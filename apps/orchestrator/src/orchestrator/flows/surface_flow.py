"""Proactive surfacing flow.

v0.1 is deliberately dumb: embed the active note content as the query, retrieve
related blocks, and exclude blocks from the active file. No synthesis, no
contradiction detection, no temporal reasoning.
"""

from __future__ import annotations

from dataclasses import dataclass

from retrieval import Retriever, ScoredChunk

# Local embedders cap context around 2048 tokens (~8k chars). Embedding the
# whole note as one query 400s on long notes — the inference adapter
# downgrades that to a None vector and we return no results, which is a bad
# UX for the user's longest, most-worth-surfacing notes. Truncate to a safe
# budget so the query always fits. Leaving margin (6k chars ≈ 1500 tokens)
# for tokenisers that are more aggressive than chars/4.
_MAX_QUERY_CHARS = 6000


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
    if len(query) > _MAX_QUERY_CHARS:
        # Keep the leading slice — for notes the opening (title, frontmatter,
        # intro paragraph) carries most of the topical signal.
        query = query[:_MAX_QUERY_CHARS]

    # Ask for extra candidates because same-file chunks are discarded below.
    candidates = await retriever.retrieve(query, k=max(k * 3, k + 5))
    results = [sc for sc in candidates if sc.chunk.relpath != relpath][:k]
    return SurfaceResult(relpath=relpath, results=results, k=k)
