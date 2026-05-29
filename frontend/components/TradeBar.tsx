"use client";

import { useState, type FormEvent } from "react";
import type { TradeSide } from "@/lib/types";

interface TradeBarProps {
  /** Pre-fills the ticker field, e.g. when a watchlist row is selected. */
  ticker: string | null;
  onTrade: (ticker: string, quantity: number, side: TradeSide) => Promise<void>;
}

/** Market-order entry: ticker, quantity, buy/sell. Instant fill, no dialog. */
export function TradeBar({ ticker, onTrade }: TradeBarProps) {
  const [symbol, setSymbol] = useState("");
  const [qty, setQty] = useState("");
  const [busy, setBusy] = useState(false);

  // Show the selected ticker as a placeholder; an explicit entry overrides it.
  const effectiveSymbol = (symbol || ticker || "").toUpperCase();

  const submit = async (side: TradeSide, e: FormEvent) => {
    e.preventDefault();
    const t = effectiveSymbol.trim();
    const q = Number(qty);
    if (!t || !Number.isFinite(q) || q <= 0 || busy) return;
    setBusy(true);
    try {
      await onTrade(t, q, side);
      setQty("");
    } finally {
      setBusy(false);
    }
  };

  return (
    <form className="flex items-stretch gap-2 rounded-lg border border-line bg-surface/70 p-2 backdrop-blur-sm">
      <input
        value={symbol}
        onChange={(e) => setSymbol(e.target.value.toUpperCase())}
        placeholder={ticker ?? "TICKER"}
        aria-label="Trade ticker"
        data-testid="trade-ticker-input"
        maxLength={6}
        className="w-28 rounded border border-line bg-surface-inset px-3 font-mono text-sm uppercase tracking-wider text-fg-primary placeholder:text-fg-faint focus:border-blue focus:outline-none"
      />
      <input
        value={qty}
        onChange={(e) => setQty(e.target.value.replace(/[^0-9.]/g, ""))}
        placeholder="QTY"
        aria-label="Trade quantity"
        data-testid="trade-quantity-input"
        inputMode="decimal"
        className="tabular w-24 rounded border border-line bg-surface-inset px-3 text-sm text-fg-primary placeholder:font-mono placeholder:text-fg-faint focus:border-blue focus:outline-none"
      />
      <button
        type="button"
        onClick={(e) => submit("buy", e)}
        disabled={busy}
        data-testid="trade-buy"
        className="flex-1 rounded border border-up/40 bg-up/15 px-4 py-2 font-display text-sm font-semibold uppercase tracking-wider text-up transition-colors hover:bg-up/25 disabled:opacity-50"
      >
        Buy
      </button>
      <button
        type="button"
        onClick={(e) => submit("sell", e)}
        disabled={busy}
        data-testid="trade-sell"
        className="flex-1 rounded border border-down/40 bg-down/15 px-4 py-2 font-display text-sm font-semibold uppercase tracking-wider text-down transition-colors hover:bg-down/25 disabled:opacity-50"
      >
        Sell
      </button>
    </form>
  );
}
