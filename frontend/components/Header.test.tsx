import { describe, expect, it } from "vitest";
import { render, screen } from "@testing-library/react";
import { Header } from "./Header";

const base = {
  totalValue: 10523.45,
  cash: 2534,
  totalPl: 23.45,
  totalPlPct: 0.23,
} as const;

describe("Header", () => {
  it("exposes the E2E test ids with formatted values", () => {
    render(<Header {...base} status="connected" />);
    expect(screen.getByTestId("cash-balance")).toHaveTextContent("$2,534.00");
    expect(screen.getByTestId("total-value")).toHaveTextContent("$10,523.45");
  });

  it("reflects the stream status via data-state", () => {
    const { rerender } = render(<Header {...base} status="connected" />);
    expect(screen.getByTestId("connection-status")).toHaveAttribute(
      "data-state",
      "connected",
    );

    rerender(<Header {...base} status="connecting" />);
    expect(screen.getByTestId("connection-status")).toHaveAttribute(
      "data-state",
      "reconnecting",
    );

    rerender(<Header {...base} status="disconnected" />);
    expect(screen.getByTestId("connection-status")).toHaveAttribute(
      "data-state",
      "disconnected",
    );
  });
});
