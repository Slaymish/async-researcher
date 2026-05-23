"""POST /surface — proactive surfacing. See MVP §"Capability 1"."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, Field
from retrieval import Retriever

from ..flows.surface_flow import surface

router = APIRouter()


class SurfaceRequest(BaseModel):
    relpath: str = Field(min_length=1)
    content: str
    k: int = Field(default=8, ge=1, le=50)


@router.post("/surface")
async def surface_route(req: SurfaceRequest, request: Request) -> dict:
    store = getattr(request.app.state, "store", None)
    client = getattr(request.app.state, "client", None)
    if store is None or client is None:
        raise HTTPException(503, "orchestrator not ready")

    result = await surface(
        relpath=req.relpath,
        content=req.content,
        retriever=Retriever(store, client),
        k=req.k,
    )
    return {
        "results": [
            {
                "relpath": sc.chunk.relpath,
                "block_id": sc.chunk.block_id,
                "kind": sc.chunk.kind,
                "text": sc.chunk.text,
                "score": sc.score,
            }
            for sc in result.results
        ]
    }
