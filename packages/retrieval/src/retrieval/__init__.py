"""Hybrid retrieval — LightRAG graph + DuckDB vector. See ADR-0011, ADR-0012."""

from .graph import GraphRetriever, NullGraphRetriever
from .hybrid import Retriever, cosine_to_relevance
from .types import Chunk, FileSig, ScoredChunk
from .vector import DuckDBStore, EmbeddingDimensionMismatch

__all__ = [
    "Chunk",
    "DuckDBStore",
    "EmbeddingDimensionMismatch",
    "FileSig",
    "GraphRetriever",
    "NullGraphRetriever",
    "Retriever",
    "ScoredChunk",
    "cosine_to_relevance",
]
