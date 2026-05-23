"""Planner unit tests (v0.2.2 step 3).

Stub-based — confirms the Planner uses the synthesis model (default), passes
the user query through to the prompt, and respects the PLANNER_FANOUT_CAP
constraint at the Pydantic layer.
"""

from __future__ import annotations

import pytest
from inference import InferenceConfig
from orchestrator.flows.roma import PLANNER_FANOUT_CAP, Plan, SubQuery, plan
from pydantic import ValidationError


class _StubClient:
    def __init__(self, plan_obj: Plan, config: InferenceConfig) -> None:
        self._plan = plan_obj
        self.config = config
        self.last_model: str | None = None
        self.last_messages: list | None = None

    async def complete(self, messages, *, response_model, model=None, **_kwargs):
        assert response_model is Plan
        self.last_model = model
        self.last_messages = messages
        return self._plan


def _config() -> InferenceConfig:
    return InferenceConfig(
        base_url="http://localhost:11434/v1",
        api_key="x",
        synthesis_model="big-model",
        embedding_model="embed-model",
        judge_model="small-model",
    )


@pytest.mark.asyncio
async def test_plan_targets_synthesis_model_by_default():
    fixed = Plan(sub_queries=[SubQuery(text="q1", rationale="cover topic A")])
    client = _StubClient(fixed, _config())

    out = await plan("multi-topic spec", client)  # type: ignore[arg-type]

    assert out == fixed
    # `model=None` → adapter falls back to InferenceTask.SYNTHESIS, so we
    # verify the planner did NOT override the model explicitly.
    assert client.last_model is None


@pytest.mark.asyncio
async def test_plan_includes_query_and_schema_in_prompt():
    fixed = Plan(sub_queries=[SubQuery(text="q", rationale="r")])
    client = _StubClient(fixed, _config())

    await plan("What did I write about LangGraph?", client)  # type: ignore[arg-type]

    assert client.last_messages is not None
    user_msg = client.last_messages[-1]
    assert "What did I write about LangGraph?" in user_msg["content"]
    # The schema is embedded in the prompt so the model knows the wire format.
    assert "sub_queries" in user_msg["content"]


@pytest.mark.asyncio
async def test_plan_respects_per_run_max_sub_queries():
    fixed = Plan(
        sub_queries=[
            SubQuery(text="q1", rationale="r1"),
            SubQuery(text="q2", rationale="r2"),
            SubQuery(text="q3", rationale="r3"),
        ]
    )
    client = _StubClient(fixed, _config())

    out = await plan("multi-topic spec", client, max_sub_queries=2)  # type: ignore[arg-type]

    assert [sq.text for sq in out.sub_queries] == ["q1", "q2"]
    assert client.last_messages is not None
    assert "Use at most 2 sub-queries" in client.last_messages[-1]["content"]


def test_plan_schema_enforces_fanout_cap():
    too_many = [{"text": f"q{i}", "rationale": "r"} for i in range(PLANNER_FANOUT_CAP + 1)]
    # Pydantic, not the planner function, is the enforcement — but the test
    # exists to lock the contract: if PLANNER_FANOUT_CAP changes, this fails
    # loudly until you've thought about the latency budget (Risk R2).
    with pytest.raises(ValidationError):
        Plan.model_validate({"sub_queries": too_many})
