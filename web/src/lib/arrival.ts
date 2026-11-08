/**
 * M-21 · how flood arrival time is worded. Never "0 h": zero-hour cells are local rain or a nearby stream.
 *
 * F18.1 (ROUND 18 · AUDITOR) + RULING F18.1 (operator): a flood FEATURE's arrival_h is the MEDIAN of its cells'
 * fast-bound hours (exposure E-20: max(0.1, round(median, 1))), within one arrival band (E-20 splits each depth band by
 * band). Its sentence gives the band, derived here from arrival_h with exposure's own edges (classify_arrival_band:
 * <1 | 1<=h<3 | 3<=h<=6 | >6), and the median as "typical", never "as little as". Only a true minimum says "as little
 * as": the hexagons' arrival_h_min (earliest fast hours over the hexagon's wet cells), rounded DOWN.
 */

/** Hours as shown: one decimal below 10 h, whole hours above. Only called for h >= 1, so never "0". */
function fmtHours(h: number): string {
  return h < 10 ? `${Math.round(h * 10) / 10}` : `${Math.round(h)}`;
}
/** The same, rounded DOWN (for a lower bound): 1.06 -> "1", 9.99 -> "9.9", 12.9 -> "12". */
function fmtHoursFloor(h: number): string {
  return h < 10 ? `${Math.floor(h * 10 + 1e-9) / 10}` : `${Math.floor(h + 1e-9)}`;
}
const MINUTES = "Water could arrive within minutes (local rain or nearby stream)";
const NONE = "No arrival estimate for this area";

export type ArrivalBand = "minutes" | "1-3 h" | "3-6 h" | "more than 6 h";
/** exposure's classify_arrival_band (07_scenarios.py), on the feature's arrival_h */
export function arrivalBand(h: number): ArrivalBand {
  return h < 1 ? "minutes" : h < 3 ? "1-3 h" : h <= 6 ? "3-6 h" : "more than 6 h";
}

/** The popup sentence for a flood FEATURE's arrival_h, a median, with its band (null -> no estimate). */
export function arrivalSentence(h: number | null): string {
  if (h === null || !Number.isFinite(h)) return NONE;
  const band = arrivalBand(h);
  // a median under 1 h is not printed as "~0.x h": the band says it (and never "0 h")
  if (band === "minutes") return "Water could arrive within minutes here (local rain or nearby stream; screening estimate)";
  const when = band === "more than 6 h" ? "in more than 6 h" : `within ${band}`;
  return `Water could arrive ${when} here (typical ~${fmtHours(h)} h), sooner in places (screening estimate)`;
}

/** The sentence for a true MINIMUM (a hexagon's arrival_h_min): a lower bound, shown rounded down. */
export function arrivalMinSentence(h: number | null): string {
  if (h === null || !Number.isFinite(h)) return NONE;
  if (h < 1) return MINUTES;
  return `Water could arrive in as little as ~${fmtHoursFloor(h)} h (screening estimate)`;
}

/** A legend tick: "minutes" under 1 h, else "~X h" (F18.3: a non-finite value shows nothing). */
export function arrivalTick(h: number): string {
  if (!Number.isFinite(h)) return "";
  return h < 1 ? "minutes" : `~${fmtHours(h)} h`;
}
