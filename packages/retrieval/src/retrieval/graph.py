"""Graph retrieval adapter interface.

LightRAG is the intended concrete backend for v0.1 (ADR-0011), but the rest of
the codebase should only know about this tiny interface: graph retrieval returns
the same `ScoredChunk` shape as vector retrieval, with `block_id` preserved.
"""

from __future__ import annotations

from typing import Protocol

from .types import ScoredChunk


class GraphRetriever(Protocol):
    async def query(self, query: str, k: int = 20) -> list[ScoredChunk]:
        """Return graph-ranked chunks for a natural-language query."""


class NullGraphRetriever:
    """No-op graph adapter used until LightRAG is configured."""

    async def query(self, query: str, k: int = 20) -> list[ScoredChunk]:
        _ = (query, k)
        return []
