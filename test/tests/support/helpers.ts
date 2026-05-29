import { expect, type Page, type APIRequestContext } from "@playwright/test";
import { testId } from "./selectors";

/** Parse a currency-ish string ("$10,000.00", "10000", "-$23.45") to a number. */
export function parseMoney(text: string | null): number {
  if (!text) return NaN;
  const cleaned = text.replace(/[^0-9.\-]/g, "");
  return Number.parseFloat(cleaned);
}

/** Read the cash balance shown in the header. */
export async function readCash(page: Page): Promise<number> {
  const text = await page.getByTestId(testId.cashBalance).textContent();
  return parseMoney(text);
}

/** Read the portfolio total value shown in the header. */
export async function readTotalValue(page: Page): Promise<number> {
  const text = await page.getByTestId(testId.totalValue).textContent();
  return parseMoney(text);
}

/**
 * Wait until the watchlist row for `ticker` shows a numeric price, i.e. the
 * SSE stream has delivered at least one update.
 */
export async function waitForPrice(page: Page, ticker: string): Promise<number> {
  const priceCell = page.getByTestId(testId.watchlistPrice(ticker));
  await expect
    .poll(async () => parseMoney(await priceCell.textContent()), {
      message: `price never streamed for ${ticker}`,
      timeout: 15_000,
    })
    .toBeGreaterThan(0);
  return parseMoney(await priceCell.textContent());
}

/** Current price for a ticker from the watchlist API (cache-backed). */
export async function apiPrice(
  request: APIRequestContext,
  ticker: string,
): Promise<number | null> {
  const res = await request.get("/api/watchlist");
  expect(res.ok()).toBeTruthy();
  const rows = (await res.json()) as Array<{
    ticker: string;
    price: number | null;
  }>;
  const row = rows.find((r) => r.ticker === ticker);
  return row ? row.price : null;
}

/** Execute a trade via the REST API (used to set up state deterministically). */
export async function apiTrade(
  request: APIRequestContext,
  ticker: string,
  side: "buy" | "sell",
  quantity: number,
): Promise<void> {
  const res = await request.post("/api/portfolio/trade", {
    data: { ticker, side, quantity },
  });
  expect(res.ok(), `trade ${side} ${quantity} ${ticker} failed: ${await res.text()}`).toBeTruthy();
}

/** Ensure a ticker is on the watchlist (idempotent), via the REST API. */
export async function apiEnsureWatch(
  request: APIRequestContext,
  ticker: string,
): Promise<void> {
  await request.post("/api/watchlist", { data: { ticker } });
}

/** Remove a ticker from the watchlist if present, via the REST API. */
export async function apiUnwatch(
  request: APIRequestContext,
  ticker: string,
): Promise<void> {
  await request.delete(`/api/watchlist/${ticker}`);
}
