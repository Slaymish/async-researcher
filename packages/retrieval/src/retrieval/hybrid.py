"""retrieve(query, k) — fuses graph + vector results, preserves ^id (ADR-0011, 0012).

Vector, local lexical, and optional graph rankings are merged via Reciprocal Rank
Fusion (RRF), keeping `block_id` as the deduplication key.

The final `ScoredChunk.score` on `Retriever.retrieve()` output is **cosine similarity
against the query** (in [-1, 1]; ~1 = identical, ~0.45 = unrelated for typical local
embedders), NOT the RRF rank score. RRF is used internally for ordering only.
This is what callers want to display to users — RRF scores cap at tiny values
(~0.05) by construction and are meaningless as "similarity %".
"""

from __future__ import annotations

import math
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
        fused = _rrf_fuse(
            result_sets=[vector_results, lexical_results, graph_results],
            k=k,
            rank_constant=self._rrf_k,
        )
        # Replace RRF rank scores with cosine similarity against the query so
        # downstream UI sees a meaningful number. Order is preserved.
        return _attach_cosine_scores(
            fused,
            query_vec=vec,
            vector_results=vector_results,
            store=self._store,
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


def _attach_cosine_scores(
    results: list[ScoredChunk],
    *,
    query_vec: list[float],
    vector_results: list[ScoredChunk],
    store: DuckDBStore,
) -> list[ScoredChunk]:
    """Replace each chunk's RRF score with cosine similarity vs the query.

    Vector hits already carry cosine in `.score` (computed in SQL); reuse those.
    Lexical-only / graph-only hits need a one-shot embedding lookup.
    """
    if not results:
        return results
    cosine_by_id = {sc.chunk.block_id: sc.score for sc in vector_results}
    missing = [sc.chunk.block_id for sc in results if sc.chunk.block_id not in cosine_by_id]
    if missing:
        embeddings = store.get_embeddings_by_ids(missing)
        for bid, emb in embeddings.items():
            cosine_by_id[bid] = _cosine(query_vec, emb) if emb is not None else 0.0
    return [
        ScoredChunk(chunk=sc.chunk, score=cosine_by_id.get(sc.chunk.block_id, 0.0))
        for sc in results
    ]


def _cosine(a: list[float], b: list[float]) -> float:
    """Plain cosine similarity. Used only on retrieval result sets (<= a few
    hundred chunks); not a bottleneck."""
    dot = 0.0
    na = 0.0
    nb = 0.0
    for x, y in zip(a, b, strict=True):
        dot += x * y
        na += x * x
        nb += y * y
    if na == 0.0 or nb == 0.0:
        return 0.0
    return dot / math.sqrt(na * nb)


def cosine_to_relevance(cos: float, *, floor: float = 0.30, ceiling: float = 1.0) -> float:
    """Rescale raw cosine similarity into a [0, 1] "relevance" score for display.

    Local embedders (nomic-embed-text, etc.) cluster all text in a baseline
    similarity band (~0.30–0.50 even for unrelated content). Raw cosine of
    0.69 for "pretty similar" text is correct but reads as 69% — and 0.45
    for "totally unrelated" reads as a misleading 45%. We clamp the bottom
    band to 0% and stretch the upper band so:

      cosine 1.00 → 100%  (identical)
      cosine 0.69 →  56%  ("pretty similar")
      cosine 0.45 →  21%  ("unrelated")
      cosine 0.30 →   0%  (baseline noise)

    Tuned for nomic-embed-text against typical natural-language queries.
    """
    if cos <= floor:
        return 0.0
    if cos >= ceiling:
        return 1.0
    return (cos - floor) / (ceiling - floor)


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
