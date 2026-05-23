"""GET /health — liveness + ingestion sanity probe."""

from __future__ import annotations

from fastapi import APIRouter, Request

router = APIRouter()


@router.get("/health")
async def health(request: Request) -> dict:
    store = getattr(request.app.state, "store", None)
    vault = getattr(request.app.state, "vault_path", None)
    return {
        "status": "ok",
        "vault": str(vault) if vault else None,
        "file_count": store.file_count() if store else 0,
        "chunk_count": store.chunk_count() if store else 0,
    }
