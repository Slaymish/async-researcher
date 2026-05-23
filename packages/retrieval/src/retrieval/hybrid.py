"""retrieve(query, k) — fuses graph + vector results, preserves ^id (ADR-0011, 0012).

Vector, local lexical, and optional graph rankings are merged via Reciprocal Rank
Fusion (RRF), keeping `block_id` as the deduplication key.
"""

from __future__ import annotations

from typing import Protocol

from .graph import GraphRetriever
from .types import ScoredChunk
from .vector import DuckDBStore


class _Embedder(Protocol):
    async def embed(
        self, texts: list[str], *, model: str | None = ...
    ) -> list[list[float] | None]: ...


class Retriever:
    """Single entry point for vault retrieval.

    Embeds the query through the inference adapter, cosine-searches DuckDB, and
    optionally fuses graph results. Callers must not strip `^id`s from results
    (ADR-0012).
    """

    def __init__(
        self,
        store: DuckDBStore,
        embedder: _Embedder,
        *,
        graph: GraphRetriever | None = None,
        rrf_k: int = 60,
    ) -> None:
        self._store = store
        self._embedder = embedder
        self._graph = graph
        self._rrf_k = rrf_k

    async def retrieve(
        self,
        query: str,
        k: int = 20,
        *,
        relpath_prefix: str | None = None,
        kinds: list[str] | None = None,
    ) -> list[ScoredChunk]:
        if not query.strip():
            return []
        [vec] = await self._embedder.embed([query])
        if vec is None:
            # Query too long for the embedding model. Caller can fall back; we don't
            # have a lexical index in v0.1.
            return []
        candidate_count = _candidate_count(k)
        vector_results = self._store.search(
            vec,
            k=candidate_count,
            relpath_prefix=relpath_prefix,
            kinds=kinds,
        )
        lexical_results = self._store.keyword_search(
            query,
            k=candidate_count,
            relpath_prefix=relpath_prefix,
            kinds=kinds,
        )
        graph_results: list[ScoredChunk] = []
        if self._graph is not None:
            graph_results = await self._graph.query(query, k=candidate_count)
            graph_results = _filter_results(
                graph_results,
                relpath_prefix=relpath_prefix,
                kinds=kinds,
            )
        return _rrf_fuse(
            result_sets=[vector_results, lexical_results, graph_results],
            k=k,
            rank_constant=self._rrf_k,
        )


def _candidate_count(k: int) -> int:
    return max(k * 3, k + 10)


def _filter_results(
    results: list[ScoredChunk],
    *,
    relpath_prefix: str | None,
    kinds: list[str] | None,
) -> list[ScoredChunk]:
    out = results
    if relpath_prefix is not None:
        out = [sc for sc in out if sc.chunk.relpath.startswith(relpath_prefix)]
    if kinds:
        allowed = set(kinds)
        out = [sc for sc in out if sc.chunk.kind in allowed]
    return out


def _rrf_fuse(
    *,
    result_sets: list[list[ScoredChunk]],
    k: int,
    rank_constant: int,
) -> list[ScoredChunk]:
    by_id: dict[str, ScoredChunk] = {}
    scores: dict[str, float] = {}

    def add(results: list[ScoredChunk]) -> None:
        for rank, scored in enumerate(results, 1):
            block_id = scored.chunk.block_id
            by_id.setdefault(block_id, scored)
            scores[block_id] = scores.get(block_id, 0.0) + 1.0 / (rank_constant + rank)

    for results in result_sets:
        add(results)

    fused = [
        ScoredChunk(chunk=by_id[block_id].chunk, score=score)
        for block_id, score in scores.items()
    ]
    return sorted(fused, key=lambda sc: sc.score, reverse=True)[:k]
