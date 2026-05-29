import { test, expect } from "@playwright/test";
import { testId } from "./support/selectors";
import { waitForPrice } from "./support/helpers";

/**
 * SSE resilience: after the price stream is dropped, the EventSource (native
 * auto-retry) reconnects and the connection-status dot returns to "connected".
 * The drop is simulated by aborting the next /api/stream/prices request.
 */
test.describe("SSE reconnection", () => {
  test("recovers connection after the stream drops", async ({ page }) => {
    await page.goto("/");
    await waitForPrice(page, "AAPL");

    const dot = page.getByTestId(testId.connectionStatus);
    await expect
      .poll(async () => dot.getAttribute("data-state"), { timeout: 15_000 })
      .toBe("connected");

    // Abort the next stream connection to force a drop, then allow retries.
    let dropped = false;
    await page.route("**/api/stream/prices", async (route) => {
      if (!dropped) {
        dropped = true;
        await route.abort();
      } else {
        await route.continue();
      }
    });

    // Trigger the abort by closing the current stream from the server side is
    // not possible here; instead reload so the new EventSource hits the route.
    await page.reload();

    // It should report a non-connected state at least transiently, then recover.
    await expect
      .poll(async () => dot.getAttribute("data-state"), {
        message: "connection never recovered to connected",
        timeout: 20_000,
      })
      .toBe("connected");

    await page.unroute("**/api/stream/prices");

    // Prices resume streaming after recovery.
    const price = await waitForPrice(page, "AAPL");
    expect(price).toBeGreaterThan(0);
  });
});
