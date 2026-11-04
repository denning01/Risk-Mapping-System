import { CropRuleSchema } from "@/lib/schema";
import { adviceFallback, type Lang } from "@/lib/alertTemplates";

/**
 * Optional: turns one crops.json rule into a short plain-language advisory with the Claude API.
 * Grounded strictly in the rule. Falls back to the fixed template on any error or after 5 s.
 */
export async function POST(req: Request) {
  const body = (await req.json().catch(() => null)) as { rule?: unknown; lang?: Lang; rain?: number } | null;
  const parsed = CropRuleSchema.safeParse(body?.rule);
  if (!parsed.success) return Response.json({ error: "Invalid rule" }, { status: 400 });
  const rule = parsed.data;
  const lang: Lang = body?.lang === "sw" ? "sw" : "en";
  const fallback = { text: adviceFallback(lang, rule.crop, rule.risk, rule.actions), generated: false };

  const key = process.env.ANTHROPIC_API_KEY;
  if (!key) return Response.json(fallback);

  const language = lang === "sw" ? "Kiswahili" : "English";
  const prompt = `Write a short SMS-style farm advisory (max 320 characters) in ${language} for a ${rule.crop} farmer in Nyando, Kisumu, Kenya.
Use ONLY these facts. Do not add any other advice, numbers or claims.
- Season: ${rule.season.replace("_", " ")}
- ENSO state: ${rule.enso === "elnino" ? "El Niño" : "normal"}
- Flood risk to this crop: ${rule.risk}
- Scenario rainfall: ${Number(body?.rain) || "unknown"} mm in 24 hours (a scenario, not a forecast)
- Actions: ${rule.actions.join("; ")}
Return only the message text.`;

  try {
    const res = await fetch("https://api.anthropic.com/v1/messages", {
      method: "POST",
      signal: AbortSignal.timeout(5000),
      headers: {
        "content-type": "application/json",
        "x-api-key": key,
        "anthropic-version": "2023-06-01",
      },
      body: JSON.stringify({
        model: process.env.ANTHROPIC_MODEL || "claude-haiku-4-5",
        max_tokens: 300,
        messages: [{ role: "user", content: prompt }],
      }),
    });
    if (!res.ok) return Response.json(fallback);
    const json = (await res.json()) as { content?: { type: string; text?: string }[] };
    const text = json.content?.find((c) => c.type === "text")?.text?.trim();
    return Response.json(text ? { text, generated: true } : fallback);
  } catch {
    return Response.json(fallback);
  }
}
