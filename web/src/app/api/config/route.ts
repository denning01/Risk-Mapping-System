import { connection } from "next/server";

/** Tells the client which optional (Tier 2) features have keys configured. Never returns the keys. */
export async function GET() {
  await connection(); // read env at request time, not at build time
  return Response.json({
    ai: Boolean(process.env.ANTHROPIC_API_KEY),
    sms: Boolean(process.env.AT_USERNAME && process.env.AT_API_KEY),
  });
}
