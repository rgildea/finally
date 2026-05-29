import { test, expect } from "@playwright/test";
import { testId } from "./support/selectors";
import { waitForPrice, apiTrade, apiPrice } from "./support/helpers";

/**
 * AI chat with the mock LLM (LLM_MOCK=true). Per CONTRACT.md §5 the mock
 * streams a deterministic reply, and a message containing "buy" triggers a
 * small AAPL buy that must surface as an inline action confirmation.
 */
test.describe("AI chat (mocked)", () => {
  test.afterEach(async ({ request }) => {
    // The mock buys AAPL; flatten it so reruns are clean.
    if ((await apiPrice(request, "AAPL")) !== null) {
      const res = await request.get("/api/portfolio");
      const body = (await res.json()) as {
        positions: Array<{ ticker: string; quantity: number }>;
      };
      const pos = body.positions.find((p) => p.ticker === "AAPL");
      if (pos && pos.quantity > 0) {
        await apiTrade(request, "AAPL", "sell", pos.quantity);
      }
    }
  });

  test("streams an assistant response", async ({ page }) => {
    await page.goto("/");
    await page.getByTestId(testId.chatInput).fill("How is my portfolio doing?");
    await page.getByTestId(testId.chatSend).click();

    const reply = page.getByTestId(testId.chatMessageAssistant).last();
    await expect(reply).toBeVisible();
    await expect
      .poll(async () => ((await reply.textContent()) ?? "").trim().length, {
        message: "assistant reply never streamed any text",
        timeout: 15_000,
      })
      .toBeGreaterThan(0);
  });

  test("a buy request shows an inline trade confirmation", async ({ page }) => {
    await page.goto("/");
    await waitForPrice(page, "AAPL");

    await page.getByTestId(testId.chatInput).fill("Please buy some AAPL for me");
    await page.getByTestId(testId.chatSend).click();

    const confirmation = page.getByTestId(testId.chatActionConfirmation).last();
    await expect(confirmation).toBeVisible({ timeout: 15_000 });
    await expect(confirmation).toContainText("AAPL");

    // The auto-executed trade must be reflected in the positions table.
    await expect(page.getByTestId(testId.positionRow("AAPL"))).toBeVisible();
  });
});
