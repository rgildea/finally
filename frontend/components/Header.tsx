"use client";

import { useFlash } from "@/lib/useFlash";
import { formatPrice, formatPct, formatSignedPrice } from "@/lib/format";
import type { ConnectionStatus } from "@/lib/usePriceStream";

interface HeaderProps {
  totalValue: number;
  cash: number;
  totalPl: number;
  totalPlPct: number;
  status: ConnectionStatus;
}

const statusMeta: Record<
  ConnectionStatus,
  { color: string; label: string; state: string }
> = {
  connected: { color: "var(--color-up)", label: "Live", state: "connected" },
  connecting: {
    color: "var(--color-brand)",
    label: "Reconnecting",
    state: "reconnecting",
  },
  disconnected: {
    color: "var(--color-down)",
    label: "Offline",
    state: "disconnected",
  },
};

export function Header({ totalValue, cash, totalPl, totalPlPct, status }: HeaderProps) {
  const flash = useFlash(totalValue);
  const meta = statusMeta[status];
  const up = totalPl >= 0;

  return (
    <header
      data-testid="header"
      className="flex flex-wrap items-center justify-between gap-4 border-b border-line bg-surface/60 px-4 py-3 backdrop-blur-md"
    >
      <div className="flex items-center gap-3">
        <div className="grid h-9 w-9 place-items-center rounded-md border border-brand/40 bg-brand/10">
          <span className="font-display text-base font-extrabold text-brand">F</span>
        </div>
        <div className="leading-none">
          <h1 className="font-display text-base font-bold tracking-tight text-fg-primary">
            Fin<span className="text-brand">Ally</span>
          </h1>
          <p className="mt-1 font-mono text-[10px] uppercase tracking-[0.25em] text-fg-faint">
            Trading Workstation
          </p>
        </div>
      </div>

      <div className="flex items-center gap-6">
        <Stat label="Cash">
          <span data-testid="cash-balance" className="tabular text-sm text-fg-primary">
            {formatPrice(cash)}
          </span>
        </Stat>

        <Stat label="Day P&L">
          <span className={`tabular text-sm ${up ? "text-up" : "text-down"}`}>
            {formatSignedPrice(totalPl)}{" "}
            <span className="text-xs opacity-80">({formatPct(totalPlPct)})</span>
          </span>
        </Stat>

        <Stat label="Total Value">
          <span
            data-testid="total-value"
            className={`tabular rounded px-1 text-lg font-semibold text-fg-primary ${
              flash === "up" ? "animate-flash-up" : ""
            } ${flash === "down" ? "animate-flash-down" : ""}`}
          >
            {formatPrice(totalValue)}
          </span>
        </Stat>

        <div
          data-testid="connection-status"
          data-state={meta.state}
          className="flex items-center gap-2 rounded-full border border-line bg-surface-inset px-3 py-1.5"
          title={`Stream: ${meta.label}`}
        >
          <span
            className="h-2 w-2 rounded-full animate-pulse-dot"
            style={{ background: meta.color, boxShadow: `0 0 8px ${meta.color}` }}
          />
          <span className="font-mono text-[10px] uppercase tracking-wider text-fg-muted">
            {meta.label}
          </span>
        </div>
      </div>
    </header>
  );
}

function Stat({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <div className="flex flex-col items-end gap-0.5">
      <span className="font-mono text-[10px] uppercase tracking-wider text-fg-faint">
        {label}
      </span>
      {children}
    </div>
  );
}
