"""POST /api/chat — SSE chat endpoint.

Streams the assistant turn using the protocol the frontend depends on:

    event: token   data: {"text": "..."}        (repeated)
    event: action  data: {"trades": [...], "watchlist_changes": [...]}
    event: done    data: {"message_id": "..."}
    event: error   data: {"detail": "..."}
"""

import json

from fastapi import APIRouter
from pydantic import BaseModel
from sse_starlette.sse import EventSourceResponse

from app.llm.service import run_chat

router = APIRouter()


class ChatRequest(BaseModel):
    message: str


@router.post("/api/chat")
async def chat(request: ChatRequest) -> EventSourceResponse:
    """Run one chat turn and stream the result as Server-Sent Events."""

    async def event_stream():
        async for event_name, data in run_chat(request.message):
            yield {"event": event_name, "data": json.dumps(data)}

    return EventSourceResponse(event_stream())
