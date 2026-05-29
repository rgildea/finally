import { test, expect } from "@playwright/test";
import { testId, DEFAULT_WATCHLIST, STARTING_CASH } from "./support/selectors";
import { readCash, waitForPrice } from "./support/helpers";

/**
 * Fresh start: the default watchlist renders, $10k cash is shown, and prices
 * are streaming. Cash is only asserted to equal STARTING_CASH on a pristine
 * volume; on a reused volume it is simply asserted to be a positive number.
 */
test.describe("fresh start", () => {
  test("loads the trading terminal", async ({ page }) => {
    await page.goto("/");
    await expect(page.getByTestId(testId.header)).toBeVisible();
    await expect(page.getByTestId(testId.watchlist)).toBeVisible();
    await expect(page.getByTestId(testId.chatPanel)).toBeVisible();
  });

  test("default watchlist shows all ten tickers", async ({ page }) => {
    await page.goto("/");
    for (const ticker of DEFAULT_WATCHLIST) {
      await expect(page.getByTestId(testId.watchlistRow(ticker))).toBeVisible();
    }
  });

  test("cash balance is present and non-negative", async ({ page }) => {
    await page.goto("/");
    await expect(page.getByTestId(testId.cashBalance)).toBeVisible();
    const cash = await readCash(page);
    expect(Number.isNaN(cash)).toBeFalsy();
    expect(cash).toBeGreaterThanOrEqual(0);
    // On a clean volume the seed is exactly the starting cash.
    if (process.env.FRESH_VOLUME === "true") {
      expect(cash).toBeCloseTo(STARTING_CASH, 2);
    }
  });

  test("prices stream in for the watchlist", async ({ page }) => {
    await page.goto("/");
    const price = await waitForPrice(page, "AAPL");
    expect(price).toBeGreaterThan(0);
  });

  test("connection status reports connected", async ({ page }) => {
    await page.goto("/");
    const dot = page.getByTestId(testId.connectionStatus);
    await expect(dot).toBeVisible();
    await expect
      .poll(async () => dot.getAttribute("data-state"), { timeout: 15_000 })
      .toBe("connected");
  });
});
