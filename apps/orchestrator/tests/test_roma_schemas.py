"""Unit tests for ROMA schemas (v0.2.2 step 1).

These pin the wire format the Atomizer/Planner LLM calls have to produce, and
they catch accidental schema drift before it leaks into prompt engineering.
The Pydantic models are validated against the inference adapter's JSON-mode
output — if `extra="forbid"` is removed or a required field becomes optional
without thought, these tests are the trip-wire.
"""

from __future__ import annotations

import pytest
from citation import Report
from orchestrator.flows.roma import (
    PLANNER_FANOUT_CAP,
    AtomizerVerdict,
    Plan,
    SubQuery,
    SubReport,
)
from pydantic import ValidationError


def test_atomizer_verdict_round_trips_through_json():
    v = AtomizerVerdict(decompose=True, rationale="multi-topic spec note")
    raw = v.model_dump_json()
    again = AtomizerVerdict.model_validate_json(raw)
    assert again == v


def test_atomizer_verdict_rejects_unknown_fields():
    with pytest.raises(ValidationError):
        AtomizerVerdict.model_validate(
            {"decompose": False, "rationale": "atomic", "confidence": 0.9}
        )


def test_atomizer_verdict_rationale_is_required():
    with pytest.raises(ValidationError):
        AtomizerVerdict.model_validate({"decompose": False, "rationale": ""})


def test_subquery_defaults_target_to_vault():
    sq = SubQuery(text="What did I note about citation?", rationale="cover citations")
    assert sq.target == "vault"


def test_subquery_rejects_non_vault_target():
    with pytest.raises(ValidationError):
        SubQuery.model_validate(
            {"text": "q", "rationale": "r", "target": "web"}
        )


def test_plan_requires_at_least_one_subquery():
    with pytest.raises(ValidationError):
        Plan.model_validate({"sub_queries": []})


def test_plan_caps_subqueries_at_fanout_cap():
    too_many = [
        {"text": f"q{i}", "rationale": "r"}
        for i in range(PLANNER_FANOUT_CAP + 1)
    ]
    with pytest.raises(ValidationError):
        Plan.model_validate({"sub_queries": too_many})


def test_plan_accepts_exactly_fanout_cap():
    just_enough = [
        SubQuery(text=f"q{i}", rationale="r")
        for i in range(PLANNER_FANOUT_CAP)
    ]
    plan = Plan(sub_queries=just_enough)
    assert len(plan.sub_queries) == PLANNER_FANOUT_CAP


def test_subreport_holds_per_executor_state():
    # Reuses citation's Report; only this module's invariants are under test.
    from citation import VerificationReport
    from retrieval import Chunk, ScoredChunk

    chunk = ScoredChunk(
        chunk=Chunk(
            block_id="ai-x",
            relpath="n.md",
            kind="para",
            text="t",
            line_start=1,
            line_end=1,
            frontmatter={},
            embedding=None,
        ),
        score=0.9,
    )
    report = Report.model_validate(
        {
            "title": "T",
            "summary": "S",
            "sections": [
                {
                    "heading": "H",
                    "claims": [{"text": "c.", "quote": "t", "block_id": "ai-x"}],
                }
            ],
        }
    )
    sr = SubReport(
        sub_query=SubQuery(text="q", rationale="r"),
        chunks=[chunk],
        report=report,
        verification=VerificationReport(total_claims=1, failures=[]),
        attempts=1,
    )
    assert sr.attempts == 1
    assert sr.verification.pass_rate == 1.0
    assert sr.chunks[0].chunk.block_id == "ai-x"
