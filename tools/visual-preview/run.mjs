import { spawnSync } from "node:child_process";
import { readFileSync, writeFileSync, mkdirSync, readdirSync, rmSync } from "node:fs";
import { resolve } from "node:path";
import { createHash } from "node:crypto";
import { fileURLToPath } from "node:url";
const root = resolve(fileURLToPath(new URL("../..", import.meta.url)));
const app = resolve(root, "apps/web");
if (readdirSync(app).some((name) => name.startsWith(".env") && !name.endsWith(".example")))
  throw new Error("Preview refuses environment files; use an isolated checkout");
function git(...args) {
  const r = spawnSync("git", args, { cwd: root, encoding: "utf8" });
  if (r.status !== 0) throw new Error("git identity unavailable");
  return r.stdout.trim();
}
const head = git("rev-parse", "HEAD");
const branch = git("branch", "--show-current");
const before = git("status", "--porcelain", "--untracked-files=all");
if (before) throw new Error("QA requires committed changes and a clean task worktree");
for (const name of ["test-results", "playwright-report"])
  rmSync(resolve(app, name), { recursive: true, force: true });
const env = { PATH: process.env.PATH, HOME: process.env.HOME, LANG: "C.UTF-8",
  NEXT_TELEMETRY_DISABLED: "1", MEGABRAIN_VISUAL_QA: "1" };
for (const key of ["VISUAL_PREVIEW_PORT", "PLAYWRIGHT_BROWSERS_PATH"])
  if (process.env[key]) env[key] = process.env[key];
const build = spawnSync(process.execPath, ["node_modules/next/dist/bin/next", "build", "--webpack"],
  { cwd: app, stdio: "inherit", timeout: 600000, env: { ...env, NODE_ENV: "production",
    MEGABRAIN_API_INTERNAL_URL: "http://127.0.0.1:" + (Number(env.VISUAL_PREVIEW_PORT ?? 38000) + 1),
    NODE_OPTIONS: "--max-old-space-size=1536" } });
const result = build.status === 0
  ? spawnSync(process.execPath, ["node_modules/@playwright/test/cli.js", "test"],
    { cwd: app, stdio: "inherit", timeout: 600000, env: { ...env, VISUAL_PREVIEW_MODE: "built" } })
  : build;
let stats = null;
try { stats = JSON.parse(readFileSync(resolve(app, "test-results/visual-results.json"), "utf8")).stats; } catch {}
const after = git("status", "--porcelain", "--untracked-files=normal");
const identityStable = head === git("rev-parse", "HEAD") && before === after;
const evidence = {
  schemaVersion: 1, generatedAt: new Date().toISOString(),
  mode: "synthetic-frontend-preview", runtime: "next-standalone-build", branch, sourceCommit: head,
  workingTreeDirty: before.length > 0, identityStable,
  stage: build.status === 0 ? "browser" : "build",
  status: result.status === 0 && identityStable ? "passed" : "failed",
  productionEligible: false,
  scope: "Frontend rendering/interactions only; no real OIDC, database, STT or production deployment.",
  buildId: build.status === 0 ? readFileSync(resolve(app, ".next/BUILD_ID"), "utf8").trim() : null,
  buildEntrypointSha256: build.status === 0 ? createHash("sha256").update(readFileSync(resolve(app, ".next/standalone/server.js"))).digest("hex") : null,
  stats, report: stats ? "apps/web/playwright-report/index.html" : null,
  screenshots: "apps/web/test-results/visual",
};
mkdirSync(resolve(app, "test-results"), { recursive: true });
writeFileSync(resolve(app, "test-results/visual-evidence.json"), JSON.stringify(evidence, null, 2) + "\n");
console.log(JSON.stringify(evidence, null, 2));
process.exit(result.status === 0 && identityStable ? 0 : 1);
