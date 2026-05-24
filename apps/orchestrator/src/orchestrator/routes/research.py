"""POST /research — deep research with deterministic citation. See ADR-0013, ADR-0021."""

from __future__ import annotations

import asyncio
import json
import threading
from typing import Literal

import httpx
from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import StreamingResponse
from inference import InferenceClient, InferenceConfig
from pydantic import BaseModel, Field
from retrieval import cosine_to_relevance

from ..flows.research_flow import ResearchResult, research
from ..flows.roma import PLANNER_FANOUT_CAP

router = APIRouter()


class ProviderOverride(BaseModel):
    """Per-request LLM provider override. Only affects synthesis/judge calls;
    embeddings always use the server's configured provider (ADR-0009)."""

    base_url: str = Field(min_length=1)
    api_key: str = Field(default="")
    synthesis_model: str | None = Field(default=None)
    judge_model: str | None = Field(default=None)


class ResearchRequest(BaseModel):
    query: str = Field(min_length=1)
    k: int = Field(default=20, ge=1, le=100)
    max_repair_attempts: int = Field(default=2, ge=0, le=5)
    max_sub_queries: int = Field(default=PLANNER_FANOUT_CAP, ge=1, le=PLANNER_FANOUT_CAP)
    skip_alignment: bool = Field(
        default=False,
        description="Skip the judge-model alignment check. Useful for fast smoke tests.",
    )
    # v0.2.2 — sign-off #7. Override the Atomizer's decompose decision.
    decompose: Literal["auto"] | bool = Field(
        default="auto",
        description=(
            'Atomizer override. "auto" (default) asks the judge model to '
            "decide. true/false bypasses the Atomizer LLM call entirely."
        ),
    )
    # v0.2.3 — sign-off #8. Per-run override on memory write.
    memory_write: bool = Field(
        default=True,
        description="When false, skip writing the run summary to Mem0 even if memory is enabled.",
    )
    # Source routing override. "auto" lets the Planner decide per sub-query.
    source_filter: Literal["auto", "vault", "web"] = Field(
        default="auto",
        description=(
            '"auto" — Planner decides per sub-query. '
            '"vault" — all sub-queries search vault only. '
            '"web" — all sub-queries search web only.'
        ),
    )
    # Optional per-request synthesis provider override (plugin-configured provider).
    provider_override: ProviderOverride | None = Field(default=None)


def _make_synthesis_client(
    override: ProviderOverride,
    base_client: InferenceClient,
) -> InferenceClient:
    """Build a synthesis-only InferenceClient from the plugin's provider override.

    Embedding model/config is inherited from the server's default client so the
    vault index remains consistent regardless of which synthesis provider is in use.
    """
    cfg = base_client.config
    return InferenceClient(
        InferenceConfig(
            base_url=override.base_url.rstrip("/"),
            api_key=override.api_key,
            synthesis_model=override.synthesis_model or cfg.synthesis_model,
            embedding_model=cfg.embedding_model,
            judge_model=override.judge_model or cfg.judge_model,
            embed_batch_size=cfg.embed_batch_size,
            timeout_s=cfg.timeout_s,
        )
    )


@router.post("/research")
async def research_route(req: ResearchRequest, request: Request) -> dict:
    store = getattr(request.app.state, "store", None)
    client = getattr(request.app.state, "client", None)
    if store is None or client is None:
        raise HTTPException(503, "orchestrator not ready")
    web_adapter = getattr(request.app.state, "web_adapter", None)
    memory = getattr(request.app.state, "memory", None)
    synthesis_client = (
        _make_synthesis_client(req.provider_override, client)
        if req.provider_override else None
    )
    try:
        result = await research(
            req.query,
            store=store,
            client=client,
            synthesis_client=synthesis_client,
            web_adapter=web_adapter,
            memory=memory,
            k=req.k,
            max_repair_attempts=req.max_repair_attempts,
            skip_alignment=req.skip_alignment,
            max_sub_queries=req.max_sub_queries,
            decompose=req.decompose,
            memory_write=req.memory_write,
            source_filter=req.source_filter,
        )
    except httpx.TimeoutException as e:
        raise HTTPException(
            504,
            "local inference request timed out; try a smaller k, disable decomposition, "
            "or increase [inference].timeout_s in config.toml",
        ) from e
    finally:
        if synthesis_client is not None:
            await synthesis_client.aclose()
    return _serialise(result)


def _serialise(result: ResearchResult) -> dict:
    return {
        "query": result.query,
        "markdown": result.markdown,
        "attempts": result.attempts,
        "pass_rate": result.verification.pass_rate,
        "failures": [_failure(f) for f in result.verification.failures],
        # v0.2.2 diagnostic shim (sign-off #8): every research run carries its
        # decomposition + per-Executor retrieval log so the plugin can render
        # them in the report's debug section. Lets the user see *why* certain
        # citations were chosen, separating retrieval noise from synthesis
        # hallucination.
        "atomizer": (
            {
                "decompose": result.atomizer_verdict.decompose,
                "rationale": result.atomizer_verdict.rationale,
            }
            if result.atomizer_verdict is not None
            else None
        ),
        "executions": [
            {
                "sub_query": sr.sub_query.text,
                "rationale": sr.sub_query.rationale,
                "attempts": sr.attempts,
                "pass_rate": sr.verification.pass_rate,
                "failures": [_failure(f) for f in sr.verification.failures],
                "chunks": [
                    {
                        "block_id": sc.chunk.block_id,
                        "relpath": sc.chunk.relpath,
                        # 0–1 relevance for display (rescaled cosine).
                        "score": cosine_to_relevance(sc.score),
                    }
                    for sc in sr.chunks
                ],
            }
            for sr in result.sub_reports
        ],
    }


@router.post("/research/stream")
async def research_stream_route(req: ResearchRequest, request: Request) -> StreamingResponse:
    store = getattr(request.app.state, "store", None)
    client = getattr(request.app.state, "client", None)
    if store is None or client is None:
        raise HTTPException(503, "orchestrator not ready")
    web_adapter = getattr(request.app.state, "web_adapter", None)
    memory = getattr(request.app.state, "memory", None)
    synthesis_client = (
        _make_synthesis_client(req.provider_override, client)
        if req.provider_override else None
    )

    queue: asyncio.Queue[dict | None] = asyncio.Queue()
    # Capture the running loop and its thread so `_on_progress` is safe to call
    # from LangGraph's thread-pool workers (sync nodes run via run_in_executor)
    # AND from async code running directly on the loop thread.
    loop = asyncio.get_running_loop()
    _loop_thread_id = threading.get_ident()

    def _put(item: dict) -> None:
        if threading.get_ident() == _loop_thread_id:
            queue.put_nowait(item)
        else:
            loop.call_soon_threadsafe(queue.put_nowait, item)

    def _on_progress(msg: str) -> None:
        _put({"type": "progress", "message": msg})

    def _on_event(evt: dict) -> None:
        _put(evt)

    async def run() -> None:
        try:
            result = await research(
                req.query,
                store=store,
                client=client,
                synthesis_client=synthesis_client,
                web_adapter=web_adapter,
                memory=memory,
                k=req.k,
                max_repair_attempts=req.max_repair_attempts,
                skip_alignment=req.skip_alignment,
                max_sub_queries=req.max_sub_queries,
                decompose=req.decompose,
                memory_write=req.memory_write,
                source_filter=req.source_filter,
                on_progress=_on_progress,
                on_event=_on_event,
            )
            queue.put_nowait({"type": "result", "data": _serialise(result)})
        except httpx.TimeoutException:
            queue.put_nowait({
                "type": "error",
                "message": (
                    "Research timed out — try disabling query expansion "
                    "or reducing search depth."
                ),
            })
        except Exception as e:
            queue.put_nowait({"type": "error", "message": str(e)})
        finally:
            queue.put_nowait(None)
            if synthesis_client is not None:
                await synthesis_client.aclose()

    async def generate():
        task = asyncio.create_task(run())
        try:
            while True:
                event = await queue.get()
                if event is None:
                    break
                yield f"data: {json.dumps(event)}\n\n"
        finally:
            if not task.done():
                task.cancel()
            try:
                await task
            except (asyncio.CancelledError, Exception):
                pass

    return StreamingResponse(
        generate(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


def _failure(f) -> dict:
    return {
        "kind": f.kind.value,
        "section": f.section_heading,
        "claim": f.claim_text,
        "block_id": f.block_id,
        "detail": f.detail,
    }
