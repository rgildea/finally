import { describe, expect, it, vi } from "vitest";
import { render, screen, fireEvent } from "@testing-library/react";
import { PositionsTable } from "./PositionsTable";
import type { Position } from "@/lib/types";

const position: Position = {
  ticker: "AAPL",
  quantity: 10,
  avg_cost: 190,
  current_price: 195,
  market_value: 1950,
  unrealized_pl: 50,
  unrealized_pl_pct: 2.63,
};

describe("PositionsTable", () => {
  it("shows an empty state with no positions", () => {
    render(<PositionsTable positions={[]} quotes={{}} onSelect={vi.fn()} />);
    expect(screen.getByText("No open positions")).toBeInTheDocument();
  });

  it("reprices P&L against the live quote", () => {
    render(
      <PositionsTable
        positions={[position]}
        quotes={{
          AAPL: { ticker: "AAPL", price: 200, prev_price: 195, change_pct: 2.5, timestamp: "t" },
        }}
        onSelect={vi.fn()}
      />,
    );
    // 10 * 200 = 2000 market value; cost 1900 -> +$100.00 P&L
    expect(screen.getByText("$2,000.00")).toBeInTheDocument();
    expect(screen.getByText("+$100.00")).toBeInTheDocument();
  });

  it("selects the ticker on row click", () => {
    const onSelect = vi.fn();
    render(<PositionsTable positions={[position]} quotes={{}} onSelect={onSelect} />);
    fireEvent.click(screen.getByText("AAPL"));
    expect(onSelect).toHaveBeenCalledWith("AAPL");
  });
});
