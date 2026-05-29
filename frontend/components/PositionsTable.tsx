"use client";

import { Panel } from "./Panel";
import { useFlash } from "@/lib/useFlash";
import {
  formatPrice,
  formatPct,
  formatSignedPrice,
  formatQty,
} from "@/lib/format";
import type { Position, PriceUpdate } from "@/lib/types";

interface PositionsTableProps {
  positions: Position[];
  quotes: Record<string, PriceUpdate>;
  onSelect: (ticker: string) => void;
}

/** Recompute a position's market value and P&L against the live price. */
function reprice(p: Position, livePrice: number | undefined): Position {
  if (livePrice == null) return p;
  const market_value = p.quantity * livePrice;
  const cost = p.quantity * p.avg_cost;
  const unrealized_pl = market_value - cost;
  return {
    ...p,
    current_price: livePrice,
    market_value,
    unrealized_pl,
    unrealized_pl_pct: cost ? (unrealized_pl / cost) * 100 : 0,
  };
}

export function PositionsTable({ positions, quotes, onSelect }: PositionsTableProps) {
  return (
    <Panel title="Positions" scroll>
      {positions.length === 0 ? (
        <div
          data-testid="positions-table"
          className="flex h-full min-h-[120px] items-center justify-center font-mono text-xs text-fg-faint"
        >
          No open positions
        </div>
      ) : (
        <table data-testid="positions-table" className="w-full border-collapse text-right">
          <thead className="sticky top-0 bg-surface">
            <tr className="font-mono text-[10px] uppercase tracking-wider text-fg-faint">
              <th className="px-3 py-2 text-left font-medium">Ticker</th>
              <th className="px-3 py-2 font-medium">Qty</th>
              <th className="px-3 py-2 font-medium">Avg</th>
              <th className="px-3 py-2 font-medium">Last</th>
              <th className="px-3 py-2 font-medium">Value</th>
              <th className="px-3 py-2 font-medium">P&L</th>
              <th className="px-3 py-2 font-medium">%</th>
            </tr>
          </thead>
          <tbody>
            {positions.map((raw) => (
              <Row
                key={raw.ticker}
                position={reprice(raw, quotes[raw.ticker]?.price)}
                onSelect={() => onSelect(raw.ticker)}
              />
            ))}
          </tbody>
        </table>
      )}
    </Panel>
  );
}

function Row({ position: p, onSelect }: { position: Position; onSelect: () => void }) {
  const flash = useFlash(p.current_price);
  const up = p.unrealized_pl >= 0;
  return (
    <tr
      onClick={onSelect}
      data-testid={`position-row-${p.ticker}`}
      className={`cursor-pointer border-t border-line/50 transition-colors hover:bg-surface-raised/60 ${
        flash === "up" ? "animate-flash-up" : ""
      } ${flash === "down" ? "animate-flash-down" : ""}`}
    >
      <td className="px-3 py-2 text-left font-display text-sm font-semibold text-fg-primary">
        {p.ticker}
      </td>
      <td
        data-testid={`position-quantity-${p.ticker}`}
        className="tabular px-3 py-2 text-xs text-fg-muted"
      >
        {formatQty(p.quantity)}
      </td>
      <td className="tabular px-3 py-2 text-xs text-fg-muted">{formatPrice(p.avg_cost)}</td>
      <td className="tabular px-3 py-2 text-xs text-fg-primary">{formatPrice(p.current_price)}</td>
      <td className="tabular px-3 py-2 text-xs text-fg-primary">{formatPrice(p.market_value)}</td>
      <td className={`tabular px-3 py-2 text-xs ${up ? "text-up" : "text-down"}`}>
        {formatSignedPrice(p.unrealized_pl)}
      </td>
      <td className={`tabular px-3 py-2 text-xs ${up ? "text-up" : "text-down"}`}>
        {formatPct(p.unrealized_pl_pct)}
      </td>
    </tr>
  );
}
