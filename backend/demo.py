"""
FinAlly market data backend — live terminal demo.

Runs the GBM simulator for a handful of tickers and displays a Rich terminal
UI with live prices, per-tick sparklines, and a log of random shock events.

Usage:
    cd backend
    uv run --group dev python demo.py
"""

import asyncio
import random
from collections import deque
from datetime import datetime

from rich import box
from rich.console import Console
from rich.layout import Layout
from rich.live import Live
from rich.panel import Panel
from rich.table import Table
from rich.text import Text

from app.market.interface import PriceUpdate
from app.market.simulator import (
    MarketSimulator,
    SimulatorConfig,
    _DEFAULT_CORRELATIONS,
    _DEFAULT_TICKERS,
)

# ── Config ────────────────────────────────────────────────────────────────────

DEMO_TICKERS = ["AAPL", "MSFT", "NVDA", "TSLA", "JPM", "NFLX"]
SPARKLINE_LEN = 40       # price history points kept per ticker
REFRESH_HZ = 4           # display redraws per second
EVENT_PROBABILITY = 0.04 # elevated vs default (0.001) so events appear in demo

# ── Sparkline ─────────────────────────────────────────────────────────────────

_BLOCKS = "▁▂▃▄▅▆▇█"


def sparkline(values: list[float]) -> str:
    """Map a price history to a single-row unicode sparkline."""
    if len(values) < 2:
        return "─" * len(values)
    lo, hi = min(values), max(values)
    if hi == lo:
        return _BLOCKS[3] * len(values)
    scale = len(_BLOCKS) - 1
    return "".join(_BLOCKS[int((v - lo) / (hi - lo) * scale)] for v in values)


# ── Instrumented simulator ────────────────────────────────────────────────────

class _DemoSimulator(MarketSimulator):
    """Subclass that fires a callback when a random shock event occurs."""

    def __init__(self, config: SimulatorConfig, on_event) -> None:
        super().__init__(config)
        self._on_event = on_event

    def _maybe_trigger_event(self) -> None:
        cfg = self._config
        if random.random() < cfg.event_probability:
            ticker = random.choice(list(self._prices))
            magnitude = random.uniform(cfg.event_magnitude_min, cfg.event_magnitude_max)
            direction = 1 if random.random() > 0.5 else -1
            self._prices[ticker] *= (1 + direction * magnitude)
            self._on_event(ticker, direction * magnitude * 100)


# ── Display builders ──────────────────────────────────────────────────────────

def _price_table(latest: dict[str, PriceUpdate], history: dict[str, deque]) -> Table:
    table = Table(
        box=box.SIMPLE,
        header_style="bold #ecad0a",
        show_edge=False,
        pad_edge=False,
        padding=(0, 2),
    )
    table.add_column("TICKER", style="bold white", width=7)
    table.add_column("PRICE", justify="right", width=11)
    table.add_column("CHANGE", justify="right", width=10)
    table.add_column(f"LAST {SPARKLINE_LEN} TICKS", width=SPARKLINE_LEN + 2)

    for ticker in DEMO_TICKERS:
        upd = latest.get(ticker)
        hist = list(history[ticker])
        spark = sparkline(hist)

        if upd is None:
            table.add_row(ticker, "…", "…", Text(spark, style="dim"))
            continue

        pct = upd.change_pct
        up = pct >= 0
        color = "green" if up else "red"
        arrow = "▲" if up else "▼"

        # Colour the sparkline by overall trend (first vs last in window)
        if len(hist) >= 2:
            trend_color = "green" if hist[-1] >= hist[0] else "red"
        else:
            trend_color = "dim"

        table.add_row(
            ticker,
            Text(f"${upd.price:>10.2f}", style=f"bold {color}"),
            Text(f"{arrow} {abs(pct):.3f}%", style=color),
            Text(spark, style=trend_color),
        )

    return table


def _event_panel(events: deque) -> Panel:
    if not events:
        body = Text("Waiting for market events…", style="dim italic")
    else:
        body = Text.from_markup("\n".join(events))
    return Panel(
        body,
        title="[bold #ecad0a]Event Log[/bold #ecad0a]",
        border_style="#ecad0a",
    )


def _build_layout(
    latest: dict[str, PriceUpdate],
    history: dict[str, deque],
    events: deque,
) -> Layout:
    layout = Layout()
    layout.split_column(
        Layout(name="prices", ratio=3),
        Layout(name="events", ratio=2),
    )
    layout["prices"].update(
        Panel(
            _price_table(latest, history),
            title="[bold #209dd7]FinAlly — Market Data Backend Demo[/bold #209dd7]",
            subtitle="[dim]Ctrl-C to exit[/dim]",
            border_style="#209dd7",
        )
    )
    layout["events"].update(_event_panel(events))
    return layout


# ── Main loop ─────────────────────────────────────────────────────────────────

async def run() -> None:
    events: deque[str] = deque(maxlen=10)
    history: dict[str, deque] = {t: deque(maxlen=SPARKLINE_LEN) for t in DEMO_TICKERS}
    latest: dict[str, PriceUpdate] = {}

    def record_event(ticker: str, pct: float) -> None:
        color = "green" if pct > 0 else "red"
        arrow = "▲" if pct > 0 else "▼"
        ts = datetime.now().strftime("%H:%M:%S")
        events.appendleft(
            f"[dim]{ts}[/dim]  [bold {color}]{arrow} {ticker}[/bold {color}]"
            f"  random shock  [{color}]{pct:+.2f}%[/{color}]"
        )

    cfg = SimulatorConfig(
        tickers={t: _DEFAULT_TICKERS[t] for t in DEMO_TICKERS},
        sector_correlations=dict(_DEFAULT_CORRELATIONS),
        tick_interval_seconds=0.5,
        event_probability=EVENT_PROBABILITY,
    )
    sim = _DemoSimulator(cfg, on_event=record_event)
    await sim.start()

    console = Console()
    interval = 1.0 / REFRESH_HZ

    try:
        with Live(
            _build_layout(latest, history, events),
            console=console,
            refresh_per_second=REFRESH_HZ,
            screen=True,
        ) as live:
            while True:
                prices = await sim.get_prices(DEMO_TICKERS)
                for ticker, upd in prices.items():
                    prev = latest.get(ticker)
                    history[ticker].append(upd.price)
                    latest[ticker] = PriceUpdate(
                        ticker=ticker,
                        price=upd.price,
                        prev_price=prev.price if prev else upd.price,
                        timestamp=upd.timestamp,
                    )
                live.update(_build_layout(latest, history, events))
                await asyncio.sleep(interval)
    finally:
        await sim.stop()


if __name__ == "__main__":
    try:
        asyncio.run(run())
    except KeyboardInterrupt:
        pass
