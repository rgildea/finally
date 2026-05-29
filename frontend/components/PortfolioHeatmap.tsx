"use client";

import { ResponsiveContainer, Treemap } from "recharts";
import { Panel } from "./Panel";
import { formatPct } from "@/lib/format";
import type { Position } from "@/lib/types";

interface HeatmapProps {
  positions: Position[];
  onSelect: (ticker: string) => void;
}

/** Map P&L percent to a green/red intensity for the rectangle fill. */
function fillFor(pct: number): string {
  const mag = Math.min(Math.abs(pct) / 6, 1); // saturate near +/-6%
  const alpha = 0.18 + mag * 0.62;
  const color = pct >= 0 ? "43, 213, 118" : "255, 82, 82";
  return `rgba(${color}, ${alpha.toFixed(2)})`;
}

interface CellProps {
  x?: number;
  y?: number;
  width?: number;
  height?: number;
  ticker?: string;
  plPct?: number;
  onSelect?: (ticker: string) => void;
}

function Cell({ x = 0, y = 0, width = 0, height = 0, ticker, plPct, onSelect }: CellProps) {
  if (!ticker || width <= 0 || height <= 0) return null;
  const showLabel = width > 46 && height > 28;
  const fill = fillFor(plPct ?? 0);
  return (
    <g
      onClick={() => onSelect?.(ticker)}
      data-testid={`heatmap-cell-${ticker}`}
      data-pl={(plPct ?? 0) >= 0 ? "up" : "down"}
      className="cursor-pointer"
      // fill is also exposed on the group so the cell's P&L color is
      // assertable directly on the test-id element, not just the child rect.
      style={{ transition: "opacity 150ms", fill }}
    >
      <rect
        x={x + 1}
        y={y + 1}
        width={Math.max(width - 2, 0)}
        height={Math.max(height - 2, 0)}
        rx={4}
        fill={fill}
        stroke="var(--color-line-strong)"
        strokeWidth={0.5}
      />
      {showLabel && (
        <>
          <text
            x={x + 8}
            y={y + 18}
            fill="var(--color-fg-primary)"
            fontSize={12}
            fontWeight={600}
            fontFamily="var(--font-display)"
          >
            {ticker}
          </text>
          <text
            x={x + 8}
            y={y + 33}
            fill="var(--color-fg-primary)"
            fontSize={10}
            fontFamily="var(--font-mono)"
            opacity={0.85}
          >
            {formatPct(plPct ?? 0)}
          </text>
        </>
      )}
    </g>
  );
}

export function PortfolioHeatmap({ positions, onSelect }: HeatmapProps) {
  const data = positions.map((p) => ({
    name: p.ticker,
    ticker: p.ticker,
    size: Math.max(p.market_value, 0.01),
    plPct: p.unrealized_pl_pct,
  }));

  return (
    <Panel title="Allocation · P&L">
      <div data-testid="portfolio-heatmap" className="h-full min-h-[160px] w-full p-2">
        {data.length === 0 ? (
          <div className="flex h-full items-center justify-center font-mono text-xs text-fg-faint">
            No open positions
          </div>
        ) : (
          <ResponsiveContainer width="100%" height="100%">
            <Treemap
              data={data}
              dataKey="size"
              isAnimationActive={false}
              content={<Cell onSelect={onSelect} />}
            />
          </ResponsiveContainer>
        )}
      </div>
    </Panel>
  );
}
