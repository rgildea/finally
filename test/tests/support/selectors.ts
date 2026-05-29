/**
 * Stable `data-testid` selectors the E2E suite depends on.
 *
 * This is a contract with the frontend-engineer: every id below must be
 * present on the corresponding element in the built app. Tests reference
 * these constants only — never raw test ids — so a rename is a one-line edit.
 */
export const testId = {
  // Header
  header: "header",
  connectionStatus: "connection-status", // data-state="connected|reconnecting|disconnected"
  cashBalance: "cash-balance",
  totalValue: "total-value",

  // Watchlist
  watchlist: "watchlist",
  watchlistRow: (ticker: string) => `watchlist-row-${ticker}`,
  watchlistPrice: (ticker: string) => `watchlist-price-${ticker}`,
  watchlistRemove: (ticker: string) => `watchlist-remove-${ticker}`,
  addTickerInput: "add-ticker-input",
  addTickerSubmit: "add-ticker-submit",

  // Positions
  positionsTable: "positions-table",
  positionRow: (ticker: string) => `position-row-${ticker}`,
  positionQuantity: (ticker: string) => `position-quantity-${ticker}`,

  // Portfolio visualizations
  heatmap: "portfolio-heatmap",
  heatmapCell: (ticker: string) => `heatmap-cell-${ticker}`,
  pnlChart: "pnl-chart",

  // Trade bar
  tradeTickerInput: "trade-ticker-input",
  tradeQuantityInput: "trade-quantity-input",
  tradeBuy: "trade-buy",
  tradeSell: "trade-sell",

  // Chat
  chatPanel: "chat-panel",
  chatInput: "chat-input",
  chatSend: "chat-send",
  chatMessage: "chat-message", // applied to each rendered message bubble
  chatMessageAssistant: "chat-message-assistant",
  chatActionConfirmation: "chat-action-confirmation",
} as const;

/** Default watchlist seeded by the backend (PLAN.md §7). */
export const DEFAULT_WATCHLIST = [
  "AAPL",
  "GOOGL",
  "MSFT",
  "AMZN",
  "TSLA",
  "NVDA",
  "META",
  "JPM",
  "V",
  "NFLX",
] as const;

/** Default starting cash balance (PLAN.md §2, §7). */
export const STARTING_CASH = 10000.0;
