"""Public types returned by the Memory adapter.

Kept separate from `adapter.py` so consumers can `from memory import Fact`
without importing the heavy mem0ai stack just to type a list.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any


@dataclass(frozen=True)
class Fact:
    """One memory record returned by `Memory.recall()`.

    Mirrors the shape mem0ai returns from `memory.search()` after we strip
    the SDK-specific fields. Callers should treat this as opaque except for
    `id`, `text`, `score`, and `created_at` — which are the fields the
    Planner prompt actually formats into its MEMORY block.
    """

    id: str
    text: str
    score: float
    created_at: datetime | None = None
    metadata: dict[str, Any] = field(default_factory=dict)
