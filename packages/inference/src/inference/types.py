"""Shared types for the inference adapter."""

from __future__ import annotations

from typing import Literal, TypedDict


class Message(TypedDict):
    role: Literal["system", "user", "assistant"]
    content: str
