"""Cerebras-backed LLM client.

Calls ``openrouter/openai/gpt-oss-120b`` via LiteLLM + OpenRouter with Cerebras
pinned as the inference provider, requesting a structured ``ChatResponse``.
``litellm.completion`` is synchronous, so it runs in a worker thread to avoid
blocking the event loop.
"""

import asyncio

from litellm import completion

from .schema import ChatResponse

MODEL = "openrouter/openai/gpt-oss-120b"
EXTRA_BODY = {"provider": {"order": ["cerebras"]}}


async def complete_chat(messages: list[dict]) -> ChatResponse:
    """Call the LLM with the given messages and parse the structured response.

    Raises:
        ValueError: If the model returns content that does not match the schema.
    """
    response = await asyncio.to_thread(
        completion,
        model=MODEL,
        messages=messages,
        response_format=ChatResponse,
        reasoning_effort="low",
        extra_body=EXTRA_BODY,
    )
    content = response.choices[0].message.content
    return ChatResponse.model_validate_json(content)
