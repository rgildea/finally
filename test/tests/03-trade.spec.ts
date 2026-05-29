import { test, expect } from "@playwright/test";
import { testId } from "./support/selectors";
import {
  readCash,
  waitForPrice,
  apiTrade,
  apiPrice,
} from "./support/helpers";

/**
 * Buy then sell through the trade bar. Uses MSFT and a small quantity so the
 * cost stays well within the cash balance. Asserts cash decreases on buy and
 * the position appears, then cash recovers on sell and the position clears.
 */
const TICKER = "MSFT";
const QTY = 1;

test.describe("trade buy then sell", () => {
  test.afterEach(async ({ request }) => {
    // Flatten any residual position so reruns start clean.
    const price = await apiPrice(request, TICKER);
    if (price !== null) {
      const res = await request.get("/api/portfolio");
      const body = (await res.json()) as {
        positions: Array<{ ticker: string; quantity: number }>;
      };
      const pos = body.positions.find((p) => p.ticker === TICKER);
      if (pos && pos.quantity > 0) {
        await apiTrade(request, TICKER, "sell", pos.quantity);
      }
    }
  });

  test("buying decreases cash and creates a position", async ({ page }) => {
    await page.goto("/");
    await waitForPrice(page, TICKER);
    const cashBefore = await readCash(page);

    await page.getByTestId(testId.tradeTickerInput).fill(TICKER);
    await page.getByTestId(testId.tradeQuantityInput).fill(String(QTY));
    await page.getByTestId(testId.tradeBuy).click();

    await expect(page.getByTestId(testId.positionRow(TICKER))).toBeVisible();
    await expect
      .poll(async () => readCash(page))
      .toBeLessThan(cashBefore);
  });

  test("selling restores cash and clears the position", async ({ page, request }) => {
    // Establish a known position via API, then sell through the UI.
    await page.goto("/");
    await waitForPrice(page, TICKER);
    await apiTrade(request, TICKER, "buy", QTY);
    await page.reload();
    await expect(page.getByTestId(testId.positionRow(TICKER))).toBeVisible();

    const cashBeforeSell = await readCash(page);

    await page.getByTestId(testId.tradeTickerInput).fill(TICKER);
    await page.getByTestId(testId.tradeQuantityInput).fill(String(QTY));
    await page.getByTestId(testId.tradeSell).click();

    await expect(page.getByTestId(testId.positionRow(TICKER))).toHaveCount(0);
    await expect
      .poll(async () => readCash(page))
      .toBeGreaterThan(cashBeforeSell);
  });
});
