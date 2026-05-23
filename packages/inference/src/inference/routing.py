"""Model-per-task selection from config.

This is intentionally small in v0.1: ADR-0009 gives us one inference adapter and
the config has three named model slots. Phase 7 can replace this with llama-swap
policies without changing callers.
"""

from __future__ import annotations

from enum import StrEnum
from typing import Protocol


class InferenceConfigLike(Protocol):
    embedding_model: str
    synthesis_model: str
    judge_model: str


class InferenceTask(StrEnum):
    EMBEDDING = "embedding"
    SYNTHESIS = "synthesis"
    JUDGE = "judge"


def model_for_task(config: InferenceConfigLike, task: InferenceTask | str) -> str:
    """Return the configured model name for a task."""
    task = InferenceTask(task)
    match task:
        case InferenceTask.EMBEDDING:
            return config.embedding_model
        case InferenceTask.SYNTHESIS:
            return config.synthesis_model
        case InferenceTask.JUDGE:
            return config.judge_model
