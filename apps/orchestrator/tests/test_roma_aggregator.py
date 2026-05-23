"""Aggregator unit tests (v0.2.2 step 5).

Pure functions — deterministic merge of `list[SubReport]` into a single
`Report` plus the unioned chunks. The atomic-case pass-through is the
critical invariant: it preserves v0.2.1's observable behaviour for queries
the Atomizer marks atomic.
"""

from __future__ import annotations

import pytest
from citation import Report, VerificationReport
from orchestrator.flows.roma import (
    Plan,
    SubQuery,
    SubReport,
    aggregate,
)
from retrieval import Chunk, ScoredChunk


def _scored(block_id: str, relpath: str, score: float, text: str = "t") -> ScoredChunk:
    return ScoredChunk(
        chunk=Chunk(
            block_id=block_id,
            relpath=relpath,
            kind="para",
            text=text,
            line_start=1,
            line_end=1,
            frontmatter={},
            embedding=None,
        ),
        score=score,
    )


def _report(title: str, summary: str, claim_pairs: list[tuple[str, str, str]]) -> Report:
    """`claim_pairs` = list of (heading, text, block_id)."""
    by_heading: dict[str, list[dict]] = {}
    for heading, text, bid in claim_pairs:
        by_heading.setdefault(heading, []).append(
            {"text": text, "quote": "t", "block_id": bid}
        )
    sections = [{"heading": h, "claims": claims} for h, claims in by_heading.items()]
    return Report.model_validate(
        {"title": title, "summary": summary, "sections": sections}
    )


def _sub_report(
    sub_query_text: str,
    chunks: list[ScoredChunk],
    report: Report,
) -> SubReport:
    return SubReport(
        sub_query=SubQuery(text=sub_query_text, rationale=f"because {sub_query_text}"),
        chunks=chunks,
        report=report,
        verification=VerificationReport(total_claims=1, failures=[]),
        attempts=1,
    )


def test_atomic_case_passes_sub_report_through_unchanged():
    """Single SubReport → Aggregator returns its Report + its chunks as-is.

    This is the v0.2.1 swap-invisibility invariant. If this breaks, every
    Atomizer-says-atomic query regresses."""
    chunks = [_scored("ai-a", "a.md", 0.9)]
    report = _report(
        "Original synth title",
        "Original synth summary.",
        [("Hardware", "claim about hw.", "ai-a")],
    )
    sub = _sub_report("q", chunks, report)

    merged, merged_chunks = aggregate([sub], query="user question?", plan=None)

    # Pass-through: title comes from the synth model, not the user query.
    assert merged.title == "Original synth title"
    assert merged.summary == "Original synth summary."
    assert merged.sections == report.sections
    assert merged_chunks == chunks


def test_decomposed_case_titles_from_user_query():
    chunks_a = [_scored("ai-a", "a.md", 0.9)]
    chunks_b = [_scored("ai-b", "b.md", 0.8)]
    a = _sub_report("subq A", chunks_a, _report("ta", "sa", [("Ha", "ca.", "ai-a")]))
    b = _sub_report("subq B", chunks_b, _report("tb", "sb", [("Hb", "cb.", "ai-b")]))

    merged, _ = aggregate([a, b], query="user multi-topic question", plan=None)

    assert merged.title == "user multi-topic question"


def test_decomposed_case_one_section_per_sub_query():
    chunks_a = [_scored("ai-a", "a.md", 0.9)]
    chunks_b = [_scored("ai-b", "b.md", 0.8)]
    a = _sub_report(
        "subq A",
        chunks_a,
        _report("ta", "sa", [("Ha1", "ca1.", "ai-a"), ("Ha2", "ca2.", "ai-a")]),
    )
    b = _sub_report("subq B", chunks_b, _report("tb", "sb", [("Hb", "cb.", "ai-b")]))

    merged, _ = aggregate([a, b], query="q", plan=None)

    # 2 sub-reports → 2 top-level sections; the sub-report's own internal
    # sections are flattened into one Section per sub-query.
    assert len(merged.sections) == 2
    assert [s.heading for s in merged.sections] == ["subq A", "subq B"]
    assert len(merged.sections[0].claims) == 2  # flattened from Ha1 + Ha2
    assert len(merged.sections[1].claims) == 1


def test_decomposed_case_orders_by_plan_not_completion():
    chunks_a = [_scored("ai-a", "a.md", 0.9)]
    chunks_b = [_scored("ai-b", "b.md", 0.8)]
    chunks_c = [_scored("ai-c", "c.md", 0.7)]
    # SubReports arrive in completion order — say C finishes first, then A, then B.
    completion_order = [
        _sub_report("Q-C", chunks_c, _report("tc", "sc", [("Hc", "cc.", "ai-c")])),
        _sub_report("Q-A", chunks_a, _report("ta", "sa", [("Ha", "ca.", "ai-a")])),
        _sub_report("Q-B", chunks_b, _report("tb", "sb", [("Hb", "cb.", "ai-b")])),
    ]
    # The Plan declared A, B, C — that's the canonical order.
    plan = Plan(
        sub_queries=[
            SubQuery(text="Q-A", rationale="ra"),
            SubQuery(text="Q-B", rationale="rb"),
            SubQuery(text="Q-C", rationale="rc"),
        ]
    )

    merged, _ = aggregate(completion_order, query="q", plan=plan)

    assert [s.heading for s in merged.sections] == ["Q-A", "Q-B", "Q-C"]


def test_chunks_deduped_by_block_id_keeping_max_score():
    # Same block_id retrieved by two Executors with different scores → keep max.
    shared_low = _scored("ai-shared", "x.md", 0.4)
    shared_high = _scored("ai-shared", "x.md", 0.9)
    unique_a = _scored("ai-a", "a.md", 0.7)
    a = _sub_report("qa", [shared_low, unique_a], _report("t", "s", [("H", "c.", "ai-a")]))
    b = _sub_report("qb", [shared_high], _report("t", "s", [("H", "c.", "ai-shared")]))

    _, chunks = aggregate([a, b], query="q", plan=None)

    assert {sc.chunk.block_id for sc in chunks} == {"ai-shared", "ai-a"}
    shared = next(sc for sc in chunks if sc.chunk.block_id == "ai-shared")
    assert shared.score == 0.9
    # Ordered by descending score.
    assert chunks[0].score >= chunks[-1].score


def test_summary_includes_each_sub_query_rationale():
    a = _sub_report("qa", [_scored("ai-a", "a.md", 0.9)],
                    _report("t", "summary about A.", [("H", "c.", "ai-a")]))
    b = _sub_report("qb", [_scored("ai-b", "b.md", 0.8)],
                    _report("t", "summary about B.", [("H", "c.", "ai-b")]))

    merged, _ = aggregate([a, b], query="q", plan=None)

    assert "because qa" in merged.summary
    assert "summary about A" in merged.summary
    assert "because qb" in merged.summary
    assert "summary about B" in merged.summary


def test_empty_sub_reports_raises():
    with pytest.raises(ValueError):
        aggregate([], query="q", plan=None)
