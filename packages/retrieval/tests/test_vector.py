from pathlib import Path

import pytest
from retrieval import Chunk, DuckDBStore, EmbeddingDimensionMismatch, FileSig


def _store(tmp_path: Path, dim: int = 4) -> DuckDBStore:
    return DuckDBStore(tmp_path / "index.duckdb", embedding_dim=dim)


def test_migration_is_idempotent(tmp_path: Path):
    s1 = _store(tmp_path)
    s1.close()
    s2 = _store(tmp_path)
    assert s2.chunk_count() == 0
    s2.close()


def test_embedding_dim_mismatch_raises(tmp_path: Path):
    s = _store(tmp_path, dim=4)
    s.close()
    with pytest.raises(EmbeddingDimensionMismatch):
        DuckDBStore(tmp_path / "index.duckdb", embedding_dim=8)


def test_read_only_connection_allows_concurrent_readers(tmp_path: Path):
    s = _store(tmp_path)
    s.upsert_chunks(
        [Chunk("ai-a", "a.md", "para", "x", 0, 1, {}, [1.0, 0.0, 0.0, 0.0])]
    )
    s.close()
    reader_a = DuckDBStore(tmp_path / "index.duckdb", embedding_dim=4, read_only=True)
    reader_b = DuckDBStore(tmp_path / "index.duckdb", embedding_dim=4, read_only=True)

    assert reader_a.chunk_count() == 1
    assert reader_b.file_count() == 0

    reader_b.close()
    reader_a.close()


def test_upsert_and_delete_roundtrip(tmp_path: Path):
    s = _store(tmp_path)
    chunks = [
        Chunk(
            block_id="ai-aaaa1111",
            relpath="a.md",
            kind="para",
            text="hello",
            line_start=0,
            line_end=1,
            frontmatter={"tag": "x"},
            embedding=[0.1, 0.2, 0.3, 0.4],
        ),
        Chunk(
            block_id="ai-bbbb2222",
            relpath="a.md",
            kind="para",
            text="world",
            line_start=2,
            line_end=3,
            frontmatter={"tag": "x"},
            embedding=[0.5, 0.6, 0.7, 0.8],
        ),
    ]
    assert s.upsert_chunks(chunks) == 2
    assert s.chunk_count() == 2
    s.delete_file("a.md")
    assert s.chunk_count() == 0
    s.close()


def test_upsert_replaces_existing_relpath_rows(tmp_path: Path):
    s = _store(tmp_path)
    first = [
        Chunk("ai-1", "a.md", "para", "x", 0, 1, {}, [0.0, 0.0, 0.0, 0.0]),
        Chunk("ai-2", "a.md", "para", "y", 1, 2, {}, [0.0, 0.0, 0.0, 0.0]),
    ]
    s.upsert_chunks(first)
    second = [Chunk("ai-3", "a.md", "para", "z", 0, 1, {}, [0.0, 0.0, 0.0, 0.0])]
    s.upsert_chunks(second)
    assert s.chunk_count() == 1
    s.close()


def test_search_returns_top_k_by_cosine_similarity(tmp_path: Path):
    s = _store(tmp_path, dim=4)
    # Three chunks at known positions on the unit circle (x,y,0,0).
    s.upsert_chunks(
        [
            Chunk("ai-east", "a.md", "para", "east", 0, 1, {}, [1.0, 0.0, 0.0, 0.0]),
            Chunk("ai-north", "b.md", "para", "north", 0, 1, {}, [0.0, 1.0, 0.0, 0.0]),
            Chunk("ai-west", "c.md", "para", "west", 0, 1, {}, [-1.0, 0.0, 0.0, 0.0]),
        ]
    )
    # Query "east": expect east > north > west.
    out = s.search([1.0, 0.0, 0.0, 0.0], k=3)
    assert [r.chunk.block_id for r in out] == ["ai-east", "ai-north", "ai-west"]
    assert out[0].score > out[1].score > out[2].score
    s.close()


def test_search_excludes_null_embeddings(tmp_path: Path):
    s = _store(tmp_path, dim=4)
    s.upsert_chunks(
        [
            Chunk("ai-vec", "a.md", "para", "x", 0, 1, {}, [1.0, 0.0, 0.0, 0.0]),
            Chunk("ai-null", "b.md", "para", "y", 0, 1, {}, None),
        ]
    )
    out = s.search([1.0, 0.0, 0.0, 0.0], k=10)
    assert [r.chunk.block_id for r in out] == ["ai-vec"]
    s.close()


def test_search_respects_relpath_prefix_filter(tmp_path: Path):
    s = _store(tmp_path, dim=4)
    s.upsert_chunks(
        [
            Chunk("ai-a", "notes/a.md", "para", "x", 0, 1, {}, [1.0, 0.0, 0.0, 0.0]),
            Chunk("ai-b", "clippings/b.md", "para", "y", 0, 1, {}, [1.0, 0.0, 0.0, 0.0]),
        ]
    )
    out = s.search([1.0, 0.0, 0.0, 0.0], k=10, relpath_prefix="notes/")
    assert [r.chunk.block_id for r in out] == ["ai-a"]
    s.close()


def test_search_respects_kinds_filter(tmp_path: Path):
    s = _store(tmp_path, dim=4)
    s.upsert_chunks(
        [
            Chunk("ai-h", "a.md", "heading", "#", 0, 1, {}, [1.0, 0.0, 0.0, 0.0]),
            Chunk("ai-p", "a.md", "para", "x", 0, 1, {}, [1.0, 0.0, 0.0, 0.0]),
        ]
    )
    out = s.search([1.0, 0.0, 0.0, 0.0], k=10, kinds=["heading"])
    assert [r.chunk.block_id for r in out] == ["ai-h"]
    s.close()


def test_keyword_search_finds_identifier_tokens(tmp_path: Path):
    s = _store(tmp_path)
    s.upsert_chunks(
        [
            Chunk(
                "ai-api",
                "API Performance Testing.md",
                "code",
                "Server-Timing parse with correlationId and perf.now()",
                0,
                1,
                {},
                [0.0, 0.0, 0.0, 0.0],
            ),
            Chunk(
                "ai-other",
                "Other.md",
                "para",
                "General performance notes without the specific headers.",
                0,
                1,
                {},
                [0.0, 0.0, 0.0, 0.0],
            ),
        ]
    )

    out = s.keyword_search("Server-Timing correlationId", k=2)

    assert [r.chunk.block_id for r in out] == ["ai-api"]
    assert out[0].score > 0
    s.close()


def test_keyword_search_respects_filters(tmp_path: Path):
    s = _store(tmp_path)
    s.upsert_chunks(
        [
            Chunk("ai-a", "notes/a.md", "para", "apiKey token", 0, 1, {}, [0, 0, 0, 0]),
            Chunk("ai-b", "code/b.md", "code", "apiKey token", 0, 1, {}, [0, 0, 0, 0]),
        ]
    )

    out = s.keyword_search("apiKey", k=5, relpath_prefix="code/", kinds=["code"])

    assert [r.chunk.block_id for r in out] == ["ai-b"]
    s.close()


def test_get_chunks_by_ids_returns_dict(tmp_path: Path):
    s = _store(tmp_path)
    s.upsert_chunks(
        [
            Chunk("ai-a", "x.md", "para", "alpha", 0, 1, {}, [0.0, 0.0, 0.0, 0.0]),
            Chunk("ai-b", "x.md", "para", "beta", 1, 2, {}, [0.0, 0.0, 0.0, 0.0]),
        ]
    )
    out = s.get_chunks_by_ids(["ai-a", "ai-missing"])
    assert set(out.keys()) == {"ai-a"}
    assert out["ai-a"].text == "alpha"
    assert s.get_chunks_by_ids([]) == {}
    s.close()


def test_search_dim_mismatch_raises(tmp_path: Path):
    s = _store(tmp_path, dim=4)
    with pytest.raises(ValueError):
        s.search([1.0, 0.0], k=1)
    s.close()


def test_file_signature_roundtrip(tmp_path: Path):
    s = _store(tmp_path)
    assert s.get_file_signature("a.md") is None
    sig = FileSig(relpath="a.md", size=100, mtime_ns=12345, content_hash="abc")
    s.set_file_signature(sig)
    got = s.get_file_signature("a.md")
    assert got == sig
    # Update
    sig2 = FileSig(relpath="a.md", size=200, mtime_ns=67890, content_hash="def")
    s.set_file_signature(sig2)
    assert s.get_file_signature("a.md") == sig2
    s.close()
