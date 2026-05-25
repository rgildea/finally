import asyncio
import logging
import math
import random
from dataclasses import dataclass, field
from datetime import datetime, timezone

from .interface import MarketDataSource, PriceUpdate

logger = logging.getLogger(__name__)


@dataclass
class TickerConfig:
    seed_price: float
    mu: float    # Annual drift (expected return), e.g. 0.12 = 12%/year
    sigma: float  # Annual volatility, e.g. 0.28 = 28%/year
    sector: str


# Default ticker universe — seed prices and GBM parameters for the 10 default watchlist tickers
_DEFAULT_TICKERS: dict[str, TickerConfig] = {
    "AAPL":  TickerConfig(seed_price=190.00, mu=0.12, sigma=0.28, sector="Tech"),
    "MSFT":  TickerConfig(seed_price=420.00, mu=0.13, sigma=0.26, sector="Tech"),
    "NVDA":  TickerConfig(seed_price=875.00, mu=0.20, sigma=0.55, sector="Tech"),
    "META":  TickerConfig(seed_price=510.00, mu=0.15, sigma=0.38, sector="Tech"),
    "GOOGL": TickerConfig(seed_price=175.00, mu=0.11, sigma=0.27, sector="Tech"),
    "AMZN":  TickerConfig(seed_price=185.00, mu=0.14, sigma=0.32, sector="Tech"),
    "TSLA":  TickerConfig(seed_price=250.00, mu=0.10, sigma=0.65, sector="EV/Tech"),
    "NFLX":  TickerConfig(seed_price=640.00, mu=0.12, sigma=0.40, sector="Media"),
    "JPM":   TickerConfig(seed_price=195.00, mu=0.09, sigma=0.22, sector="Finance"),
    "V":     TickerConfig(seed_price=275.00, mu=0.10, sigma=0.20, sector="Finance"),
}

# Correlation coefficient ρ per sector.
# Z_ticker = ρ·Z_sector + √(1-ρ²)·Z_idiosyncratic
_DEFAULT_CORRELATIONS: dict[str, float] = {
    "Tech":    0.60,
    "EV/Tech": 0.40,  # TSLA has partial tech correlation
    "Media":   0.30,  # NFLX has weaker correlation with the broader market
    "Finance": 0.55,
}

# Fallback for any ticker the user adds that is not in _DEFAULT_TICKERS
_FALLBACK_CONFIG = TickerConfig(seed_price=100.0, mu=0.10, sigma=0.30, sector="Tech")


@dataclass
class SimulatorConfig:
    tickers: dict[str, TickerConfig] = field(default_factory=lambda: dict(_DEFAULT_TICKERS))
    sector_correlations: dict[str, float] = field(default_factory=lambda: dict(_DEFAULT_CORRELATIONS))
    tick_interval_seconds: float = 0.5
    event_probability: float = 0.001   # Per tick, per ticker
    event_magnitude_min: float = 0.02  # 2% minimum shock
    event_magnitude_max: float = 0.05  # 5% maximum shock


class MarketSimulator(MarketDataSource):
    """
    Simulates stock prices using GBM with sector correlations and random events.

    The simulation loop runs as an asyncio background task (started by start()).
    get_prices() reads the current in-memory prices synchronously — no I/O.
    """

    def __init__(self, config: SimulatorConfig | None = None) -> None:
        self._config = config or SimulatorConfig()
        # Live prices — updated by _tick(), read by get_prices()
        self._prices: dict[str, float] = {
            ticker: cfg.seed_price
            for ticker, cfg in self._config.tickers.items()
        }
        self._task: asyncio.Task | None = None

    async def start(self) -> None:
        if self._task is not None and not self._task.done():
            return
        self._task = asyncio.create_task(
            self._run_loop(), name="market-simulator"
        )
        logger.info("Market simulator started")

    async def stop(self) -> None:
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
            self._task = None
        logger.info("Market simulator stopped")

    async def get_prices(self, tickers: list[str]) -> dict[str, PriceUpdate]:
        """
        Return current simulated prices for the requested tickers.

        Tickers not in the config use the fallback config and start at $100.
        prev_price is set equal to price here; the polling loop's _merge_with_prev()
        replaces it with the actual previously cached price before writing to the cache.
        """
        now = datetime.now(timezone.utc).isoformat()
        result: dict[str, PriceUpdate] = {}
        for ticker in tickers:
            if ticker not in self._prices:
                # Dynamically add unknown tickers with fallback config
                self._config.tickers[ticker] = _FALLBACK_CONFIG
                self._prices[ticker] = _FALLBACK_CONFIG.seed_price
            price = round(self._prices[ticker], 2)
            result[ticker] = PriceUpdate(
                ticker=ticker,
                price=price,
                prev_price=price,  # polling loop replaces this with cached prev
                timestamp=now,
            )
        return result

    async def _run_loop(self) -> None:
        """Main simulation loop. Ticks every tick_interval_seconds."""
        cfg = self._config
        # dt in trading years: 252 trading days, 6.5 trading hours per day
        dt = cfg.tick_interval_seconds / (252 * 6.5 * 3600)

        while True:
            try:
                self._tick(dt)
                await asyncio.sleep(cfg.tick_interval_seconds)
            except asyncio.CancelledError:
                raise
            except Exception:
                logger.exception("Error in simulator tick — continuing")
                await asyncio.sleep(cfg.tick_interval_seconds)

    def _tick(self, dt: float) -> None:
        """Advance all ticker prices by one GBM time step."""
        sector_shocks = self._draw_sector_shocks()
        self._maybe_trigger_event()

        cfg = self._config
        for ticker, ticker_cfg in cfg.tickers.items():
            if ticker not in self._prices:
                continue
            rho = cfg.sector_correlations.get(ticker_cfg.sector, 0.0)
            z_sector = sector_shocks.get(ticker_cfg.sector, 0.0)
            z_idio = random.gauss(0, 1)

            # Sector-shock mixing: produces correct pairwise correlation = ρ²
            z = rho * z_sector + math.sqrt(max(0.0, 1 - rho ** 2)) * z_idio

            drift = (ticker_cfg.mu - 0.5 * ticker_cfg.sigma ** 2) * dt
            diffusion = ticker_cfg.sigma * math.sqrt(dt) * z
            self._prices[ticker] *= math.exp(drift + diffusion)

    def _draw_sector_shocks(self) -> dict[str, float]:
        """Draw one independent N(0,1) shock per active sector."""
        sectors = {cfg.sector for cfg in self._config.tickers.values()}
        return {sector: random.gauss(0, 1) for sector in sectors}

    def _maybe_trigger_event(self) -> None:
        """
        With small probability, apply a sudden 2–5% shock to a random ticker.
        Applied before the GBM step so the price continues naturally from the new level.
        """
        cfg = self._config
        if random.random() < cfg.event_probability:
            ticker = random.choice(list(self._prices))
            magnitude = random.uniform(cfg.event_magnitude_min, cfg.event_magnitude_max)
            direction = 1 if random.random() > 0.5 else -1
            self._prices[ticker] *= (1 + direction * magnitude)
            logger.debug(
                "Market event: %s moved %+.1f%%", ticker, direction * magnitude * 100
            )
