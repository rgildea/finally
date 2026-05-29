import type { NextConfig } from "next";

const isDev = process.env.NODE_ENV === "development";

/**
 * Production builds are a fully static export served by FastAPI from
 * `backend/static/`. During `next dev` we drop export mode and proxy
 * `/api/*` to the local backend so SSE streams and REST calls resolve
 * same-origin (rewrites are unsupported under `output: 'export'`).
 */
const nextConfig: NextConfig = {
  output: isDev ? undefined : "export",
  images: { unoptimized: true },
  ...(isDev && {
    async rewrites() {
      return [
        {
          // 127.0.0.1 (not "localhost") so the proxy hits the backend's IPv4
          // bind; "localhost" can resolve to ::1 where uvicorn isn't listening.
          source: "/api/:path*",
          destination: "http://127.0.0.1:8000/api/:path*",
        },
      ];
    },
  }),
};

export default nextConfig;
