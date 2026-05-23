"""Tests for citation.repair — bounded semantic-repair loop."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest
from citation import Claim, Report, Section
from citation.repair import RepairOutcome, _failure_brief, repair_loop
from citation.verify import ClaimFailure, FailureKind, VerificationReport
from retrieval import Chunk, DuckDBStore


def _store(tmp_path: Path) -> DuckDBStore:
    return DuckDBStore(tmp_path / "index.duckdb", embedding_dim=2)


def _passing_verification() -> VerificationReport:
    return VerificationReport(total_claims=1, failures=[])


def _failing_verification(n: int = 1) -> VerificationReport:
    failures = [
        ClaimFailure(
            kind=FailureKind.BROKEN_LINK,
            section_heading="S",
            claim_text=f"claim {i}",
            block_id=f"ai-{i}",
            detail="not found",
        )
        for i in range(n)
    ]
    return VerificationReport(total_claims=n, failures=failures)


def _good_report() -> Report:
    return Report(
        title="T",
        summary="S.",
        sections=[Section(heading="H", claims=[Claim(text="c", quote="q", block_id="ai-a")])],
    )


class _FailureKindStr:
    BROKEN_LINK = "broken_link"
    QUOTE_NOT_IN_SOURCE = "quote_not_in_source"
    UNSUPPORTED = "unsupported"
    MISSING_CITATION = "missing_citation"


# --- _failure_brief ----------------------------------------------------------


def test_failure_brief_contains_all_failure_fields():
    failures = [
        ClaimFailure(
            kind=FailureKind.QUOTE_NOT_IN_SOURCE,
            section_heading="Methods",
            claim_text="the method is efficient",
            block_id="ai-abc",
            detail="quote not found in source",
        )
    ]
    brief = _failure_brief(failures)
    assert "Methods" in brief
    assert "ai-abc" in brief
    assert "the method is efficient" in brief
    assert "quote not found in source" in brief
    assert "quote_not_in_source" in brief


def test_failure_brief_numbers_multiple_failures():
    failures = [
        ClaimFailure(FailureKind.BROKEN_LINK, "S", f"claim {i}", f"ai-{i}", "x")
        for i in range(3)
    ]
    brief = _failure_brief(failures)
    assert "[1]" in brief
    assert "[2]" in brief
    assert "[3]" in brief


def test_failure_brief_handles_none_block_id():
    failures = [
        ClaimFailure(
            kind=FailureKind.MISSING_CITATION,
            section_heading="S",
            claim_text="claim",
            block_id=None,
            detail="no citation",
        )
    ]
    brief = _failure_brief(failures)
    assert "(none)" in brief


# --- repair_loop: short-circuit on first pass --------------------------------


@pytest.mark.asyncio
async def test_repair_loop_returns_immediately_when_first_verify_passes(tmp_path: Path):
    store = _store(tmp_path)
    store.upsert_chunks(
        [Chunk("ai-a", "n.md", "para", "the quote is here exactly", 0, 1, {}, [1.0, 0.0])]
    )
    report = Report(
        title="T",
        summary="S.",
        sections=[
            Section(
                heading="H",
                claims=[Claim(text="source has quote", quote="the quote is here exactly", block_id="ai-a")],
            )
        ],
    )
    client = MagicMock()

    outcome = await repair_loop(
        report, "query", [], store, client, max_repair_attempts=2, skip_alignment=True
    )

    assert isinstance(outcome, RepairOutcome)
    assert outcome.attempts == 1
    assert outcome.verification.passed
    # No LLM call should be made when first verify passes.
    client.complete.assert_not_called()
    store.close()


@pytest.mark.asyncio
async def test_repair_loop_calls_complete_on_failure(tmp_path: Path):
    store = _store(tmp_path)
    # No chunks seeded → broken_link for any claim.
    report = _good_report()
    fixed_report = _good_report()

    client = AsyncMock()
    # First call: synthesis returns fixed report (still fails — no chunks).
    client.complete = AsyncMock(return_value=fixed_report)

    outcome = await repair_loop(
        report, "query", [], store, client, max_repair_attempts=1, skip_alignment=True
    )

    # One attempt for initial verify, one repair call, then we hit max.
    assert outcome.attempts == 2
    assert client.complete.call_count == 1
    store.close()


@pytest.mark.asyncio
async def test_repair_loop_respects_max_repair_attempts_zero(tmp_path: Path):
    store = _store(tmp_path)
    report = _good_report()
    client = AsyncMock()

    outcome = await repair_loop(
        report, "query", [], store, client, max_repair_attempts=0, skip_alignment=True
    )

    # max_repair_attempts=0 means verify once, never call LLM.
    assert outcome.attempts == 1
    client.complete.assert_not_called()
    store.close()


@pytest.mark.asyncio
async def test_repair_loop_passes_failure_brief_back_to_llm(tmp_path: Path):
    store = _store(tmp_path)
    # Seed chunk so quote check passes but block_id mismatch can be tested.
    store.upsert_chunks(
        [Chunk("ai-a", "n.md", "para", "exact quote text present here", 0, 1, {}, [1.0, 0.0])]
    )
    # Report cites ai-missing (not in store → broken link).
    broken = Report(
        title="T",
        summary="S.",
        sections=[
            Section(
                heading="H",
                claims=[Claim(text="claim", quote="exact quote text present here", block_id="ai-missing")],
            )
        ],
    )
    # Repair returns the same broken report (deliberately).
    client = AsyncMock()
    client.complete = AsyncMock(return_value=broken)

    outcome = await repair_loop(
        broken, "query", [], store, client, max_repair_attempts=2, skip_alignment=True
    )

    # Should have tried 2 repair attempts (initial + 2 repairs = 3 verify calls, 2 LLM calls).
    assert outcome.attempts == 3
    assert client.complete.call_count == 2
    # The conversation passed to complete should mention the failure kind.
    first_call_args = client.complete.call_args_list[0]
    messages_arg = first_call_args[0][0]
    user_content = next(m["content"] for m in messages_arg if m["role"] == "user" and "broken_link" in m.get("content", ""))
    assert "broken_link" in user_content
    store.close()


@pytest.mark.asyncio
async def test_repair_loop_short_circuits_if_repair_passes(tmp_path: Path):
    store = _store(tmp_path)
    store.upsert_chunks(
        [Chunk("ai-a", "n.md", "para", "the correct quote", 0, 1, {}, [1.0, 0.0])]
    )
    broken = Report(
        title="T",
        summary="S.",
        sections=[
            Section(
                heading="H",
                claims=[Claim(text="claim", quote="the correct quote", block_id="ai-missing")],
            )
        ],
    )
    fixed = Report(
        title="T",
        summary="S.",
        sections=[
            Section(
                heading="H",
                claims=[Claim(text="claim", quote="the correct quote", block_id="ai-a")],
            )
        ],
    )
    client = AsyncMock()
    client.complete = AsyncMock(return_value=fixed)

    outcome = await repair_loop(
        broken, "query", [], store, client, max_repair_attempts=3, skip_alignment=True
    )

    # One initial verify (fails), one LLM call, one re-verify (passes) → done.
    assert outcome.attempts == 2
    assert client.complete.call_count == 1
    assert outcome.verification.passed
    store.close()
