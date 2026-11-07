/**
 * Fixed SMS alert templates (English + Swahili). These are the fallback for any
 * AI-generated text and must be reviewed by a Swahili speaker before the pitch.
 */
import type { Risk } from "./types";

export type Lang = "en" | "sw";

export interface AlertInput {
  areaName: string;
  rain: number;
  elnino: boolean;
  risk: Risk;
  place: string;
  shelter?: string;
  minutes?: number;
  /** The origin is inside the flood: there is no walking route out of it. */
  noRoute?: boolean;
  avoid: string[];
}

const RISK_SW: Record<Risk, string> = { low: "NDOGO", medium: "YA WASTANI", high: "KUBWA" };

export function alertText(lang: Lang, a: AlertInput): string {
  if (lang === "sw") {
    const parts = [
      `TAHADHARI YA MAFURIKO (${a.areaName}): hatari ${RISK_SW[a.risk]} karibu na ${a.place}`,
      `ikiwa mvua ya ${a.rain} mm itanyesha kwa saa 24${a.elnino ? " (msimu wa El Niño)" : ""}.`,
    ];
    if (a.shelter) parts.push(`Mahali salama: ${a.shelter}${a.minutes ? `, dakika ${a.minutes} kwa miguu` : ""}.`);
    else if (a.noRoute) parts.push("Hakuna njia salama kwa miguu: panda ghorofa ya juu au eneo la juu. Msalaba Mwekundu wa Kenya, simu ya bure 1199.");
    if (a.avoid.length) parts.push(`Epuka: ${a.avoid.join(", ")}.`);
    parts.push("Fuata maagizo ya serikali ya kaunti. [MAJARIBIO]");
    return parts.join(" ");
  }
  const parts = [
    `FLOOD ALERT (${a.areaName}): ${a.risk.toUpperCase()} risk near ${a.place}`,
    `if ${a.rain} mm of rain falls in 24 h${a.elnino ? " (El Niño season)" : ""}.`,
  ];
  if (a.shelter) parts.push(`Safe place: ${a.shelter}${a.minutes ? `, ${a.minutes} min on foot` : ""}.`);
  else if (a.noRoute) parts.push("No safe route on foot: move to an upper floor or high ground. Kenya Red Cross toll-free 1199.");
  if (a.avoid.length) parts.push(`Avoid: ${a.avoid.join(", ")}.`);
  parts.push("Follow county government instructions. [TEST]");
  return parts.join(" ");
}

export function adviceFallback(lang: Lang, crop: string, risk: Risk, actions: string[]): string {
  if (lang === "sw") {
    return `Ushauri kwa mkulima wa ${crop}: hatari ${RISK_SW[risk].toLowerCase()}. ${actions.join(". ")}.`;
  }
  return `Advice for ${crop} farmers: ${risk} risk. ${actions.join(". ")}.`;
}
