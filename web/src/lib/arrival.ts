/**
 * M-21 · how flood arrival time is worded (operator, from E-20). The contract's arrival_h is the FAST bound (the M-20
 * ruling: "water could arrive in as little as X h"). Never "0 h": zero-hour cells are local rain or a nearby stream.
 */

/** Hours as shown: one decimal below 10 h, whole hours above. Only called for h >= 1, so never "0". */
function fmtHours(h: number): string {
  return h < 10 ? `${Math.round(h * 10) / 10}` : `${Math.round(h)}`;
}

/** The popup sentence for a flood feature's arrival_h (null -> no estimate). */
export function arrivalSentence(h: number | null): string {
  if (h === null || !Number.isFinite(h)) return "No arrival estimate for this area";
  if (h < 1) return "Water could arrive within minutes (local rain or nearby stream)";
  return `Water could arrive in as little as ~${fmtHours(h)} h (screening estimate)`;
}

/** A legend tick: "minutes" under 1 h, else "~X h". */
export function arrivalTick(h: number): string {
  return h < 1 ? "minutes" : `~${fmtHours(h)} h`;
}
