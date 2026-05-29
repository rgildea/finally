#!/usr/bin/env bash
# Build and run the FinAlly container on http://localhost:8000.
# Idempotent: safe to run repeatedly. Always rebuilds so source changes are
# picked up; Docker's layer cache makes an unchanged rebuild fast and prevents
# serving a stale frontend. Pass --build to force a clean --no-cache rebuild.
set -euo pipefail

IMAGE="finally"
CONTAINER="finally"
VOLUME="finally-data"
PORT="8000"

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT_DIR"

NO_CACHE=""
[[ "${1:-}" == "--build" ]] && NO_CACHE="--no-cache"

if [[ ! -f .env ]]; then
  echo "No .env found; copying .env.example. Edit it to add your OPENROUTER_API_KEY."
  cp .env.example .env
fi

# Always build; the layer cache skips unchanged steps (incl. the frontend build),
# so a no-op run is fast while source changes are always picked up.
echo "Building image '$IMAGE'..."
docker build $NO_CACHE -t "$IMAGE" .

# Friendly hint about the market data source (does not mutate .env).
MASSIVE_KEY="$(grep -E '^MASSIVE_API_KEY=' .env | tail -1 | cut -d= -f2- || true)"
if [[ -n "$MASSIVE_KEY" ]]; then
  echo "Using Massive live data; blank MASSIVE_API_KEY in .env to use the simulator."
fi

# Remove any existing container so this is safe to re-run.
docker rm -f "$CONTAINER" >/dev/null 2>&1 || true

echo "Starting container '$CONTAINER'..."
docker run -d \
  --name "$CONTAINER" \
  --env-file .env \
  -e FINALLY_DB_PATH=/app/db/finally.db \
  -v "$VOLUME:/app/db" \
  -p "$PORT:8000" \
  "$IMAGE" >/dev/null

URL="http://localhost:$PORT"
echo "FinAlly is running at $URL"

if command -v open >/dev/null 2>&1; then
  open "$URL"
fi
