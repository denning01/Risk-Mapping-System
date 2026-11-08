"use client";

/**
 * M-16 · FROM -> TO on foot with up to 3 alternatives and a route analysis per alternative. An ADDED option: the
 * nearest-safe-place answer in SafePlacesPanel stays the default after a tap (operator constraint, 2026-11-08).
 */
import type { TripAlt } from "@/lib/routing";
import type { FloodNext } from "@/lib/tripAnalysis";
import { Badge, Card } from "./ui";

export type TripDestOption = { id: string; name: string; lon: number; lat: number; targetId?: string; group: "Places" | "Safe places" };
export type TripView =
  | { state: "idle" }
  | { state: "pending" }
  | { state: "refused"; reason: string }
  | { state: "ok"; alts: (TripAlt & { flood: FloodNext | null })[] };

const ALT_LABELS: Record<TripAlt["label"], string> = {
  fastest: "Fastest safe route",
  safer: "Safer: fewer paths next to water",
  alternative: "Another way",
};
export const TRIP_REFUSALS: Record<string, { text: string; danger?: boolean }> = {
  wet_start: { text: "Your starting point is inside the flood extent in this scenario, so no route leaves it on dry ground.", danger: true },
  cut_off_start: { text: "The nearest path to your starting point is flooded in this scenario, so no route leaves it on dry ground.", danger: true },
  wet_dest: { text: "This destination is inside the flood extent in this scenario. Choose another destination." },
  cut_off_dest: { text: "The paths at this destination are flooded in this scenario. Choose another destination." },
  far_start: { text: "Your starting point is more than 500 m from any mapped road or path." },
  far_dest: { text: "This destination is more than 500 m from any mapped road or path." },
  unreachable: { text: "No dry path connects these two points in this scenario." },
  graph: { text: "The road network could not be loaded, so trips are unavailable." },
};

export function TripPanel(props: {
  startName: string | null;
  options: TripDestOption[];
  destId: string | null;
  destName: string | null;
  picking: boolean;
  onDest: (id: string) => void;
  onPickOnMap: () => void;
  onClear: () => void;
  view: TripView;
  choice: number;
  onChoice: (i: number) => void;
}) {
  const { view } = props;
  const refusal = view.state === "refused" ? TRIP_REFUSALS[view.reason] : null;
  return (
    <Card title="Plan a trip (from → to)" right={<Badge>Option</Badge>}>
      <p className="text-[11px] text-zinc-500">
        From: <b className="text-zinc-800">{props.startName ?? "choose a starting point above, or tap the map"}</b>
      </p>
      <label className="mt-1 block text-[11px] font-medium text-zinc-500" htmlFor="trip-dest">
        To
      </label>
      <select
        id="trip-dest"
        value={props.destId ?? ""}
        onChange={(e) => props.onDest(e.target.value)}
        disabled={!props.startName}
        className="mt-0.5 w-full rounded-lg border border-zinc-300 bg-white px-2 py-1.5 text-sm disabled:opacity-50"
      >
        <option value="" disabled>
          Choose a destination…
        </option>
        {props.destId === "map" && <option value="map">{props.destName}</option>}
        {(["Places", "Safe places"] as const).map((grp) => (
          <optgroup key={grp} label={grp}>
            {props.options
              .filter((o) => o.group === grp)
              .map((o) => (
                <option key={o.id} value={o.id}>
                  {o.name}
                </option>
              ))}
          </optgroup>
        ))}
      </select>
      <div className="mt-1.5 flex flex-wrap gap-2 text-[11px]">
        <button
          onClick={props.onPickOnMap}
          disabled={!props.startName}
          className={`rounded-md border px-2 py-0.5 font-semibold disabled:opacity-50 ${props.picking ? "border-violet-600 bg-violet-600 text-white" : "border-violet-600 text-violet-700 hover:bg-violet-50"}`}
        >
          {props.picking ? "Tap the map for the destination…" : "Pick destination on the map"}
        </button>
        {props.destId && (
          <button onClick={props.onClear} className="rounded-md border border-zinc-300 px-2 py-0.5 font-semibold text-zinc-700 hover:bg-zinc-50">
            Clear trip (back to nearest safe place)
          </button>
        )}
      </div>

      {view.state === "pending" && <p className="mt-3 text-sm text-zinc-600">Finding routes on foot…</p>}
      {refusal &&
        (refusal.danger ? (
          <div className="mt-3 rounded-lg border border-red-300 bg-red-50 p-2 text-sm" data-trip-refusal={view.state === "refused" ? view.reason : undefined}>
            <div className="font-semibold text-red-800">No safe route on foot.</div>
            <p className="mt-1 text-red-900">
              Move to an upper floor or high ground and call for help: Kenya Red Cross toll-free{" "}
              <a href="tel:1199" className="font-bold underline">
                1199
              </a>
              .
            </p>
            <p className="mt-1 text-[11px] text-red-700">{refusal.text}</p>
          </div>
        ) : (
          <p className="mt-3 rounded-lg bg-amber-50 p-2 text-sm text-amber-900" data-trip-refusal={view.state === "refused" ? view.reason : undefined}>
            No route: {refusal.text}
          </p>
        ))}

      {view.state === "ok" && (
        <div className="mt-3 space-y-1.5" role="radiogroup" aria-label="Route alternatives">
          {view.alts.map((a, i) => (
            <button
              key={a.label}
              role="radio"
              aria-checked={props.choice === i}
              data-alt={a.label}
              onClick={() => props.onChoice(i)}
              className={`w-full rounded-lg border p-2 text-left text-sm ${props.choice === i ? "border-blue-600 bg-blue-50" : "border-zinc-200 bg-white hover:bg-zinc-50"}`}
            >
              <div className="flex items-center gap-2">
                <span className={`inline-block h-1 w-6 rounded ${props.choice === i ? "bg-blue-600" : "bg-slate-500"}`} />
                <b>{ALT_LABELS[a.label]}</b>
                {a.extraMin > 0 && <Badge tone="amber">+{a.extraMin} min</Badge>}
              </div>
              <div className="mt-0.5 text-zinc-700">
                <b>{a.minutes} min</b> · {(a.metres / 1000).toFixed(1)} km
              </div>
              <div className="text-[11px] text-zinc-600">
                {Math.round(a.nearM)} m on paths within 30 m of flood water ·{" "}
                {a.flood ? (
                  <>
                    water next to the route: <b className="capitalize">{a.flood.risk}</b> risk, up to ~{a.flood.depthMax} m deep
                  </>
                ) : (
                  "no mapped flood within 30 m"
                )}
              </div>
            </button>
          ))}
          <p className="text-[11px] text-zinc-500">
            Computed in your browser on the mapped roads and paths for this scenario: flooded paths are never used. The fastest route may pass close
            to water; the safer one costs paths next to water 3× and shows the extra minutes. Rain at the start and the destination is in “My weather”.
            Screening-level, not a forecast.
          </p>
        </div>
      )}
    </Card>
  );
}
