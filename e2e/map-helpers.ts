// Map-pixel helpers shared by the tap and trip specs. The map canvas is opaque: FloodMap exposes the camera (data-view
// "lon,lat,zoom") so a lon/lat becomes a pixel, and the point it received (data-tap / data-dest).
import { expect, type Page } from "@playwright/test";
import { riskAt } from "../web/src/lib/geo";
import type { FloodCollection } from "../web/src/lib/types";

/** The settled camera (data-view stops changing). */
export async function settledView(page: Page) {
  const map = page.locator(".maplibregl-map");
  let last = "";
  await expect
    .poll(
      async () => {
        const v = (await map.getAttribute("data-view")) ?? "";
        const same = v !== "" && v === last;
        last = v;
        return same;
      },
      { intervals: [400], timeout: 15000 },
    )
    .toBe(true);
  const [lon, lat, zoom] = last.split(",").map(Number);
  return { lon, lat, zoom };
}

/** Web Mercator (MapLibre, 512 px tiles, no pitch or bearing): lon/lat -> pixel in the map container. */
export async function pixelOf(page: Page, lon: number, lat: number) {
  const v = await settledView(page);
  const box = (await page.locator(".maplibregl-map").boundingBox())!;
  const world = 512 * 2 ** v.zoom;
  const mx = (x: number) => ((x + 180) / 360) * world;
  const my = (y: number) => ((1 - Math.log(Math.tan(Math.PI / 4 + (y * Math.PI) / 360)) / Math.PI) / 2) * world;
  const px = box.width / 2 + mx(lon) - mx(v.lon);
  const py = box.height / 2 + my(lat) - my(v.lat);
  const inside = px > 60 && px < box.width - 60 && py > 60 && py < box.height - 60;
  return inside ? { x: box.x + px, y: box.y + py } : null;
}

/** Tap the map at lon/lat; returns the point the app received, or null when the tap hit a marker or shelter. */
export async function tapAt(page: Page, lon: number, lat: number): Promise<[number, number] | null> {
  const map = page.locator(".maplibregl-map");
  const before = await map.getAttribute("data-tap");
  const p = await pixelOf(page, lon, lat);
  if (!p) return null;
  await page.mouse.click(p.x, p.y);
  let now: string | null = null;
  try {
    await expect
      .poll(async () => ((now = await map.getAttribute("data-tap")) !== null && now !== before), { timeout: 2000 })
      .toBe(true);
  } catch {
    return null;
  }
  const got = now!.split(",").map(Number) as [number, number];
  // the click landed where it was aimed (within ~2 px at this zoom)
  const v = await settledView(page);
  const degPerPx = 360 / (512 * 2 ** v.zoom);
  expect(Math.abs(got[0] - lon)).toBeLessThan(3 * degPerPx);
  expect(Math.abs(got[1] - lat)).toBeLessThan(3 * degPerPx);
  return got;
}


/** Up to 40 interior points of flood polygons that stay wet 3 px around at the current zoom (a click lands within a
 * pixel or two); every polygon of every feature, largest rings first. */
export async function wetPoints(page: Page, flood: FloodCollection): Promise<[number, number][]> {
  const v = await settledView(page);
  const d = (3 * 360) / (512 * 2 ** v.zoom);
  const wetAround = (lon: number, lat: number) =>
    [[0, 0], [d, 0], [-d, 0], [0, d], [0, -d]].every(([dx, dy]) => riskAt(flood, lon + dx, lat + dy));
  const wet: [number, number][] = [];
  const rings = flood.features
    .flatMap((f) => (f.geometry.type === "Polygon" ? [f.geometry.coordinates[0]] : f.geometry.coordinates.map((q) => q[0])))
    .sort((a, b) => b.length - a.length);
  for (const ring of rings) {
    const lon = ring.reduce((a, p) => a + p[0], 0) / ring.length;
    const lat = ring.reduce((a, p) => a + p[1], 0) / ring.length;
    if (wetAround(lon, lat)) wet.push([lon, lat]);
    if (wet.length >= 40) break;
  }
  return wet;
}

/** Click lon/lat on the map without waiting for data-tap (a trip destination reports data-dest instead). */
export async function clickAt(page: Page, lon: number, lat: number): Promise<boolean> {
  const p = await pixelOf(page, lon, lat);
  if (!p) return false;
  await page.mouse.click(p.x, p.y);
  return true;
}

/** Drag the map until lon/lat is on screen (pixelOf != null); MapLibre pans by the drag. Returns false if it never is. */
export async function panTo(page: Page, lon: number, lat: number): Promise<boolean> {
  const map = page.locator(".maplibregl-map");
  for (let k = 0; k < 6; k++) {
    if (await pixelOf(page, lon, lat)) return true;
    const v = await settledView(page);
    const box = (await map.boundingBox())!;
    const world = 512 * 2 ** v.zoom;
    const mx = (x: number) => ((x + 180) / 360) * world;
    const my = (y: number) => ((1 - Math.log(Math.tan(Math.PI / 4 + (y * Math.PI) / 360)) / Math.PI) / 2) * world;
    // offset of the target from the centre, clamped to what one drag inside the box can move
    const dx = Math.max(-box.width / 3, Math.min(box.width / 3, mx(lon) - mx(v.lon)));
    const dy = Math.max(-box.height / 3, Math.min(box.height / 3, my(lat) - my(v.lat)));
    const cx = box.x + box.width / 2;
    const cy = box.y + box.height / 2;
    await page.mouse.move(cx, cy);
    await page.mouse.down();
    await page.mouse.move(cx - dx, cy - dy, { steps: 10 });
    await page.mouse.up();
  }
  return !!(await pixelOf(page, lon, lat));
}
