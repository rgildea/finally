#!/usr/bin/env bash
#
# Build the frontend static export, place it where the backend serves it, and
# run the backend with the mock LLM + market simulator on a throwaway DB. Used
# as the Playwright `webServer` so the E2E suite is self-contained without
# Docker.
#
# Env:
#   PORT             host port to serve on (default 8010)
#   SKIP_BUILD=true  reuse an existing backend/static export (faster reruns)
#
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
PORT="${PORT:-8010}"
DB_PATH="${FINALLY_DB_PATH:-/tmp/finally-e2e.db}"

if [ "${SKIP_BUILD:-false}" != "true" ]; then
  echo "[serve-local] building frontend export"
  (cd "$ROOT/frontend" && npm ci && npm run build)

  echo "[serve-local] copying export into backend/static"
  rm -rf "$ROOT/backend/static"
  mkdir -p "$ROOT/backend/static"
  cp -R "$ROOT/frontend/out/." "$ROOT/backend/static/"
fi

# Fresh DB each run so state starts from the $10k seed.
rm -f "$DB_PATH"

echo "[serve-local] starting backend on :$PORT (LLM_MOCK, simulator)"
cd "$ROOT/backend"
exec env \
  LLM_MOCK=true \
  MASSIVE_API_KEY="" \
  OPENROUTER_API_KEY="test-not-used-in-mock" \
  FINALLY_DB_PATH="$DB_PATH" \
  uv run uvicorn app.main:app --host 127.0.0.1 --port "$PORT"
