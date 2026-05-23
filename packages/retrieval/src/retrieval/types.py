"""Cross-package types for retrieval. Carries `^id` per ADR-0012."""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class Chunk:
    block_id: str  # bare id, no leading `^`
    relpath: str
    kind: str
    text: str
    line_start: int
    line_end: int
    frontmatter: dict = field(default_factory=dict)
    embedding: list[float] | None = None


@dataclass(frozen=True)
class ScoredChunk:
    chunk: Chunk
    score: float  # cosine similarity in [-1, 1]; higher is more similar.


@dataclass(frozen=True)
class FileSig:
    relpath: str
    size: int
    mtime_ns: int
    content_hash: str
