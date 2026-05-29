import { describe, expect, it, vi } from "vitest";
import { render, screen, fireEvent } from "@testing-library/react";
import { Watchlist } from "./Watchlist";
import type { WatchlistItem } from "@/lib/types";

const items: WatchlistItem[] = [
  { ticker: "AAPL", price: 195, prev_price: 194, change_pct: 0.51, timestamp: "t" },
  { ticker: "TSLA", price: 240, prev_price: 245, change_pct: -2.04, timestamp: "t" },
];

function setup(overrides = {}) {
  const props = {
    items,
    quotes: {},
    history: {},
    selected: "AAPL",
    onSelect: vi.fn(),
    onAdd: vi.fn(),
    onRemove: vi.fn(),
    ...overrides,
  };
  render(<Watchlist {...props} />);
  return props;
}

describe("Watchlist", () => {
  it("renders rows with price and change", () => {
    setup();
    expect(screen.getByText("AAPL")).toBeInTheDocument();
    expect(screen.getByText("$195.00")).toBeInTheDocument();
    expect(screen.getByText("-2.04%")).toBeInTheDocument();
  });

  it("selects a ticker on row click", () => {
    const props = setup();
    fireEvent.click(screen.getByText("TSLA"));
    expect(props.onSelect).toHaveBeenCalledWith("TSLA");
  });

  it("adds an uppercased ticker via the form", () => {
    const props = setup();
    fireEvent.change(screen.getByLabelText("Add ticker"), {
      target: { value: "pypl" },
    });
    fireEvent.click(screen.getByLabelText("Add to watchlist"));
    expect(props.onAdd).toHaveBeenCalledWith("PYPL");
  });

  it("removes a ticker without selecting it", () => {
    const props = setup();
    fireEvent.click(screen.getByLabelText("Remove TSLA"));
    expect(props.onRemove).toHaveBeenCalledWith("TSLA");
    expect(props.onSelect).not.toHaveBeenCalled();
  });

  it("prefers live quote price over the snapshot", () => {
    setup({
      quotes: {
        AAPL: { ticker: "AAPL", price: 200, prev_price: 195, change_pct: 2.5, timestamp: "t" },
      },
    });
    expect(screen.getByText("$200.00")).toBeInTheDocument();
  });
});
