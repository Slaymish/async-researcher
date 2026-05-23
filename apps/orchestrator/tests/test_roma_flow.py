"""End-to-end ROMA flow tests (v0.2.2 step 7).

These exercise the full graph: atomize → (plan → fanout)? → execute → aggregate
→ (verify+repair)? → assemble. The v0.2.1 swap-invisibility tests in
`test_research_flow.py` cover the atomic-with-override path; this file covers
the LLM Atomizer paths (auto-atomic and auto-decompose) and the parallel
fan-out behaviour.

Stubs queue responses by type — Atomizer pops AtomizerVerdicts, Planner pops
Plans, Executors pop Reports. The shared inference client routes each call
to the right queue based on `response_model`.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from citation import Report
from inference import InferenceConfig
from orchestrator.flows.research_flow import research
from orchestrator.flows.roma import AtomizerVerdict, Plan, SubQuery
from retrieval import Chunk, DuckDBStore, ScoredChunk

_CHUNK_TEXT = "Apple Silicon handles 14B local inference."
_BLOCK_ID = "ai-flow"
_RELPATH = "notes/flow.md"


def _store(tmp_path: Path) -> DuckDBStore:
    s = DuckDBStore(tmp_path / "f.duckdb", embedding_dim=2)
    s.upsert_chunks(
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
    return s


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


def _report(title: str = "T", claim: str = "Apple Silicon handles 14B.") -> Report:
    return Report.model_validate(
        {
            "title": title,
            "summary": "S",
            "sections": [
                {
                    "heading": "H",
                    "claims": [
                        {
                            "text": claim,
                            "quote": _CHUNK_TEXT,
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


class _TypeAwareClient:
    """Routes complete() by response_model — Atomizer/Planner/Executor each
    have their own queue. This is the shape the real graph needs once the
    Atomizer LLM call is in play.
    """

    def __init__(
        self,
        *,
        atomizer_verdicts: list[AtomizerVerdict] | None = None,
        plans: list[Plan] | None = None,
        reports: list[Report] | None = None,
    ) -> None:
        self._verdicts = list(atomizer_verdicts or [])
        self._plans = list(plans or [])
        self._reports = list(reports or [])
        self.config = InferenceConfig(
            base_url="http://localhost:11434/v1",
            api_key="x",
            synthesis_model="big",
            embedding_model="embed",
            judge_model="small",
        )
        self.atomizer_calls = 0
        self.planner_calls = 0
        self.report_calls = 0

    async def complete(self, messages, *, response_model, model=None, **_kwargs):
        # The Atomizer is the only caller that passes `model=judge_model` and
        # asks for AtomizerVerdict; routing on the schema is enough.
        if response_model is AtomizerVerdict:
            self.atomizer_calls += 1
            return self._verdicts.pop(0)
        if response_model is Plan:
            self.planner_calls += 1
            return self._plans.pop(0)
        if response_model is Report:
            self.report_calls += 1
            return self._reports.pop(0)
        raise AssertionError(f"unexpected response_model {response_model}")


@pytest.mark.asyncio
async def test_auto_atomic_runs_one_executor(tmp_path: Path):
    """Atomizer says decompose=False → no Planner call, one Executor runs,
    SubReport.attempts surfaces as ResearchResult.attempts (no post-merge cycle)."""
    store = _store(tmp_path)
    retriever = _FakeRetriever([_scored()])
    client = _TypeAwareClient(
        atomizer_verdicts=[AtomizerVerdict(decompose=False, rationale="atomic")],
        reports=[_report()],
    )

    result = await research(
        "How well does Apple Silicon do local inference?",
        store=store,
        client=client,  # type: ignore[arg-type]
        retriever=retriever,  # type: ignore[arg-type]
        k=5,
        max_repair_attempts=2,
        skip_alignment=True,
        # default decompose="auto" exercises the Atomizer
    )

    assert client.atomizer_calls == 1
    assert client.planner_calls == 0
    assert client.report_calls == 1  # only the per-Executor synth
    assert result.attempts == 1  # one Executor, one synth, no repair
    assert result.verification.failures == []
    assert result.atomizer_verdict is not None
    assert result.atomizer_verdict.decompose is False
    assert len(result.sub_reports) == 1
    assert result.sub_reports[0].sub_query.text == (
        "How well does Apple Silicon do local inference?"
    )
    # Retriever was called once with the original query (atomic Executor
    # uses the user question verbatim).
    assert len(retriever.calls) == 1
    assert retriever.calls[0][0] == "How well does Apple Silicon do local inference?"
    store.close()


@pytest.mark.asyncio
async def test_auto_decompose_fans_out_three_executors(tmp_path: Path):
    """Atomizer says decompose=True → Planner returns 3 sub-queries → 3
    Executors run in parallel → Aggregator merges → post-merge verify runs
    (and passes, because every claim is clean against the store)."""
    store = _store(tmp_path)
    retriever = _FakeRetriever([_scored()])
    plan = Plan(
        sub_queries=[
            SubQuery(text="hw angle?", rationale="hardware"),
            SubQuery(text="sw angle?", rationale="software"),
            SubQuery(text="bench angle?", rationale="benchmarks"),
        ]
    )
    client = _TypeAwareClient(
        atomizer_verdicts=[AtomizerVerdict(decompose=True, rationale="multi")],
        plans=[plan],
        # 3 Executors → 3 reports. Each Executor calls synth once.
        reports=[_report("R1"), _report("R2"), _report("R3")],
    )

    result = await research(
        "multi-topic spec",
        store=store,
        client=client,  # type: ignore[arg-type]
        retriever=retriever,  # type: ignore[arg-type]
        k=5,
        max_repair_attempts=2,
        skip_alignment=True,
    )

    assert client.atomizer_calls == 1
    assert client.planner_calls == 1
    assert client.report_calls == 3  # one per Executor; no repair needed
    # Post-merge attempts counter (per-Executor counters are in sub_reports[]).
    assert result.attempts == 1
    assert result.verification.failures == []
    assert len(result.sub_reports) == 3
    # Aggregator titled with the original user query, not a sub-Report title.
    assert result.report.title == "multi-topic spec"
    # One section per sub-query, in Plan order.
    headings = [s.heading for s in result.report.sections]
    assert headings == ["hw angle?", "sw angle?", "bench angle?"]
    # Three retrieve calls — one per Executor — each with the sub-query text.
    assert {q for q, _ in retriever.calls} == {
        "hw angle?",
        "sw angle?",
        "bench angle?",
    }
    store.close()


@pytest.mark.asyncio
async def test_user_override_decompose_false_skips_atomizer(tmp_path: Path):
    """decompose=False on the API → Atomizer LLM call skipped entirely."""
    store = _store(tmp_path)
    retriever = _FakeRetriever([_scored()])
    client = _TypeAwareClient(reports=[_report()])  # no verdicts queued

    result = await research(
        "any query",
        store=store,
        client=client,  # type: ignore[arg-type]
        retriever=retriever,  # type: ignore[arg-type]
        k=5,
        max_repair_attempts=2,
        skip_alignment=True,
        decompose=False,
    )

    assert client.atomizer_calls == 0  # the headline assertion
    assert client.planner_calls == 0
    assert client.report_calls == 1
    assert result.atomizer_verdict is None  # we skipped the call
    assert len(result.sub_reports) == 1
    store.close()


@pytest.mark.asyncio
async def test_user_override_decompose_true_skips_atomizer_runs_planner(tmp_path: Path):
    store = _store(tmp_path)
    retriever = _FakeRetriever([_scored()])
    plan = Plan(sub_queries=[SubQuery(text="q1", rationale="r1")])
    client = _TypeAwareClient(plans=[plan], reports=[_report()])

    result = await research(
        "any query",
        store=store,
        client=client,  # type: ignore[arg-type]
        retriever=retriever,  # type: ignore[arg-type]
        k=5,
        max_repair_attempts=2,
        skip_alignment=True,
        decompose=True,
    )

    assert client.atomizer_calls == 0  # forced — no LLM gate
    assert client.planner_calls == 1
    # Planner returned 1 sub-query → 1 Executor → atomic-shape Aggregator path
    # (single sub_report → post-merge cycle skipped per _route_after_aggregate).
    assert client.report_calls == 1
    assert result.atomizer_verdict is None
    assert len(result.sub_reports) == 1
    store.close()


@pytest.mark.asyncio
async def test_max_sub_queries_limits_decomposed_executor_count(tmp_path: Path):
    store = _store(tmp_path)
    retriever = _FakeRetriever([_scored()])
    plan = Plan(
        sub_queries=[
            SubQuery(text="q1", rationale="r1"),
            SubQuery(text="q2", rationale="r2"),
            SubQuery(text="q3", rationale="r3"),
        ]
    )
    client = _TypeAwareClient(
        atomizer_verdicts=[AtomizerVerdict(decompose=True, rationale="multi")],
        plans=[plan],
        reports=[_report("R1"), _report("R2")],
    )

    result = await research(
        "multi-topic spec",
        store=store,
        client=client,  # type: ignore[arg-type]
        retriever=retriever,  # type: ignore[arg-type]
        k=5,
        max_repair_attempts=2,
        skip_alignment=True,
        max_sub_queries=2,
    )

    assert client.report_calls == 2
    assert len(result.sub_reports) == 2
    assert [sr.sub_query.text for sr in result.sub_reports] == ["q1", "q2"]
    store.close()
