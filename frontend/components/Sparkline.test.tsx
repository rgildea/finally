import { describe, expect, it } from "vitest";
import { render } from "@testing-library/react";
import { Sparkline } from "./Sparkline";

describe("Sparkline", () => {
  it("renders a placeholder line with fewer than two points", () => {
    const { container } = render(<Sparkline points={[{ t: 1, price: 10 }]} />);
    expect(container.querySelector("line")).toBeInTheDocument();
    expect(container.querySelector("path")).toBeNull();
  });

  it("draws a path for a rising series", () => {
    const { container } = render(
      <Sparkline
        points={[
          { t: 1, price: 10 },
          { t: 2, price: 11 },
          { t: 3, price: 12 },
        ]}
      />,
    );
    const paths = container.querySelectorAll("path");
    // One area fill + one stroke line.
    expect(paths.length).toBe(2);
  });
});
