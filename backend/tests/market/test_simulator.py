import asyncio
import math
import random

import pytest

from app.market.interface import PriceUpdate
from app.market.simulator import (
    MarketSimulator,
    SimulatorConfig,
    TickerConfig,
    _DEFAULT_TICKERS,
    _FALLBACK_CONFIG,
)


@pytest.mark.asyncio
async def test_get_prices_returns_all_default_tickers():
    sim = MarketSimulator()
    await sim.start()
    try:
        result = await sim.get_prices(list(_DEFAULT_TICKERS.keys()))
        assert set(result.keys()) == set(_DEFAULT_TICKERS.keys())
    finally:
        await sim.stop()


@pytest.mark.asyncio
async def test_all_prices_are_price_update_instances():
    sim = MarketSimulator()
    await sim.start()
    try:
        result = await sim.get_prices(["AAPL", "MSFT"])
        for update in result.values():
            assert isinstance(update, PriceUpdate)
    finally:
        await sim.stop()


@pytest.mark.asyncio
async def test_all_prices_positive():
    sim = MarketSimulator()
    await sim.start()
    await asyncio.sleep(1.0)
    try:
        result = await sim.get_prices(list(_DEFAULT_TICKERS.keys()))
        for ticker, update in result.items():
            assert update.price > 0, f"{ticker} has non-positive price {update.price}"
    finally:
        await sim.stop()


@pytest.mark.asyncio
async def test_unknown_ticker_uses_fallback():
    sim = MarketSimulator()
    await sim.start()
    try:
        result = await sim.get_prices(["ZZZZ"])
        assert "ZZZZ" in result
        assert result["ZZZZ"].price == _FALLBACK_CONFIG.seed_price
    finally:
        await sim.stop()


@pytest.mark.asyncio
async def test_prices_near_seed_after_short_run():
    """After 1 second, prices should be within ±10% of seed values."""
    sim = MarketSimulator()
    await sim.start()
    await asyncio.sleep(1.0)
    try:
        result = await sim.get_prices(list(_DEFAULT_TICKERS.keys()))
        for ticker, update in result.items():
            seed = _DEFAULT_TICKERS[ticker].seed_price
            ratio = update.price / seed
            assert 0.90 <= ratio <= 1.10, (
                f"{ticker} price {update.price:.2f} deviates >10% from seed {seed:.2f}"
            )
    finally:
        await sim.stop()


def test_tick_produces_finite_prices():
    """Unit test for _tick() without running the async loop."""
    random.seed(42)
    sim = MarketSimulator()
    dt = 0.5 / (252 * 6.5 * 3600)
    sim._tick(dt)
    for ticker, price in sim._prices.items():
        assert math.isfinite(price), f"{ticker} produced non-finite price"
        assert price > 0, f"{ticker} produced non-positive price"


def test_sector_shocks_one_per_sector():
    sim = MarketSimulator()
    shocks = sim._draw_sector_shocks()
    expected_sectors = {"Tech", "EV/Tech", "Media", "Finance"}
    assert set(shocks.keys()) == expected_sectors


def test_sector_shocks_are_floats():
    sim = MarketSimulator()
    shocks = sim._draw_sector_shocks()
    for sector, shock in shocks.items():
        assert isinstance(shock, float), f"Shock for {sector} is not a float"


@pytest.mark.asyncio
async def test_stop_without_start_is_safe():
    sim = MarketSimulator()
    await sim.stop()  # Should not raise


@pytest.mark.asyncio
async def test_start_idempotent():
    """Calling start() twice should not create a second task."""
    sim = MarketSimulator()
    await sim.start()
    task1 = sim._task
    await sim.start()
    task2 = sim._task
    assert task1 is task2
    await sim.stop()


@pytest.mark.asyncio
async def test_unknown_ticker_added_dynamically():
    """An unknown ticker added after init should appear on next get_prices call."""
    sim = MarketSimulator()
    await sim.start()
    try:
        result = await sim.get_prices(["NEWT"])
        assert "NEWT" in result
        assert "NEWT" in sim._config.tickers
    finally:
        await sim.stop()


def test_custom_config_respects_seed_prices():
    config = SimulatorConfig(
        tickers={
            "FOO": TickerConfig(seed_price=500.0, mu=0.10, sigma=0.20, sector="Tech"),
        },
        sector_correlations={"Tech": 0.5},
    )
    sim = MarketSimulator(config=config)
    assert sim._prices["FOO"] == 500.0


def test_tick_uses_ito_correction():
    """
    With drift=0 and sigma=0, price should stay exactly at seed after a tick.
    This validates that the GBM formula is correct (exp(0) = 1).
    """
    config = SimulatorConfig(
        tickers={"FLAT": TickerConfig(seed_price=100.0, mu=0.0, sigma=0.0, sector="Tech")},
        sector_correlations={"Tech": 0.0},
    )
    sim = MarketSimulator(config=config)
    dt = 0.5 / (252 * 6.5 * 3600)
    for _ in range(10):
        sim._tick(dt)
    assert sim._prices["FLAT"] == pytest.approx(100.0)
