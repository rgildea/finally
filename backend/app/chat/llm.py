"""LLM integration: structured LiteLLM→Cerebras call with mock-mode gate."""
import logging
import os

from litellm import acompletion
from pydantic import BaseModel, ValidationError

logger = logging.getLogger(__name__)

MODEL = "openrouter/openai/gpt-oss-120b"
EXTRA_BODY = {"provider": {"order": ["cerebras"]}}
LLM_MOCK = os.getenv("LLM_MOCK", "false").lower() == "true"


class TradeAction(BaseModel):
    ticker: str
    side: str
    quantity: float


class WatchlistAction(BaseModel):
    ticker: str
    action: str


class ChatResponse(BaseModel):
    message: str
    trades: list[TradeAction] = []
    watchlist_changes: list[WatchlistAction] = []


MOCK_RESPONSE = ChatResponse(
    message="This is a mock response. Your portfolio looks great!",
    trades=[],
    watchlist_changes=[],
)


async def get_llm_response(messages: list[dict]) -> ChatResponse:
    """Call the LLM and return a structured ChatResponse. Returns mock when LLM_MOCK=true."""
    if os.getenv("LLM_MOCK", "false").lower() == "true":
        return MOCK_RESPONSE
    response = await acompletion(
        model=MODEL,
        messages=messages,
        response_format=ChatResponse,
        reasoning_effort="low",
        extra_body=EXTRA_BODY,
    )
    try:
        return ChatResponse.model_validate_json(response.choices[0].message.content)
    except ValidationError:
        logger.exception("LLM returned malformed structured response")
        return ChatResponse(message="I encountered an error processing the response. Please try again.")


def build_system_messages() -> list[dict]:
    """Return the system prompt messages for the LLM."""
    return [
        {
            "role": "system",
            "content": (
                "You are FinAlly, an AI trading assistant for a simulated trading workstation. "
                "Analyze portfolio composition, risk concentration, and P&L. "
                "Suggest trades with reasoning. Execute trades when the user asks or agrees. "
                "Manage the watchlist proactively. Be concise and data-driven. "
                "Always respond with valid structured JSON matching the required schema."
            ),
        }
    ]
