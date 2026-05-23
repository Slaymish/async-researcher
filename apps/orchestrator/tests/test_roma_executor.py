"""Executor unit tests (v0.2.2 step 4).

Per sign-off #2, #3: each Executor runs retrieve → synth → verify → repair
against its own retrieved context, returning a self-contained SubReport.
These tests use the same FakeRetriever / FakeClient pattern as the v0.2.1
research-flow tests so we exercise the real `citation.repair_loop` against
mocked retrieval + inference.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from citation import Report
from orchestrator.flows.roma import SubQuery, execute_sub_query
from retrieval import Chunk, DuckDBStore, ScoredChunk

_CHUNK_TEXT = "Apple Silicon handles 14B local inference."
_BLOCK_ID = "ai-test-exec"
_RELPATH = "notes/exec.md"


def _store_with_chunk(tmp_path: Path) -> DuckDBStore:
    store = DuckDBStore(tmp_path / "exec.duckdb", embedding_dim=2)
    store.upsert_chunks(
        [
            Chunk(
                block_id=_BLOCK_ID,
                relpath=_RELPATH,
                kind="para",
                text=_CHUNK_TEXT,
                line_start=1,
                line_end=1,
                frontmatter={},
                embedding=[1.0, 0.0],
            )
        ]
    )
    return store


def _scored() -> ScoredChunk:
    return ScoredChunk(
        chunk=Chunk(
            block_id=_BLOCK_ID,
            relpath=_RELPATH,
            kind="para",
            text=_CHUNK_TEXT,
            line_start=1,
            line_end=1,
            frontmatter={},
            embedding=None,
        ),
        score=0.91,
    )


def _good_report() -> Report:
    return Report.model_validate(
        {
            "title": "Local inference",
            "summary": "Summary.",
            "sections": [
                {
                    "heading": "Hardware",
                    "claims": [
                        {
                            "text": "Apple Silicon handles 14B models for local inference.",
                            "quote": "Apple Silicon handles 14B local inference.",
                            "block_id": _BLOCK_ID,
                        }
                    ],
                }
            ],
        }
    )


def _bad_report() -> Report:
    return Report.model_validate(
        {
            "title": "Local inference",
            "summary": "Summary.",
            "sections": [
                {
                    "heading": "Hardware",
                    "claims": [
                        {
                            "text": "Apple Silicon handles 14B models for local inference.",
                            "quote": "fabricated quote not in the source.",
                            "block_id": _BLOCK_ID,
                        }
                    ],
                }
            ],
        }
    )


class _FakeRetriever:
    def __init__(self, scored: list[ScoredChunk]) -> None:
        self._scored = scored
        self.calls: list[tuple[str, int]] = []

    async def retrieve(self, query: str, k: int = 20, **_kwargs):
        self.calls.append((query, k))
        return list(self._scored)


class _FakeClient:
    def __init__(self, reports: list[Report]) -> None:
        self._reports = list(reports)
        self.calls = 0

    async def complete(self, messages, *, response_model, **_kwargs):
        self.calls += 1
        if not self._reports:
            raise AssertionError("FakeClient exhausted")
        return self._reports.pop(0)


@pytest.mark.asyncio
async def test_executor_returns_sub_report_with_per_executor_verification(tmp_path: Path):
    store = _store_with_chunk(tmp_path)
    retriever = _FakeRetriever([_scored()])
    client = _FakeClient([_good_report()])

    sub_query = SubQuery(text="What about Apple Silicon?", rationale="hardware angle")
    result = await execute_sub_query(
        sub_query,
        retriever=retriever,  # type: ignore[arg-type]
        store=store,
        client=client,  # type: ignore[arg-type]
        k=5,
        max_repair_attempts=2,
        skip_alignment=True,
    )

    assert result.sub_query == sub_query
    assert result.attempts == 1
    assert result.verification.failures == []
    assert result.verification.pass_rate == 1.0
    assert len(result.chunks) == 1
    assert result.chunks[0].chunk.block_id == _BLOCK_ID
    # The Executor uses the sub-query's text, not the original user question.
    assert retriever.calls == [("What about Apple Silicon?", 5)]
    store.close()


@pytest.mark.asyncio
async def test_executor_recovers_via_repair(tmp_path: Path):
    """First synth fails → one repair → passes. Mirrors the v0.2.1 flow test."""
    store = _store_with_chunk(tmp_path)
    retriever = _FakeRetriever([_scored()])
    client = _FakeClient([_bad_report(), _good_report()])

    sub_query = SubQuery(text="q", rationale="r")
    result = await execute_sub_query(
        sub_query,
        retriever=retriever,  # type: ignore[arg-type]
        store=store,
        client=client,  # type: ignore[arg-type]
        k=5,
        max_repair_attempts=2,
        skip_alignment=True,
    )

    assert result.attempts == 2
    assert client.calls == 2
    assert result.verification.failures == []
    store.close()


@pytest.mark.asyncio
async def test_executor_emits_sub_report_even_when_repair_exhausted(tmp_path: Path):
    """Sign-off #3 detail: a failed sub-Report still propagates upward.

    Dropping it silently would hide signal the Aggregator + post-merge cycle
    need to react to. The Aggregator can decide to filter; the Executor is
    not the place to decide."""
    store = _store_with_chunk(tmp_path)
    retriever = _FakeRetriever([_scored()])
    # 1 initial + 2 repair attempts allowed → 3 calls, all bad → still emits.
    client = _FakeClient([_bad_report(), _bad_report(), _bad_report()])

    sub_query = SubQuery(text="q", rationale="r")
    result = await execute_sub_query(
        sub_query,
        retriever=retriever,  # type: ignore[arg-type]
        store=store,
        client=client,  # type: ignore[arg-type]
        k=5,
        max_repair_attempts=2,
        skip_alignment=True,
    )

    assert result.attempts == 3
    assert client.calls == 3
    assert result.verification.failures, "expected failures to remain after budget"
    store.close()
