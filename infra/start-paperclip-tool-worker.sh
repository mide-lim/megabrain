#!/bin/sh
set -eu

BASE=/home/megabrain-hermes/.local/share/megabrain-runtime/paperclip-prod
WORKER_DIR="$BASE/tool-worker"
SOURCE_CONFIG="$BASE/config.json"
WORKER_CONFIG="$WORKER_DIR/config.json"

mkdir -p "$WORKER_DIR/home" "$WORKER_DIR/logs"

export DATABASE_URL="$(
  /usr/local/bin/node - <<'NODE'
const user = encodeURIComponent(process.env.POSTGRES_USER || "");
const pass = encodeURIComponent(process.env.POSTGRES_PASSWORD || "");
const host = process.env.PAPERCLIP_DB_HOST || "postgres";
const db = process.env.PAPERCLIP_DB_NAME || "paperclip_prod";
if (!user || !pass) process.exit(2);
process.stdout.write(`postgresql://${user}:${pass}@${host}:5432/${db}`);
NODE
)"

SOURCE_CONFIG="$SOURCE_CONFIG" WORKER_CONFIG="$WORKER_CONFIG" /usr/local/bin/node <<'NODE'
const fs = require("fs");
const src = process.env.SOURCE_CONFIG;
const dst = process.env.WORKER_CONFIG;
const cfg = JSON.parse(fs.readFileSync(src, "utf8"));
cfg.server = {
  ...(cfg.server || {}),
  deploymentMode: "authenticated",
  exposure: "public",
  bind: "lan",
  host: "0.0.0.0",
  port: 13101,
  serveUi: false,
  allowedHostnames: ["paperclip-tool-worker", "paperclip", "paperclip.midelim.tech"]
};
cfg.logging = {
  ...(cfg.logging || {}),
  mode: "file",
  logDir: "/home/megabrain-hermes/.local/share/megabrain-runtime/paperclip-prod/tool-worker/logs"
};
cfg.database = {
  ...(cfg.database || {}),
  mode: "postgres",
  connectionString: process.env.DATABASE_URL,
  backup: {
    enabled: false,
    intervalMinutes: 60,
    retentionDays: 7,
    dir: "/home/megabrain-hermes/.local/share/megabrain-runtime/paperclip-prod/tool-worker/backups"
  }
};
fs.writeFileSync(dst, JSON.stringify(cfg, null, 2) + "\n", { mode: 0o600 });
NODE

exec /usr/local/bin/node \
  /home/megabrain-hermes/.local/share/megabrain-labs/paperclip/v2-o2-cockpit/tooling/node_modules/pnpm/bin/pnpm.cjs \
  --dir /home/megabrain-hermes/.local/share/megabrain-labs/paperclip/v2-o2-c1c-auth-exchange/source \
  paperclipai run \
  --config "$WORKER_CONFIG" \
  --no-repair
