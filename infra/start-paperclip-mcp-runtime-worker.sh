#!/bin/sh
set -eu

SOURCE=/home/megabrain-hermes/.local/share/megabrain-labs/paperclip/v2-o2-c1c-auth-exchange/source

export DATABASE_URL="$(
  node - <<'NODE'
const user = encodeURIComponent(process.env.POSTGRES_USER || "");
const pass = encodeURIComponent(process.env.POSTGRES_PASSWORD || "");
const host = process.env.PAPERCLIP_DB_HOST || "postgres";
const db = process.env.PAPERCLIP_DB_NAME || "paperclip_prod";
if (!user || !pass) process.exit(2);
process.stdout.write(`postgresql://${user}:${pass}@${host}:5432/${db}`);
NODE
)"
cd "$SOURCE/server"
exec ./node_modules/.bin/tsx src/mcp-runtime-worker.ts
