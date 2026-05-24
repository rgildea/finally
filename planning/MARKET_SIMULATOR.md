# Market Simulator

The market simulator generates realistic-looking stock prices using geometric Brownian motion (GBM). It is the default price source when `MASSIVE_API_KEY` is not set. It runs entirely in-process as an asyncio background task with no external dependencies.

---

## Geometric Brownian Motion

GBM is the standard model for stock price dynamics in quantitative finance (Black-Scholes). It produces prices that drift upward on average while exhibiting random, log-normally distributed returns — consistent with empirical equity behavior.

**Continuous-time SDE:**

```
dS = μ·S·dt + σ·S·dW
```

**Discrete-time approximation (Euler-Maruyama):**

```
S(t+dt) = S(t) · exp((μ - σ²/2)·dt + σ·√dt·Z)
```

Where:
- `S(t)` — current price
- `μ` (mu) — annual drift (expected return), e.g. `0.10` = 10%/year
- `σ` (sigma) — annual volatility, e.g. `0.30` = 30%/year
- `dt` — time step in years (500ms ≈ `500 / (252 * 6.5 * 3600) ≈ 8.5e-8` years)
- `Z` — standard normal random variable `~ N(0, 1)`

The `(μ - σ²/2)` adjustment (Ito correction) ensures the expected price is `S·exp(μ·dt)`, not biased by the variance term.

For a 500ms step with typical equity parameters, price moves are on the order of 0.01–0.05% per tick — realistic intraday noise.

---

## Ticker Configuration

Default seed prices and per-ticker GBM parameters. Drift and volatility are expressed as annual figures; the simulator scales to the tick interval automatically.

| Ticker | Seed Price | Annual Drift (μ) | Annual Volatility (σ) | Sector |
|--------|-----------|-------------------|-----------------------|--------|
| AAPL | 190.00 | 0.12 | 0.28 | Tech |
| MSFT | 420.00 | 0.13 | 0.26 | Tech |
| NVDA | 875.00 | 0.20 | 0.55 | Tech |
| META | 510.00 | 0.15 | 0.38 | Tech |
| GOOGL | 175.00 | 0.11 | 0.27 | Tech |
| AMZN | 185.00 | 0.14 | 0.32 | Tech |
| TSLA | 250.00 | 0.10 | 0.65 | EV/Tech |
| NFLX | 640.00 | 0.12 | 0.40 | Media |
| JPM | 195.00 | 0.09 | 0.22 | Finance |
| V | 275.00 | 0.10 | 0.20 | Finance |

Higher volatility tickers (TSLA, NVDA) will show larger price swings. Finance stocks (JPM, V) are calmer.

---

## Correlation Structure

Real markets exhibit correlated moves — tech stocks tend to rise and fall together. The simulator implements simplified sector correlation:

- Draw one **sector shock** `Z_sector ~ N(0, 1)` per sector per tick
- Draw one **idiosyncratic shock** `Z_idio ~ N(0, 1)` per ticker per tick
- Combine: `Z_ticker = ρ·Z_sector + √(1-ρ²)·Z_idio`

Where `ρ` (rho) is the sector correlation coefficient.

| Sector | Tickers | ρ (correlation) |
|--------|---------|-----------------|
| Tech | AAPL, MSFT, NVDA, META, GOOGL, AMZN | 0.60 |
| EV/Tech | TSLA | 0.40 (partial tech correlation) |
| Media | NFLX | 0.30 (weaker tech correlation) |
| Finance | JPM, V | 0.55 |

This means during a broad market move, tech stocks will largely move together while finance stocks move on their own sector shock.

---

## Random Events

Occasional large price moves add drama and simulate news events (earnings surprises, analyst upgrades, macro shocks).

**Parameters:**
- **Probability per tick:** `0.001` (roughly one event every ~8 minutes at 500ms ticks)
- **Magnitude:** uniform random in `[0.02, 0.05]` (2–5% move)
- **Direction:** 50% up, 50% down
- **Target:** one randomly selected ticker per event

**Implementation:** On each tick, draw `U ~ Uniform(0,1)`. If `U < 0.001`, select a random ticker and multiply its price by `(1 ± magnitude)` before the GBM step. The GBM then continues from the new price level naturally.

---

## Update Loop

The simulator runs as a single asyncio task started at FastAPI startup:

```
Every 500ms:
  1. For each sector, draw sector shock Z_sector
  2. For each ticker:
     a. Draw idiosyncratic shock Z_idio
     b. Combine: Z = ρ·Z_sector + √(1-ρ²)·Z_idio
     c. Check for random event; apply if triggered
     d. Apply GBM step: S_new = S · exp((μ - σ²/2)·dt + σ·√dt·Z)
  3. Write all updated prices to PriceCache
  4. Sleep 500ms
```

The task is cancellation-safe — it checks for `asyncio.CancelledError` and shuts down cleanly.

---

## Code Structure

### `SimulatorConfig`

Holds all configuration as a dataclass. Instantiated once at module level.

```python
from dataclasses import dataclass, field

@dataclass
class TickerConfig:
    seed_price: float
    mu: float        # Annual drift
    sigma: float     # Annual volatility
    sector: str

@dataclass
class SimulatorConfig:
    tickers: dict[str, TickerConfig] = field(default_factory=_default_tickers)
    sector_correlations: dict[str, float] = field(default_factory=_default_correlations)
    tick_interval_seconds: float = 0.5
    event_probability: float = 0.001
    event_magnitude_min: float = 0.02
    event_magnitude_max: float = 0.05

def _default_tickers() -> dict[str, TickerConfig]:
    return {
        "AAPL": TickerConfig(190.00, 0.12, 0.28, "Tech"),
        "MSFT": TickerConfig(420.00, 0.13, 0.26, "Tech"),
        "NVDA": TickerConfig(875.00, 0.20, 0.55, "Tech"),
        "META": TickerConfig(510.00, 0.15, 0.38, "Tech"),
        "GOOGL": TickerConfig(175.00, 0.11, 0.27, "Tech"),
        "AMZN": TickerConfig(185.00, 0.14, 0.32, "Tech"),
        "TSLA": TickerConfig(250.00, 0.10, 0.65, "EV/Tech"),
        "NFLX": TickerConfig(640.00, 0.12, 0.40, "Media"),
        "JPM":  TickerConfig(195.00, 0.09, 0.22, "Finance"),
        "V":    TickerConfig(275.00, 0.10, 0.20, "Finance"),
    }

def _default_correlations() -> dict[str, float]:
    return {"Tech": 0.60, "EV/Tech": 0.40, "Media": 0.30, "Finance": 0.55}
```

### `MarketSimulator`

Implements the `MarketDataSource` abstract interface (see `MARKET_INTERFACE.md`).

```python
import asyncio
import math
import random
import logging
from datetime import datetime, timezone

from .interface import MarketDataSource, PriceUpdate

logger = logging.getLogger(__name__)


class MarketSimulator(MarketDataSource):
    """
    Simulates stock prices using geometric Brownian motion with sector correlations
    and occasional random events. Runs as an asyncio background task.
    """

    def __init__(self, config: SimulatorConfig | None = None) -> None:
        self._config = config or SimulatorConfig()
        # Current prices, initialized from seed values
        self._prices: dict[str, float] = {
            ticker: cfg.seed_price
            for ticker, cfg in self._config.tickers.items()
        }
        self._task: asyncio.Task | None = None

    async def start(self) -> None:
        """Start the background price simulation loop."""
        self._task = asyncio.create_task(self._run_loop(), name="market-simulator")
        logger.info("Market simulator started")

    async def stop(self) -> None:
        """Stop the background simulation loop."""
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
        logger.info("Market simulator stopped")

    async def get_prices(self, tickers: list[str]) -> dict[str, PriceUpdate]:
        """
        Return the latest simulated prices for the requested tickers.
        Called by the price cache polling loop.
        """
        now = datetime.now(timezone.utc).isoformat()
        result = {}
        for ticker in tickers:
            if ticker in self._prices:
                price = self._prices[ticker]
                result[ticker] = PriceUpdate(
                    ticker=ticker,
                    price=price,
                    prev_price=price,  # Simulator updates in-place; cache tracks prev
                    timestamp=now,
                    change_pct=0.0,    # Cache layer computes change from previous cached value
                )
        return result

    async def _run_loop(self) -> None:
        """Main simulation loop. Runs every tick_interval_seconds."""
        interval = self._config.tick_interval_seconds
        # Time step in years (trading year: 252 days, 6.5 hours/day)
        dt = interval / (252 * 6.5 * 3600)

        while True:
            try:
                self._tick(dt)
                await asyncio.sleep(interval)
            except asyncio.CancelledError:
                raise
            except Exception:
                logger.exception("Error in simulator tick")
                await asyncio.sleep(interval)

    def _tick(self, dt: float) -> None:
        """Advance all prices by one time step."""
        sector_shocks = self._draw_sector_shocks()
        self._maybe_trigger_event()

        config = self._config
        for ticker, ticker_cfg in config.tickers.items():
            rho = config.sector_correlations.get(ticker_cfg.sector, 0.0)
            z_sector = sector_shocks.get(ticker_cfg.sector, 0.0)
            z_idio = random.gauss(0, 1)
            z = rho * z_sector + math.sqrt(1 - rho ** 2) * z_idio

            mu = ticker_cfg.mu
            sigma = ticker_cfg.sigma
            drift = (mu - 0.5 * sigma ** 2) * dt
            diffusion = sigma * math.sqrt(dt) * z

            self._prices[ticker] *= math.exp(drift + diffusion)

    def _draw_sector_shocks(self) -> dict[str, float]:
        """Draw one N(0,1) shock per sector."""
        sectors = {cfg.sector for cfg in self._config.tickers.values()}
        return {sector: random.gauss(0, 1) for sector in sectors}

    def _maybe_trigger_event(self) -> None:
        """Randomly trigger a large price move on one ticker."""
        if random.random() < self._config.event_probability:
            ticker = random.choice(list(self._prices.keys()))
            magnitude = random.uniform(
                self._config.event_magnitude_min,
                self._config.event_magnitude_max,
            )
            direction = 1 if random.random() > 0.5 else -1
            self._prices[ticker] *= 1 + direction * magnitude
            logger.debug("Event: %s moved %.1f%%", ticker, direction * magnitude * 100)
```

---

## Integration with Price Cache

The simulator does not push prices directly to clients. Instead:

1. The simulation loop (`_run_loop`) updates `self._prices` in memory every 500ms.
2. A separate `get_prices()` call from the polling loop reads the current prices and writes them to `PriceCache`.
3. The SSE endpoint reads from `PriceCache` and streams to clients.

This design matches the Massive API client's interface exactly — both implement `get_prices()` and the polling loop calls them the same way.

See `MARKET_INTERFACE.md` for the full architecture.

---

## Dynamic Ticker Support

The simulator supports any ticker in its config dict. If the user adds a ticker not in the default config (e.g., via the watchlist API), the simulator falls back to generic parameters:

```python
FALLBACK_CONFIG = TickerConfig(seed_price=100.0, mu=0.10, sigma=0.30, sector="Tech")
```

The simulator uses the fallback config for unknown tickers rather than raising an error.
