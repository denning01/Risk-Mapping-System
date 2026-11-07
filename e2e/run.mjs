#!/usr/bin/env node
// `npm run test:e2e` — E-14. Builds the app (unless E2E_SKIP_BUILD=1, which verify-all sets because its step 6
// has just built it), picks a free port, and runs the Playwright suite against `next start` on that port.
// Never touches web/package.json, web/src or web/scripts: it only runs web's own `next` binary.
import { spawnSync } from "node:child_process";
import { createServer } from "node:net";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";

const root = join(dirname(fileURLToPath(import.meta.url)), "..");
const web = join(root, "web");

if (process.env.E2E_SKIP_BUILD !== "1") {
  console.log("e2e: building the app (web: next build)");
  const b = spawnSync("npx", ["next", "build"], { cwd: web, stdio: "inherit" });
  if (b.status !== 0) process.exit(b.status ?? 1);
}

const port = await new Promise((res, rej) => {
  const s = createServer();
  s.once("error", rej);
  s.listen(0, "127.0.0.1", () => {
    const p = s.address().port;
    s.close(() => res(p));
  });
});
console.log(`e2e: next start on free port ${port}`);

const r = spawnSync("npx", ["playwright", "test", "--config", join(root, "e2e/playwright.config.ts"), ...process.argv.slice(2)], {
  cwd: root,
  stdio: "inherit",
  env: { ...process.env, E2E_PORT: String(port) },
});
process.exit(r.status ?? 1);
