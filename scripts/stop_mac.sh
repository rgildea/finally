#!/usr/bin/env bash
# Stop and remove the FinAlly container. The data volume is preserved.
# Idempotent: safe to run when nothing is running.
set -euo pipefail

CONTAINER="finally"

if docker rm -f "$CONTAINER" >/dev/null 2>&1; then
  echo "Stopped and removed container '$CONTAINER'. Data volume preserved."
else
  echo "No running container '$CONTAINER' found."
fi
