import { describe, expect, it, vi } from "vitest";
import { render, screen, fireEvent } from "@testing-library/react";
import { TradeBar } from "./TradeBar";

describe("TradeBar", () => {
  it("submits a buy with the selected ticker and entered quantity", async () => {
    const onTrade = vi.fn().mockResolvedValue(undefined);
    render(<TradeBar ticker="NVDA" onTrade={onTrade} />);

    fireEvent.change(screen.getByLabelText("Trade quantity"), {
      target: { value: "5" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Buy" }));

    expect(onTrade).toHaveBeenCalledWith("NVDA", 5, "buy");
  });

  it("uses an explicit ticker over the selected one and sells", () => {
    const onTrade = vi.fn().mockResolvedValue(undefined);
    render(<TradeBar ticker="NVDA" onTrade={onTrade} />);

    fireEvent.change(screen.getByLabelText("Trade ticker"), {
      target: { value: "amd" },
    });
    fireEvent.change(screen.getByLabelText("Trade quantity"), {
      target: { value: "3" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Sell" }));

    expect(onTrade).toHaveBeenCalledWith("AMD", 3, "sell");
  });

  it("ignores invalid (zero/empty) quantities", () => {
    const onTrade = vi.fn();
    render(<TradeBar ticker="NVDA" onTrade={onTrade} />);
    fireEvent.click(screen.getByRole("button", { name: "Buy" }));
    expect(onTrade).not.toHaveBeenCalled();
  });
});
