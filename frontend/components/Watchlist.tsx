"use client";

import { useState, type FormEvent } from "react";
import { Panel } from "./Panel";
import { Sparkline } from "./Sparkline";
import { useFlash } from "@/lib/useFlash";
import type { PricePoint } from "@/lib/usePriceStream";
import { formatPrice, formatPct } from "@/lib/format";
import type { PriceUpdate, WatchlistItem } from "@/lib/types";

interface WatchlistProps {
  items: WatchlistItem[];
  quotes: Record<string, PriceUpdate>;
  history: Record<string, PricePoint[]>;
  selected: string | null;
  onSelect: (ticker: string) => void;
  onAdd: (ticker: string) => void;
  onRemove: (ticker: string) => void;
}

export function Watchlist({
  items,
  quotes,
  history,
  selected,
  onSelect,
  onAdd,
  onRemove,
}: WatchlistProps) {
  const [draft, setDraft] = useState("");

  const submit = (e: FormEvent) => {
    e.preventDefault();
    const t = draft.trim().toUpperCase();
    if (t) onAdd(t);
    setDraft("");
  };

  return (
    <Panel
      title="Watchlist"
      scroll
      action={
        <form onSubmit={submit} className="flex items-center gap-1">
          <input
            value={draft}
            onChange={(e) => setDraft(e.target.value)}
            placeholder="ADD TICKER"
            aria-label="Add ticker"
            data-testid="add-ticker-input"
            maxLength={6}
            className="w-24 rounded border border-line bg-surface-inset px-2 py-1 font-mono text-[11px] uppercase tracking-wider text-fg-primary placeholder:text-fg-faint focus:border-blue focus:outline-none"
          />
          <button
            type="submit"
            aria-label="Add to watchlist"
            data-testid="add-ticker-submit"
            className="rounded border border-line px-2 py-1 font-mono text-[11px] text-blue transition-colors hover:border-blue hover:bg-blue/10"
          >
            +
          </button>
        </form>
      }
    >
      <ul data-testid="watchlist" className="divide-y divide-line/60">
        {items.map((item) => (
          <WatchRow
            key={item.ticker}
            item={item}
            quote={quotes[item.ticker]}
            points={history[item.ticker] ?? []}
            active={selected === item.ticker}
            onSelect={() => onSelect(item.ticker)}
            onRemove={() => onRemove(item.ticker)}
          />
        ))}
        {items.length === 0 && (
          <li className="px-3 py-6 text-center font-mono text-xs text-fg-faint">
            No tickers watched.
          </li>
        )}
      </ul>
    </Panel>
  );
}

interface RowProps {
  item: WatchlistItem;
  quote: PriceUpdate | undefined;
  points: PricePoint[];
  active: boolean;
  onSelect: () => void;
  onRemove: () => void;
}

function WatchRow({ item, quote, points, active, onSelect, onRemove }: RowProps) {
  // Live quote (from SSE) wins over the REST snapshot it loaded with.
  const price = quote?.price ?? item.price;
  const changePct = quote?.change_pct ?? item.change_pct;
  const flash = useFlash(price);
  const up = changePct >= 0;

  return (
    <li
      onClick={onSelect}
      data-testid={`watchlist-row-${item.ticker}`}
      className={`group grid cursor-pointer grid-cols-[1fr_auto_auto] items-center gap-3 px-3 py-2 transition-colors ${
        active ? "bg-blue/10" : "hover:bg-surface-raised/60"
      } ${flash === "up" ? "animate-flash-up" : ""} ${flash === "down" ? "animate-flash-down" : ""}`}
    >
      <div className="flex min-w-0 items-center gap-2">
        {active && <span className="h-3 w-[2px] rounded-full bg-blue" />}
        <span className="truncate font-display text-sm font-semibold tracking-wide text-fg-primary">
          {item.ticker}
        </span>
      </div>

      <Sparkline points={points} />

      <div className="flex flex-col items-end gap-0.5">
        <span
          data-testid={`watchlist-price-${item.ticker}`}
          className="tabular text-sm text-fg-primary"
        >
          {formatPrice(price)}
        </span>
        <span
          className={`tabular text-[11px] ${up ? "text-up" : "text-down"}`}
        >
          {formatPct(changePct)}
        </span>
      </div>

      <button
        onClick={(e) => {
          e.stopPropagation();
          onRemove();
        }}
        aria-label={`Remove ${item.ticker}`}
        data-testid={`watchlist-remove-${item.ticker}`}
        className="col-start-3 row-start-1 -mr-1 ml-1 text-fg-faint opacity-0 transition-opacity hover:text-down focus:opacity-100 group-hover:opacity-100"
      >
        ×
      </button>
    </li>
  );
}
