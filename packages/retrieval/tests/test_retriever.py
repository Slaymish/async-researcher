from pathlib import Path

import pytest
from retrieval import Chunk, DuckDBStore, Retriever, ScoredChunk


class FakeEmbedder:
    def __init__(self, vectors: dict[str, list[float] | None]) -> None:
        self.vectors = vectors
        self.calls: list[str] = []

    async def embed(self, texts, *, model=None):
        out: list[list[float] | None] = []
        for t in texts:
            self.calls.append(t)
            out.append(self.vectors.get(t))
        return out


class FakeGraph:
    def __init__(self, results: list[ScoredChunk]) -> None:
        self.results = results
        self.calls: list[tuple[str, int]] = []

    async def query(self, query: str, k: int = 20) -> list[ScoredChunk]:
        self.calls.append((query, k))
        return self.results[:k]


def _seed(store: DuckDBStore) -> None:
    store.upsert_chunks(
        [
            Chunk("ai-a", "a.md", "para", "alpha", 0, 1, {}, [1.0, 0.0, 0.0, 0.0]),
            Chunk("ai-b", "b.md", "para", "beta", 0, 1, {}, [0.0, 1.0, 0.0, 0.0]),
        ]
    )


def _scored(block_id: str, relpath: str, score: float) -> ScoredChunk:
    return ScoredChunk(
        chunk=Chunk(block_id, relpath, "para", block_id, 0, 1, {}, None),
        score=score,
    )


@pytest.mark.asyncio
async def test_retrieve_embeds_query_and_returns_top_k(tmp_path: Path):
    store = DuckDBStore(tmp_path / "i.duckdb", embedding_dim=4)
    _seed(store)
    embedder = FakeEmbedder({"hello": [1.0, 0.0, 0.0, 0.0]})
    r = Retriever(store, embedder)
    out = await r.retrieve("hello", k=2)
    assert embedder.calls == ["hello"]
    assert [s.chunk.block_id for s in out] == ["ai-a", "ai-b"]
    store.close()


@pytest.mark.asyncio
async def test_retrieve_empty_query_returns_nothing(tmp_path: Path):
    store = DuckDBStore(tmp_path / "i.duckdb", embedding_dim=4)
    _seed(store)
    r = Retriever(store, FakeEmbedder({}))
    assert await r.retrieve("   ", k=5) == []
    store.close()


@pytest.mark.asyncio
async def test_retrieve_oversized_query_returns_nothing(tmp_path: Path):
    store = DuckDBStore(tmp_path / "i.duckdb", embedding_dim=4)
    _seed(store)
    # Embedder returns None for "huge" → caller would otherwise crash without graceful
    # handling; retriever should just return [].
    r = Retriever(store, FakeEmbedder({"huge": None}))
    assert await r.retrieve("huge", k=5) == []
    store.close()


@pytest.mark.asyncio
async def test_retrieve_fuses_vector_and_graph_results(tmp_path: Path):
    store = DuckDBStore(tmp_path / "i.duckdb", embedding_dim=4)
    _seed(store)
    graph = FakeGraph([_scored("ai-b", "b.md", 1.0), _scored("ai-c", "c.md", 0.9)])
    r = Retriever(
        store,
        FakeEmbedder({"hello": [1.0, 0.0, 0.0, 0.0]}),
        graph=graph,
    )

    out = await r.retrieve("hello", k=3)

    assert graph.calls == [("hello", 13)]
    # ai-b appears in both rankings, so RRF promotes it above vector-only ai-a.
    assert [s.chunk.block_id for s in out] == ["ai-b", "ai-a", "ai-c"]
    assert all(s.score > 0 for s in out)
    store.close()


@pytest.mark.asyncio
async def test_retrieve_filters_graph_results_with_same_filters_as_vector(tmp_path: Path):
    store = DuckDBStore(tmp_path / "i.duckdb", embedding_dim=4)
    _seed(store)
    graph = FakeGraph(
        [
            _scored("ai-graph-a", "notes/a.md", 1.0),
            _scored("ai-graph-b", "archive/b.md", 0.9),
        ]
    )
    r = Retriever(
        store,
        FakeEmbedder({"hello": [1.0, 0.0, 0.0, 0.0]}),
        graph=graph,
    )

    out = await r.retrieve("hello", k=5, relpath_prefix="notes/")

    assert [s.chunk.block_id for s in out] == ["ai-graph-a"]
    store.close()
