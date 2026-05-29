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
import { formatPrice } from "@/lib/format";
import type { Snapshot } from "@/lib/types";

interface PnlChartProps {
  snapshots: Snapshot[];
}

const timeFmt = new Intl.DateTimeFormat("en-US", {
  hour: "2-digit",
  minute: "2-digit",
  hour12: false,
});

/** Portfolio total value over time, from GET /api/portfolio/history. */
export function PnlChart({ snapshots }: PnlChartProps) {
  const data = snapshots.map((s) => ({
    t: Date.parse(s.recorded_at),
    value: s.total_value,
  }));
  const gained =
    data.length >= 2 ? data[data.length - 1].value >= data[0].value : true;
  const stroke = gained ? "var(--color-up)" : "var(--color-down)";

  return (
    <Panel title="Portfolio Value">
      <div data-testid="pnl-chart" className="h-full min-h-[140px] w-full p-2">
        {data.length < 2 ? (
          <div className="flex h-full items-center justify-center font-mono text-xs text-fg-faint">
            Tracking value…
          </div>
        ) : (
          <ResponsiveContainer width="100%" height="100%">
            <AreaChart data={data} margin={{ top: 8, right: 8, bottom: 0, left: 0 }}>
              <defs>
                <linearGradient id="pnlFill" x1="0" y1="0" x2="0" y2="1">
                  <stop offset="0%" stopColor={stroke} stopOpacity={0.28} />
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
                formatter={(v) => [formatPrice(Number(v)), "Value"]}
              />
              <Area
                type="monotone"
                dataKey="value"
                stroke={stroke}
                strokeWidth={1.8}
                fill="url(#pnlFill)"
                isAnimationActive={false}
              />
            </AreaChart>
          </ResponsiveContainer>
        )}
      </div>
    </Panel>
  );
}
