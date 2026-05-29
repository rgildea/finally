# FinAlly E2E tests

Playwright end-to-end suite (TypeScript). Drives the real app — FastAPI serving
the Next.js static export plus the API — with the mock LLM enabled.

## Run (default: self-contained, no Docker)

The Playwright `webServer` builds the frontend export, copies it into
`backend/static/`, and starts the backend with the mock LLM + market simulator
on a throwaway DB (so every run starts from the $10,000 seed). It serves on
host port 8010 by default. See `scripts/serve-local.sh`.

```bash
cd test
npm ci
npx playwright install chromium
FRESH_VOLUME=true npm test
```

`FRESH_VOLUME=true` asserts the seeded $10,000 cash exactly (always true with
the throwaway DB). After the first run, `SKIP_BUILD=true npm test` reuses the
existing `backend/static/` export for faster reruns.

## Run against an already-running instance

Skip the managed server and point at any live app (e.g. the Docker container):

```bash
cd test
EXTERNAL_SERVER=true BASE_URL=http://localhost:8010 npm test
```

## Run against the Docker container

The test compose maps host port 8010 to the container's 8000 to avoid host
conflicts. It builds the production image and runs it with `LLM_MOCK=true`.

```bash
# From the repo root.
docker compose -f test/docker-compose.test.yml up --build -d

cd test && EXTERNAL_SERVER=true BASE_URL=http://localhost:8010 npm test

# Tear down.
docker compose -f test/docker-compose.test.yml down -v
```

## Scenarios

| Spec | Covers |
|------|--------|
| `01-fresh-start` | Default 10-ticker watchlist, cash shown, prices streaming, connected |
| `02-watchlist` | Add and remove a ticker via the UI |
| `03-trade` | Buy then sell: cash and positions update |
| `04-portfolio-viz` | Heatmap cell color, P&L chart has data points |
| `05-chat` | Mocked AI chat: streamed reply, inline trade confirmation |
| `06-sse-reconnect` | Stream drops and the connection recovers |

## Selector contract

Tests reference `data-testid` attributes defined in
`tests/support/selectors.ts`. The frontend must expose every id listed there.
