import { test, expect } from "@playwright/test";
import { testId } from "./support/selectors";
import { apiTrade, apiPrice, waitForPrice } from "./support/helpers";

/**
 * Portfolio visualizations: with at least one position the heatmap renders a
 * cell for it, and the P&L chart accumulates data points (snapshots recorded
 * on the backend interval). Establishes a position via the API first.
 */
const TICKER = "NVDA";

test.describe("portfolio visualizations", () => {
  test.beforeEach(async ({ page, request }) => {
    await page.goto("/");
    await waitForPrice(page, TICKER);
    if ((await apiPrice(request, TICKER)) !== null) {
      await apiTrade(request, TICKER, "buy", 1);
    }
  });

  test.afterEach(async ({ request }) => {
    const res = await request.get("/api/portfolio");
    const body = (await res.json()) as {
      positions: Array<{ ticker: string; quantity: number }>;
    };
    const pos = body.positions.find((p) => p.ticker === TICKER);
    if (pos && pos.quantity > 0) {
      await apiTrade(request, TICKER, "sell", pos.quantity);
    }
  });

  test("heatmap renders a colored cell for a held position", async ({ page }) => {
    await page.reload();
    const cell = page.getByTestId(testId.heatmapCell(TICKER));
    await expect(cell).toBeVisible();
    // The cell is an SVG <g> carrying data-pl and an inline P&L fill color
    // (mirrored on its <rect>); assert a real, non-transparent fill.
    await expect(cell).toHaveAttribute("data-pl", /up|down/);
    const fill = await cell.evaluate((el) => getComputedStyle(el).fill);
    expect(fill).toBeTruthy();
    expect(fill).not.toBe("rgba(0, 0, 0, 0)");
  });

  test("P&L chart draws the value series once enough snapshots exist", async ({
    page,
    request,
  }) => {
    // Waiting on two ~15s snapshot ticks can exceed the default test timeout.
    test.setTimeout(70_000);
    // The chart needs >= 2 snapshots to draw a line (one point shows a
    // placeholder). Snapshots record on a ~15s backend interval.
    await expect
      .poll(
        async () => {
          const res = await request.get("/api/portfolio/history");
          const body = (await res.json()) as { snapshots: unknown[] };
          return body.snapshots.length;
        },
        { message: "fewer than 2 portfolio snapshots recorded", timeout: 45_000 },
      )
      .toBeGreaterThanOrEqual(2);

    await page.reload();
    await expect(page.getByTestId(testId.pnlChart)).toBeVisible();
    // Recharts AreaChart renders the series as SVG <path> elements.
    const chart = page.getByTestId(testId.pnlChart);
    await expect
      .poll(async () => chart.locator("svg path").count(), { timeout: 10_000 })
      .toBeGreaterThan(0);
  });
});
