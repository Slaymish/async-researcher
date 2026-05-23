"""Proactive surfacing flow.

v0.1 is deliberately dumb: embed the active note content as the query, retrieve
related blocks, and exclude blocks from the active file. No synthesis, no
contradiction detection, no temporal reasoning.
"""

from __future__ import annotations

from dataclasses import dataclass

from retrieval import Retriever, ScoredChunk


@dataclass(frozen=True)
class SurfaceResult:
    relpath: str
    results: list[ScoredChunk]
    k: int


async def surface(
    *,
    relpath: str,
    content: str,
    retriever: Retriever,
    k: int = 8,
) -> SurfaceResult:
    """Return top related chunks from other files for the active note.

    The plugin also filters self-references defensively, but the backend owns the
    contract so non-plugin clients get the same behaviour.
    """
    query = content.strip()
    if not query:
        return SurfaceResult(relpath=relpath, results=[], k=k)

    # Ask for extra candidates because same-file chunks are discarded below.
    candidates = await retriever.retrieve(query, k=max(k * 3, k + 5))
    results = [sc for sc in candidates if sc.chunk.relpath != relpath][:k]
    return SurfaceResult(relpath=relpath, results=results, k=k)
