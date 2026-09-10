import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import test from "node:test";

const repositoryRoot = new URL("../../../", import.meta.url);

test("C2 Caddy routing assigns only selected application routes to Next", async () => {
  const caddy = await readFile(new URL("infra/Caddyfile", repositoryRoot), "utf8");

  for (const route of ["/", "/login", "/inbox", "/inbox/*", "/library", "/library/*", "/categories", "/categories/*", "/settings", "/settings/*", "/_next/*"]) {
    assert.match(caddy, new RegExp(`handle ${route.replaceAll("*", "\\*")} \\{\\n\\t\\treverse_proxy frontend:3000`));
  }
  assert.match(caddy, /handle \{\n\t\treverse_proxy web:8000/);
  assert.match(caddy, /n8n\.midelim\.tech \{\n\treverse_proxy n8n:5678/);
  assert.doesNotMatch(caddy, /basic_auth/i);
});

test("frontend health probe no longer reserves an application /api path", async () => {
  const compose = await readFile(new URL("infra/docker-compose.yml", repositoryRoot), "utf8");
  const healthRoute = await readFile(new URL("../src/app/healthz/route.ts", import.meta.url), "utf8");

  assert.match(compose, /127\.0\.0\.1:3000\/healthz/);
  assert.doesNotMatch(compose, /127\.0\.0\.1:3000\/api\/health/);
  assert.match(healthRoute, /status: "healthy"/);
});
