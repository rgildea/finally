import { test, expect } from "@playwright/test";
import { testId } from "./support/selectors";
import { apiUnwatch, apiEnsureWatch } from "./support/helpers";

/**
 * Add and remove a ticker via the UI. PYPL is not in the default watchlist,
 * so it is a safe target. Each test restores the prior state via the API so
 * the suite is order-independent on a persistent volume.
 */
const TARGET = "PYPL";

test.describe("watchlist add / remove", () => {
  test.afterEach(async ({ request }) => {
    await apiUnwatch(request, TARGET);
  });

  test("adds a ticker through the UI", async ({ page, request }) => {
    await apiUnwatch(request, TARGET);
    await page.goto("/");

    await page.getByTestId(testId.addTickerInput).fill(TARGET);
    await page.getByTestId(testId.addTickerSubmit).click();

    await expect(page.getByTestId(testId.watchlistRow(TARGET))).toBeVisible();
  });

  test("removes a ticker through the UI", async ({ page, request }) => {
    await apiEnsureWatch(request, TARGET);
    await page.goto("/");

    const row = page.getByTestId(testId.watchlistRow(TARGET));
    await expect(row).toBeVisible();

    await page.getByTestId(testId.watchlistRemove(TARGET)).click();
    await expect(row).toHaveCount(0);
  });
});
