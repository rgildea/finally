# FinAlly Frontend

The trading terminal UI: a Next.js (App Router) + TypeScript single-page app,
styled with Tailwind v4 in a dark, Bloomberg-inspired theme.

## Develop

```bash
npm install
npm run dev      # http://localhost:3000, proxies /api -> http://localhost:8000
```

The backend must be running on port 8000 for live data. In dev, `next.config.ts`
rewrites `/api/*` to the backend; in production the app is a static export served
by FastAPI from the same origin, so no proxy or CORS is needed.

## Verify

```bash
npm test         # vitest unit/component tests
npm run lint     # eslint
npm run build    # static export -> out/
```

## Layout

- `app/` — root layout (fonts, theme) and the terminal page.
- `components/` — panels: watchlist, detail chart, heatmap, P&L chart, positions
  table, trade bar, AI chat, header.
- `lib/` — typed API client (`api.ts`), SSE price stream (`usePriceStream.ts`),
  chat SSE parser (`chatStream.ts`), formatters, and hooks.

Live prices arrive over SSE (`EventSource('/api/stream/prices')`); sparkline and
detail-chart history are accumulated client-side from that stream. The P&L chart
reads `GET /api/portfolio/history`. The chat panel consumes the
`token`/`action`/`done`/`error` SSE protocol from `POST /api/chat`.
