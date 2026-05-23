from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from orchestrator.flows.surface_flow import surface
from orchestrator.routes.surface import router
from retrieval import Chunk, DuckDBStore, ScoredChunk


class FakeRetriever:
    def __init__(self, results: list[ScoredChunk]) -> None:
        self.results = results
        self.calls: list[tuple[str, int]] = []

    async def retrieve(self, query: str, k: int = 20, **_kwargs):
        self.calls.append((query, k))
        return self.results[:k]


class FakeEmbedder:
    async def embed(self, texts, *, model=None):
        return [[1.0, 0.0] for _ in texts]


def _scored(block_id: str, relpath: str, score: float) -> ScoredChunk:
    return ScoredChunk(
        chunk=Chunk(
            block_id=block_id,
            relpath=relpath,
            kind="para",
            text=f"text for {block_id}",
            line_start=1,
            line_end=1,
            frontmatter={},
            embedding=None,
        ),
        score=score,
    )


@pytest.mark.asyncio
async def test_surface_filters_active_file_and_preserves_order(tmp_path: Path):
    store = DuckDBStore(tmp_path / "index.duckdb", embedding_dim=2)
    retriever = FakeRetriever(
        [
            _scored("self", "active.md", 0.99),
            _scored("other-a", "a.md", 0.90),
            _scored("other-b", "b.md", 0.80),
        ]
    )

    result = await surface(
        relpath="active.md",
        content="  current note text  ",
        retriever=retriever,
        k=1,
    )

    assert retriever.calls == [("current note text", 6)]
    assert [sc.chunk.block_id for sc in result.results] == ["other-a"]
    store.close()


@pytest.mark.asyncio
async def test_surface_empty_content_skips_retrieval(tmp_path: Path):
    store = DuckDBStore(tmp_path / "index.duckdb", embedding_dim=2)
    retriever = FakeRetriever([_scored("other", "a.md", 1.0)])

    result = await surface(
        relpath="active.md",
        content="   ",
        retriever=retriever,
        k=5,
    )

    assert result.results == []
    assert retriever.calls == []
    store.close()


def test_surface_route_returns_plugin_contract(tmp_path: Path):
    store = DuckDBStore(tmp_path / "index.duckdb", embedding_dim=2)
    store.upsert_chunks(
        [
            Chunk("self", "active.md", "para", "active text", 1, 1, {}, [1.0, 0.0]),
            Chunk("other", "other.md", "para", "related text", 1, 1, {}, [1.0, 0.0]),
        ]
    )
    app = FastAPI()
    app.state.store = store
    app.state.client = FakeEmbedder()
    app.include_router(router)

    response = TestClient(app).post(
        "/surface",
        json={"relpath": "active.md", "content": "active text", "k": 5},
    )

    assert response.status_code == 200
    payload = response.json()
    assert len(payload["results"]) == 1
    assert payload["results"][0] == {
        "relpath": "other.md",
        "block_id": "other",
        "kind": "para",
        "text": "related text",
        "score": payload["results"][0]["score"],
    }
    assert payload["results"][0]["score"] > 0
    store.close()
