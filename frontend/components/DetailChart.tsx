"use client";

import {
  Area,
  AreaChart,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";
import { Panel } from "./Panel";
import { formatPrice, formatPct } from "@/lib/format";
import type { PricePoint } from "@/lib/usePriceStream";
import type { PriceUpdate } from "@/lib/types";

interface DetailChartProps {
  ticker: string | null;
  points: PricePoint[];
  quote: PriceUpdate | undefined;
}

const timeFmt = new Intl.DateTimeFormat("en-US", {
  hour: "2-digit",
  minute: "2-digit",
  hour12: false,
});

export function DetailChart({ ticker, points, quote }: DetailChartProps) {
  const up = (quote?.change_pct ?? 0) >= 0;
  const stroke = up ? "var(--color-up)" : "var(--color-down)";
  const data = points.map((p) => ({ t: p.t, price: p.price }));

  return (
    <Panel
      title={ticker ? `${ticker} · Live` : "Chart"}
      action={
        quote && (
          <div className="flex items-baseline gap-3">
            <span className="tabular text-lg font-semibold text-fg-primary">
              {formatPrice(quote.price)}
            </span>
            <span className={`tabular text-xs ${up ? "text-up" : "text-down"}`}>
              {formatPct(quote.change_pct)}
            </span>
          </div>
        )
      }
    >
      <div className="h-full min-h-[200px] w-full p-2">
        {data.length < 2 ? (
          <div className="flex h-full items-center justify-center font-mono text-xs text-fg-faint">
            {ticker ? "Accumulating live data…" : "Select a ticker"}
          </div>
        ) : (
          <ResponsiveContainer width="100%" height="100%">
            <AreaChart data={data} margin={{ top: 8, right: 8, bottom: 0, left: 0 }}>
              <defs>
                <linearGradient id="detailFill" x1="0" y1="0" x2="0" y2="1">
                  <stop offset="0%" stopColor={stroke} stopOpacity={0.3} />
                  <stop offset="100%" stopColor={stroke} stopOpacity={0} />
                </linearGradient>
              </defs>
              <XAxis
                dataKey="t"
                type="number"
                domain={["dataMin", "dataMax"]}
                scale="time"
                tickFormatter={(t) => timeFmt.format(new Date(t))}
                tick={{ fill: "var(--color-fg-faint)", fontSize: 10 }}
                stroke="var(--color-line)"
                minTickGap={48}
              />
              <YAxis
                domain={["auto", "auto"]}
                orientation="right"
                width={56}
                tickFormatter={(v) => formatPrice(v)}
                tick={{ fill: "var(--color-fg-faint)", fontSize: 10 }}
                stroke="var(--color-line)"
              />
              <Tooltip
                contentStyle={{
                  background: "var(--color-surface-inset)",
                  border: "1px solid var(--color-line-strong)",
                  borderRadius: 8,
                  fontSize: 12,
                }}
                labelFormatter={(t) => timeFmt.format(new Date(t as number))}
                formatter={(v) => [formatPrice(Number(v)), "Price"]}
              />
              <Area
                type="monotone"
                dataKey="price"
                stroke={stroke}
                strokeWidth={1.8}
                fill="url(#detailFill)"
                isAnimationActive={false}
              />
            </AreaChart>
          </ResponsiveContainer>
        )}
      </div>
    </Panel>
  );
}
