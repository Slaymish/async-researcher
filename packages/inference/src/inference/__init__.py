"""OpenAI-compatible inference adapter. ADR-0009, ADR-0014."""

from .client import InferenceClient, InferenceConfig
from .routing import InferenceTask, model_for_task
from .types import Message

__all__ = [
    "InferenceClient",
    "InferenceConfig",
    "InferenceTask",
    "Message",
    "model_for_task",
]
