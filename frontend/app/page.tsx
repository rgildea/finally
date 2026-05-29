"use client";

import { useMemo, useState } from "react";
import { Header } from "@/components/Header";
import { Watchlist } from "@/components/Watchlist";
import { DetailChart } from "@/components/DetailChart";
import { PortfolioHeatmap } from "@/components/PortfolioHeatmap";
import { PnlChart } from "@/components/PnlChart";
import { PositionsTable } from "@/components/PositionsTable";
import { TradeBar } from "@/components/TradeBar";
import { ChatPanel } from "@/components/ChatPanel";
import { Toaster, pushToast } from "@/components/Toaster";
import { api, ApiError } from "@/lib/api";
import { usePriceStream } from "@/lib/usePriceStream";
import { useTerminalData } from "@/lib/useTerminalData";
import { formatPrice, formatQty } from "@/lib/format";
import type { TradeSide } from "@/lib/types";

export default function Terminal() {
  const { quotes, history, status } = usePriceStream();
  const { portfolio, watchlist, history: pnlHistory, setWatchlist, refresh } =
    useTerminalData();
  const [picked, setPicked] = useState<string | null>(null);

  // Derived selection: an explicit pick wins, otherwise default to the first
  // watched ticker. Computed during render to avoid a setState effect.
  const selected = picked ?? watchlist[0]?.ticker ?? null;

  // Live total value: cash + positions marked to the latest streamed prices.
  const liveTotalValue = useMemo(() => {
    const positionsValue = portfolio.positions.reduce((sum, p) => {
      const price = quotes[p.ticker]?.price ?? p.current_price;
      return sum + p.quantity * price;
    }, 0);
    return portfolio.cash_balance + positionsValue;
  }, [portfolio, quotes]);

  const handleTrade = async (
    ticker: string,
    quantity: number,
    side: TradeSide,
  ) => {
    try {
      const result = await api.trade(ticker, quantity, side);
      pushToast(
        "success",
        `${side.toUpperCase()} ${formatQty(result.quantity)} ${result.ticker} @ ${formatPrice(result.price)}`,
      );
      await refresh();
    } catch (err) {
      pushToast("error", err instanceof ApiError ? err.message : "Trade failed");
    }
  };

  const handleAdd = async (ticker: string) => {
    try {
      setWatchlist(await api.addWatchlist(ticker));
    } catch (err) {
      pushToast("error", err instanceof ApiError ? err.message : "Could not add ticker");
    }
  };

  const handleRemove = async (ticker: string) => {
    try {
      setWatchlist(await api.removeWatchlist(ticker));
      if (picked === ticker) setPicked(null);
    } catch (err) {
      pushToast("error", err instanceof ApiError ? err.message : "Could not remove ticker");
    }
  };

  return (
    <div className="flex h-dvh flex-col">
      <Header
        totalValue={liveTotalValue}
        cash={portfolio.cash_balance}
        totalPl={portfolio.total_pl}
        totalPlPct={portfolio.total_pl_pct}
        status={status}
      />

      <main className="grid min-h-0 flex-1 grid-cols-1 gap-3 p-3 lg:grid-cols-[320px_1fr_360px]">
        {/* Left rail: watchlist */}
        <div className="flex min-h-0 flex-col">
          <Watchlist
            items={watchlist}
            quotes={quotes}
            history={history}
            selected={selected}
            onSelect={setPicked}
            onAdd={handleAdd}
            onRemove={handleRemove}
          />
        </div>

        {/* Center: chart, trade bar, then heatmap + pnl, then positions */}
        <div className="grid min-h-0 grid-rows-[minmax(220px,1.4fr)_auto_minmax(150px,1fr)_minmax(150px,1fr)] gap-3">
          <DetailChart
            ticker={selected}
            points={selected ? (history[selected] ?? []) : []}
            quote={selected ? quotes[selected] : undefined}
          />
          <TradeBar ticker={selected} onTrade={handleTrade} />
          <div className="grid min-h-0 grid-cols-2 gap-3">
            <PortfolioHeatmap positions={portfolio.positions} onSelect={setPicked} />
            <PnlChart snapshots={pnlHistory} />
          </div>
          <PositionsTable
            positions={portfolio.positions}
            quotes={quotes}
            onSelect={setPicked}
          />
        </div>

        {/* Right rail: AI copilot */}
        <div className="flex min-h-0 flex-col">
          <ChatPanel onActionsApplied={refresh} />
        </div>
      </main>

      <Toaster />
    </div>
  );
}
