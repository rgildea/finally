"""Structured-output schema for the LLM chat assistant.

The model is instructed to return JSON matching ``ChatResponse``: a required
conversational ``message`` plus optional ``trades`` and ``watchlist_changes``
that the chat service auto-executes.
"""

from typing import Literal

from pydantic import BaseModel, Field


class TradeAction(BaseModel):
    """A market order the assistant wants to execute on the user's behalf."""

    ticker: str
    side: Literal["buy", "sell"]
    quantity: float


class WatchlistChange(BaseModel):
    """An add/remove the assistant wants to apply to the watchlist."""

    ticker: str
    action: Literal["add", "remove"]


class ChatResponse(BaseModel):
    """Top-level structured response returned by the LLM."""

    message: str = Field(description="Conversational response shown to the user.")
    trades: list[TradeAction] = Field(default_factory=list)
    watchlist_changes: list[WatchlistChange] = Field(default_factory=list)
