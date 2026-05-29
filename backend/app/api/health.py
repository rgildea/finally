"""Health check endpoint for Docker and deployment probes."""

from fastapi import APIRouter

router = APIRouter()


@router.get("/api/health")
async def health() -> dict:
    """Return a simple liveness signal."""
    return {"status": "ok"}
