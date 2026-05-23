"""End-to-end tests for the v0.2 LangGraph research flow.

These exist specifically as the swap-invisibility gate for deliverable 1
(ADR-0020). The graph in `flows/graph.py` must produce identical observable
behaviour to the v0.1 flat function — same `ResearchResult` shape, same
`attempts` counting semantics, same repair-loop iteration limit.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from citation import Report
from orchestrator.flows.research_flow import research
from retrieval import Chunk, DuckDBStore, ScoredChunk

_CHUNK_TEXT = "Apple Silicon chips are good for local inference."
_BLOCK_ID = "ai-test-block"
_RELPATH = "notes/apple-silicon.md"


def _store_with_chunk(tmp_path: Path) -> DuckDBStore:
    store = DuckDBStore(tmp_path / "index.duckdb", embedding_dim=2)
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


def _good_report() -> Report:
    return Report.model_validate(
        {
            "title": "Local inference on Apple Silicon",
            "summary": "A short summary.",
            "sections": [
                {
                    "heading": "Hardware",
                    "claims": [
                        {
                            "text": "Apple Silicon performs well for local inference.",
                            "quote": "Apple Silicon chips are good for local inference.",
                            "block_id": _BLOCK_ID,
                        }
                    ],
                }
            ],
        }
    )


def _bad_report() -> Report:
    # Quote that is NOT a substring of the chunk → QUOTE_NOT_IN_SOURCE failure.
    return Report.model_validate(
        {
            "title": "Local inference on Apple Silicon",
            "summary": "A short summary.",
            "sections": [
                {
                    "heading": "Hardware",
                    "claims": [
                        {
                            "text": "Apple Silicon performs well for local inference.",
                            "quote": "totally fabricated quote not in the source.",
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
    """Queues `Report` objects to return from successive `complete()` calls."""

    def __init__(self, reports: list[Report]) -> None:
        self._reports = list(reports)
        self.calls: int = 0

    async def complete(self, messages, *, response_model, **_kwargs):
        self.calls += 1
        if not self._reports:
            raise AssertionError(
                f"FakeClient exhausted after {self.calls} calls; "
                f"messages tail: {messages[-1]['content'][:80]!r}"
            )
        return self._reports.pop(0)

    async def aclose(self) -> None:  # pragma: no cover - parity with real client
        pass


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
        score=0.99,
    )


@pytest.mark.asyncio
async def test_happy_path_single_synth_no_repair(tmp_path: Path):
    """Verification passes on first synth → graph goes straight to assemble."""
    store = _store_with_chunk(tmp_path)
    retriever = _FakeRetriever([_scored()])
    client = _FakeClient([_good_report()])

    result = await research(
        "How well does Apple Silicon do local inference?",
        store=store,
        client=client,  # type: ignore[arg-type]
        retriever=retriever,  # type: ignore[arg-type]
        k=5,
        max_repair_attempts=2,
        skip_alignment=True,
        # v0.2.2: bypass the Atomizer LLM call so this test continues to
        # exercise the bare retrieve→synth→verify→repair→assemble spine
        # (the v0.2.1 contract). The Atomizer is exercised explicitly by
        # the test_roma_flow.py tests.
        decompose=False,
    )

    assert result.attempts == 1
    assert client.calls == 1  # only the initial synth, no repair
    assert result.verification.pass_rate == 1.0
    assert result.verification.failures == []
    assert _BLOCK_ID in result.markdown
    assert retriever.calls == [
        ("How well does Apple Silicon do local inference?", 5)
    ]
    store.close()


@pytest.mark.asyncio
async def test_repair_path_recovers_after_one_attempt(tmp_path: Path):
    """First synth fails verification → one repair → passes → assemble."""
    store = _store_with_chunk(tmp_path)
    retriever = _FakeRetriever([_scored()])
    client = _FakeClient([_bad_report(), _good_report()])

    result = await research(
        "How well does Apple Silicon do local inference?",
        store=store,
        client=client,  # type: ignore[arg-type]
        retriever=retriever,  # type: ignore[arg-type]
        k=5,
        max_repair_attempts=2,
        skip_alignment=True,
        # v0.2.2: bypass the Atomizer LLM call so this test continues to
        # exercise the bare retrieve→synth→verify→repair→assemble spine
        # (the v0.2.1 contract). The Atomizer is exercised explicitly by
        # the test_roma_flow.py tests.
        decompose=False,
    )

    assert result.attempts == 2
    assert client.calls == 2  # initial + one repair
    assert result.verification.pass_rate == 1.0
    assert result.verification.failures == []
    store.close()


@pytest.mark.asyncio
async def test_repair_loop_bounded_by_max_attempts(tmp_path: Path):
    """Every synth fails → graph stops after max_repair_attempts and assembles
    the still-failing report. Matches v0.1 repair_loop semantics: attempts
    counts the total number of synth calls (initial + repairs)."""
    store = _store_with_chunk(tmp_path)
    retriever = _FakeRetriever([_scored()])
    # 1 initial + 2 repair attempts allowed → 3 synth calls before giving up.
    client = _FakeClient([_bad_report(), _bad_report(), _bad_report()])

    result = await research(
        "How well does Apple Silicon do local inference?",
        store=store,
        client=client,  # type: ignore[arg-type]
        retriever=retriever,  # type: ignore[arg-type]
        k=5,
        max_repair_attempts=2,
        skip_alignment=True,
        # v0.2.2: bypass the Atomizer LLM call so this test continues to
        # exercise the bare retrieve→synth→verify→repair→assemble spine
        # (the v0.2.1 contract). The Atomizer is exercised explicitly by
        # the test_roma_flow.py tests.
        decompose=False,
    )

    assert result.attempts == 3
    assert client.calls == 3
    assert result.verification.failures, "expected failures to remain after budget"
    # The assembler still runs against the final (failing) report.
    assert _BLOCK_ID in result.markdown
    store.close()
