import http from "node:http";
import { spawn, spawnSync } from "node:child_process";
import { fileURLToPath } from "node:url";
import { resolve } from "node:path";
import { readdirSync, readFileSync, cpSync, existsSync } from "node:fs";
import { COOKIE, CSRF, initialState, detail, projection } from "./fixtures.mjs";

const port = Number(process.env.VISUAL_PREVIEW_PORT ?? 38000);
if (!Number.isInteger(port) || port < 38000 || port > 38900) throw new Error("Invalid preview port");
const root = resolve(fileURLToPath(new URL("../..", import.meta.url)));
const app = resolve(root, "apps/web");
if (readdirSync(app).some((name) => name.startsWith(".env") && !name.endsWith(".example")))
  throw new Error("Preview refuses environment files; use an isolated checkout");
if (process.env.VISUAL_PREVIEW_MODE !== "built") {
  const evidence = JSON.parse(readFileSync(resolve(app, "test-results/visual-evidence.json"), "utf8"));
  const head = spawnSync("git", ["rev-parse", "HEAD"], { cwd: root, encoding: "utf8" });
  const status = spawnSync("git", ["status", "--porcelain"], { cwd: root, encoding: "utf8" });
  if (head.status !== 0 || status.status !== 0 || status.stdout.trim() ||
      evidence.sourceCommit !== head.stdout.trim() || evidence.workingTreeDirty ||
      !evidence.identityStable || evidence.status !== "passed")
    throw new Error("Manual preview requires passing QA for the current clean commit");
}
let state = initialState();
let child;
const servers = [];
function json(res, code, data) {
  res.writeHead(code, { "Content-Type": "application/json", "Cache-Control": "no-store",
    "X-MegaBrain-Preview": "synthetic-data" });
  res.end(JSON.stringify(data));
}
function api(req, res) {
  const url = new URL(req.url, "http://127.0.0.1");
  const path = url.pathname;
  if (path === "/__preview/health") return json(res, child ? 200 : 503, { mode: "synthetic" });
  if (path === "/__preview/control" && req.method === "POST") {
    let body = "";
    req.on("data", (chunk) => { body += chunk; if (body.length > 1024) req.destroy(); });
    req.on("end", () => {
      try { state = { ...initialState(), ...JSON.parse(body || "{}") }; json(res, 200, { ok: true }); }
      catch { json(res, 400, { error: "invalid_control" }); }
    });
    return;
  }
  if (path === "/auth/login") {
    res.writeHead(303, { Location: "/inbox", "Cache-Control": "no-store",
      "Set-Cookie": COOKIE + "=synthetic; Path=/; HttpOnly; SameSite=Lax" });
    return res.end();
  }
  const owner = (req.headers.cookie ?? "").split(";").some((c) => c.trim() === COOKIE + "=synthetic");
  if (!owner) return json(res, 401, { authenticated: false });
  if (path === "/api/auth/session") return json(res, 200, {
    authenticated: true, user: { email: "preview@example.invalid" } });
  if (path === "/api/auth/csrf") return json(res, 200, { csrf_token: CSRF });
  if (path === "/api/platform/paperclip/status") return json(res, 200, { available: state.paperclip });
  if (req.method === "POST" && path === "/auth/logout") {
    res.writeHead(303, { Location: "/login",
      "Set-Cookie": COOKIE + "=; Path=/; Max-Age=0" }); return res.end();
  }
  if (state.unavailable) return json(res, 503, { error: "preview_backend_unavailable" });
  if (path === "/api/reels" && req.method === "GET") {
    const q = url.searchParams.get("q") ?? "";
    const items = state.reels.filter((r) =>
      (!url.searchParams.has("curation_status") || r.curation_status === url.searchParams.get("curation_status")) &&
      JSON.stringify(r).toLocaleLowerCase().includes(q.toLocaleLowerCase()));
    return json(res, 200, { items, query: { q },
      pagination: { page: 1, page_size: 12, has_previous: false, has_next: false } });
  }
  if (path === "/api/categories") return json(res, 200, {
    items: [{ id: 1, name: "Tecnologia", reel_count: 1 }] });
  if (path === "/api/categories/1") return json(res, 200, {
    category: { id: 1, name: "Tecnologia", reel_count: 1 }, items: [state.reels[0]],
    pagination: { page: 1, page_size: 12, has_previous: false, has_next: false } });
  const match = /^\/api\/reels\/(\d+)(?:\/(curation|transcription))?$/.exec(path);
  if (match) {
    const item = state.reels.find((r) => r.id === Number(match[1]));
    if (!item) return json(res, 404, { error: "not_found" });
    if (!match[2] && req.method === "GET") return json(res, 200, detail(item));
    if (match[2] === "transcription" && req.method === "POST") {
      if (req.headers["x-csrf-token"] !== CSRF) return json(res, 403, { error: "csrf" });
      item.transcription_status = "queued";
      return json(res, 202, projection(item));
    }
  }
  return json(res, 404, { error: "unsupported_preview_operation" });
}
function proxy(req, res) {
  if (req.url.startsWith("/api/") || req.url.startsWith("/auth/") || req.url.startsWith("/__preview/"))
    return api(req, res);
  const upstream = http.request({ hostname: "127.0.0.1", port: port + 2,
    path: req.url, method: req.method, headers: { ...req.headers, host: "127.0.0.1:" + (port + 2) } },
    (reply) => { res.writeHead(reply.statusCode ?? 502, reply.headers); reply.pipe(res); });
  upstream.setTimeout(60000, () => upstream.destroy());
  upstream.on("error", () => { if (!res.headersSent) json(res, 502, { error: "preview_starting" }); else res.destroy(); });
  req.pipe(upstream);
}
for (const [listenPort, handler] of [[port + 1, api], [port, proxy]]) {
  const server = http.createServer(handler);
  server.on("error", (error) => { console.error(error.code); cleanup(1); });
  server.listen(listenPort, "127.0.0.1");
  servers.push(server);
}
const env = { PATH: process.env.PATH, HOME: process.env.HOME, LANG: "C.UTF-8",
  NODE_ENV: "development", NEXT_TELEMETRY_DISABLED: "1",
  MEGABRAIN_API_INTERNAL_URL: "http://127.0.0.1:" + (port + 1) };
env.NODE_ENV = "production";
let args;
{
  const standalone = resolve(app, ".next/standalone");
  if (!existsSync(resolve(standalone, "server.js"))) throw new Error("Run qa:visual to build first");
  cpSync(resolve(app, ".next/static"), resolve(standalone, ".next/static"), { recursive: true });
  if (existsSync(resolve(app, "public")))
    cpSync(resolve(app, "public"), resolve(standalone, "public"), { recursive: true });
  env.HOSTNAME = "127.0.0.1";
  env.PORT = String(port + 2);
  args = [".next/standalone/server.js"];
}
child = spawn(process.execPath, args, { cwd: app, env, stdio: "inherit" });
child.on("exit", (code) => cleanup(code ?? 1));
child.on("error", () => cleanup(1));
let stopping = false;
function cleanup(code = 0) {
  if (stopping) return;
  stopping = true;
  child?.kill("SIGTERM");
  for (const server of servers) server.close();
  setTimeout(() => process.exit(code), 1500).unref();
}
const ttl = setTimeout(() => cleanup(), 15 * 60 * 1000);
ttl.unref();
process.on("SIGTERM", () => cleanup());
process.on("SIGINT", () => cleanup());
console.log("Synthetic preview at http://127.0.0.1:" + port + " (no production data)");
