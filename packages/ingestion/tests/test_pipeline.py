from pathlib import Path

import pytest
from ingestion import ingest
from retrieval import DuckDBStore


class FakeEmbedder:
    def __init__(self) -> None:
        self.calls: list[list[str]] = []

    async def embed(self, texts, *, model=None):
        self.calls.append(list(texts))
        return [[float(len(t)), 0.0, 0.0, 0.0] for t in texts]


def _vault_with_notes(root: Path) -> None:
    (root / "a.md").write_text("# A\n\nfirst para.\n\nsecond para.\n")
    (root / "b.md").write_text("# B\n\n- item one\n- item two\n")
    sub = root / "sub"
    sub.mkdir()
    (sub / "c.md").write_text("plain paragraph.\n")


@pytest.mark.asyncio
async def test_initial_ingest_indexes_all_blocks(tmp_path: Path):
    vault = tmp_path / "vault"
    vault.mkdir()
    _vault_with_notes(vault)
    store = DuckDBStore(tmp_path / "index.duckdb", embedding_dim=4)
    embedder = FakeEmbedder()
    try:
        rep = await ingest(vault, store, embedder)
        assert rep.scanned == 3
        assert rep.changed == 3
        assert rep.written == 3  # all three notes had no ids → all rewritten
        assert rep.indexed > 0
        assert store.chunk_count() == rep.indexed
        assert embedder.calls, "embedder should have been called"
    finally:
        store.close()


@pytest.mark.asyncio
async def test_rerun_unchanged_vault_is_noop(tmp_path: Path):
    vault = tmp_path / "vault"
    vault.mkdir()
    _vault_with_notes(vault)
    store = DuckDBStore(tmp_path / "index.duckdb", embedding_dim=4)
    embedder = FakeEmbedder()
    try:
        await ingest(vault, store, embedder)
        embedder.calls.clear()
        before_count = store.chunk_count()

        rep2 = await ingest(vault, store, embedder)
        assert rep2.scanned == 3
        assert rep2.changed == 0
        assert rep2.written == 0
        assert rep2.indexed == 0
        assert rep2.skipped == 3
        assert store.chunk_count() == before_count
        assert embedder.calls == []
    finally:
        store.close()


@pytest.mark.asyncio
async def test_edit_reindexes_only_changed_file(tmp_path: Path):
    vault = tmp_path / "vault"
    vault.mkdir()
    _vault_with_notes(vault)
    store = DuckDBStore(tmp_path / "index.duckdb", embedding_dim=4)
    embedder = FakeEmbedder()
    try:
        await ingest(vault, store, embedder)
        embedder.calls.clear()

        # Edit one file.
        (vault / "a.md").write_text("# A v2\n\ncompletely new content.\n")

        rep = await ingest(vault, store, embedder)
        assert rep.changed == 1
        # Only the edited file's blocks should have been embedded.
        embedded_texts = [t for call in embedder.calls for t in call]
        assert all("# A v2" in t or "completely new" in t for t in embedded_texts)
    finally:
        store.close()


@pytest.mark.asyncio
async def test_deletion_removes_chunks(tmp_path: Path):
    vault = tmp_path / "vault"
    vault.mkdir()
    _vault_with_notes(vault)
    store = DuckDBStore(tmp_path / "index.duckdb", embedding_dim=4)
    embedder = FakeEmbedder()
    try:
        await ingest(vault, store, embedder)
        (vault / "a.md").unlink()
        rep = await ingest(vault, store, embedder)
        assert rep.deleted == 1
        # No row left for a.md
        rows = store._con.execute(  # noqa: SLF001
            "SELECT COUNT(*) FROM chunks WHERE relpath = ?", ["a.md"]
        ).fetchone()
        assert rows[0] == 0
    finally:
        store.close()


@pytest.mark.asyncio
async def test_dry_run_does_not_write_or_embed(tmp_path: Path):
    vault = tmp_path / "vault"
    vault.mkdir()
    (vault / "a.md").write_text("a paragraph\n")
    store = DuckDBStore(tmp_path / "index.duckdb", embedding_dim=4)
    embedder = FakeEmbedder()
    try:
        original = (vault / "a.md").read_text()
        rep = await ingest(vault, store, embedder, dry_run=True)
        assert rep.scanned == 1
        assert embedder.calls == []
        assert store.chunk_count() == 0
        assert (vault / "a.md").read_text() == original
    finally:
        store.close()
