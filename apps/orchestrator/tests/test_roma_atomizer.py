"""Atomizer unit tests (v0.2.2 step 2).

The Atomizer is an LLM call (judge model, per sign-off #5). These tests
stub the inference client so they don't need a live model — they pin:
  - the call targets the judge model, not the synthesis model
  - the verdict is what comes back unchanged
  - the override resolver behaves correctly across "auto"/True/False
"""

from __future__ import annotations

import pytest
from inference import InferenceConfig
from orchestrator.flows.roma import AtomizerVerdict, atomize, resolve_decompose


class _StubClient:
    """Captures model + messages from each complete() call; returns a queued verdict."""

    def __init__(self, verdict: AtomizerVerdict, config: InferenceConfig) -> None:
        self._verdict = verdict
        self.config = config
        self.last_model: str | None = None
        self.last_messages: list | None = None

    async def complete(self, messages, *, response_model, model=None, **_kwargs):
        assert response_model is AtomizerVerdict
        self.last_model = model
        self.last_messages = messages
        return self._verdict


def _config() -> InferenceConfig:
    return InferenceConfig(
        base_url="http://localhost:11434/v1",
        api_key="x",
        synthesis_model="big-model",
        embedding_model="embed-model",
        judge_model="small-model",
    )


@pytest.mark.asyncio
async def test_atomize_targets_judge_model_not_synthesis():
    verdict = AtomizerVerdict(decompose=True, rationale="multi-topic")
    client = _StubClient(verdict, _config())

    out = await atomize("Some long spec question.", client)  # type: ignore[arg-type]

    assert out == verdict
    # Sign-off #5: Atomizer runs on the judge model, not the synthesis model.
    assert client.last_model == "small-model"


@pytest.mark.asyncio
async def test_atomize_prompts_include_the_query():
    verdict = AtomizerVerdict(decompose=False, rationale="atomic")
    client = _StubClient(verdict, _config())

    await atomize("How do I configure ingest?", client)  # type: ignore[arg-type]

    assert client.last_messages is not None
    user_msg = client.last_messages[-1]
    assert user_msg["role"] == "user"
    assert "How do I configure ingest?" in user_msg["content"]


def test_resolve_decompose_auto_returns_verdict_value():
    v = AtomizerVerdict(decompose=True, rationale="multi")
    assert resolve_decompose("auto", v) is True
    v_no = AtomizerVerdict(decompose=False, rationale="atomic")
    assert resolve_decompose("auto", v_no) is False


def test_resolve_decompose_bool_overrides_verdict():
    v = AtomizerVerdict(decompose=True, rationale="multi")
    # User-forced atomic: trumps the Atomizer's "decompose=True" verdict.
    assert resolve_decompose(False, v) is False
    # User-forced decompose: trumps the Atomizer's "atomic" verdict.
    v_no = AtomizerVerdict(decompose=False, rationale="atomic")
    assert resolve_decompose(True, v_no) is True


def test_resolve_decompose_bool_does_not_require_verdict():
    assert resolve_decompose(False, None) is False
    assert resolve_decompose(True, None) is True


def test_resolve_decompose_auto_without_verdict_is_an_error():
    with pytest.raises(ValueError, match="Atomizer"):
        resolve_decompose("auto", None)
