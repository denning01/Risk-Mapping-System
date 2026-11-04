/**
 * Optional: sends a test SMS through the Africa's Talking SANDBOX (no real phone receives it;
 * view it in the sandbox simulator). Disabled unless AT_USERNAME and AT_API_KEY are set.
 */
export async function POST(req: Request) {
  const username = process.env.AT_USERNAME;
  const apiKey = process.env.AT_API_KEY;
  if (!username || !apiKey) return Response.json({ ok: false, error: "SMS not configured" }, { status: 501 });

  const body = (await req.json().catch(() => null)) as { to?: string; message?: string } | null;
  const to = String(body?.to ?? "").trim();
  const message = String(body?.message ?? "").slice(0, 480);
  if (!/^\+254\d{9}$/.test(to)) return Response.json({ ok: false, error: "Use a Kenyan number like +2547XXXXXXXX" }, { status: 400 });
  if (!message) return Response.json({ ok: false, error: "Empty message" }, { status: 400 });

  try {
    const res = await fetch("https://api.sandbox.africastalking.com/version1/messaging", {
      method: "POST",
      signal: AbortSignal.timeout(8000),
      headers: { apiKey, Accept: "application/json", "Content-Type": "application/x-www-form-urlencoded" },
      body: new URLSearchParams({ username, to, message }),
    });
    if (!res.ok) return Response.json({ ok: false, error: `Africa's Talking returned ${res.status}` }, { status: 502 });
    return Response.json({ ok: true });
  } catch {
    return Response.json({ ok: false, error: "Could not reach Africa's Talking" }, { status: 502 });
  }
}
