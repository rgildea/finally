"""Prompt construction for the chat assistant.

Builds the message list sent to the LLM: a system prompt describing FinAlly, a
portfolio/watchlist context block, recent conversation history, and the user's
new message.
"""

import json

SYSTEM_PROMPT = (
    "You are FinAlly, an AI trading assistant embedded in a simulated trading "
    "workstation. Analyze the user's portfolio composition, risk concentration, "
    "and P&L. Suggest trades with clear reasoning, and execute them when the user "
    "asks or agrees. Manage the watchlist proactively. Be concise and data-driven. "
    "All trades are market orders filled instantly at the current price in a "
    "simulated account with fake money. Always respond with the structured JSON "
    "schema: a conversational `message`, plus optional `trades` and "
    "`watchlist_changes` arrays for actions to execute on the user's behalf."
)


def build_messages(
    user_message: str,
    portfolio: dict,
    watchlist: list[dict],
    history: list[dict],
) -> list[dict]:
    """Assemble the LLM message list from context and conversation history."""
    messages: list[dict] = [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "system", "content": _context_block(portfolio, watchlist)},
    ]
    for msg in history:
        role = msg.get("role")
        if role in {"user", "assistant"}:
            messages.append({"role": role, "content": msg.get("content", "")})
    messages.append({"role": "user", "content": user_message})
    return messages


def _context_block(portfolio: dict, watchlist: list[dict]) -> str:
    """Render the current portfolio and watchlist as a compact JSON context."""
    context = {"portfolio": portfolio, "watchlist": watchlist}
    return "Current account state:\n" + json.dumps(context, default=str)
