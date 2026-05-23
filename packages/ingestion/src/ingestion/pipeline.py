"""Top-level ingestion orchestration.

Two callers:
- `ingest(vault_path, ...)` — one-shot bulk pass. Used by `orchestrator-ingest` and on
  first startup of the dev server.
- `ingest_file(path, ...)` — per-file path used by the watcher on save events.

Idempotence guarantee (success criterion #1, MVP scope §"Success criteria"): if no files
have changed since the last run, this function performs zero writes and zero embedding
calls. The manifest in `DuckDBStore.files` is the source of truth for "has this file
changed".
"""

from __future__ import annotations

import hashlib
import logging
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Protocol

from retrieval import Chunk, DuckDBStore, FileSig

from .id_injector import inject_ids
from .parser import parse_markdown
from .walker import file_signature, iter_vault

log = logging.getLogger(__name__)


class Embedder(Protocol):
    async def embed(
        self, texts: list[str], *, model: str | None = ...
    ) -> list[list[float] | None]: ...


@dataclass
class IngestReport:
    scanned: int = 0
    changed: int = 0
    written: int = 0  # files we wrote `^id`s back into
    indexed: int = 0  # blocks upserted
    skipped: int = 0
    deleted: int = 0
    errors: list[tuple[str, str]] = field(default_factory=list)

    def as_dict(self) -> dict:
        return {
            "scanned": self.scanned,
            "changed": self.changed,
            "written": self.written,
            "indexed": self.indexed,
            "skipped": self.skipped,
            "deleted": self.deleted,
            "errors": self.errors,
        }


def _content_hash(text: str) -> str:
    return hashlib.blake2b(text.encode("utf-8"), digest_size=16).hexdigest()


async def ingest_file(
    path: Path,
    vault_path: Path,
    store: DuckDBStore,
    embedder: Embedder,
    *,
    dry_run: bool = False,
    force: bool = False,
    report: IngestReport | None = None,
) -> IngestReport:
    """Process a single file. Safe to call concurrently for different paths."""
    rep = report or IngestReport()
    rep.scanned += 1
    relpath = path.relative_to(vault_path).as_posix()

    try:
        size, mtime_ns = file_signature(path)
    except FileNotFoundError:
        rep.deleted += 1
        if not dry_run:
            store.delete_file(relpath)
        return rep

    prev = store.get_file_signature(relpath)
    if not force and prev is not None and prev.size == size and prev.mtime_ns == mtime_ns:
        rep.skipped += 1
        return rep

    try:
        original_text = path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError) as e:
        rep.errors.append((relpath, f"read: {e}"))
        return rep

    chash = _content_hash(original_text)
    if not force and prev is not None and prev.content_hash == chash:
        # Touched but not modified (e.g. mtime bump from a backup tool). Refresh the sig
        # so we stop reading this file every run, but don't re-index.
        rep.skipped += 1
        if not dry_run:
            store.set_file_signature(
                FileSig(relpath=relpath, size=size, mtime_ns=mtime_ns, content_hash=chash)
            )
        return rep

    parsed = parse_markdown(original_text)
    reserved = store.block_ids_except(relpath)
    new_text, blocks_with_ids = inject_ids(
        original_text, parsed, relpath, reserved=reserved
    )

    if new_text != original_text:
        if not dry_run:
            path.write_text(new_text, encoding="utf-8")
            # Re-stat: writing the file just changed its mtime/size, and the post-injection
            # content is what we want to remember as "current".
            size, mtime_ns = file_signature(path)
            chash = _content_hash(new_text)
        rep.written += 1

    texts = [b.text for b in blocks_with_ids]
    embeddings = await embedder.embed(texts) if texts and not dry_run else [None] * len(texts)

    chunks = [
        Chunk(
            block_id=b.existing_id or "",  # assign_ids guarantees existing_id is set
            relpath=relpath,
            kind=b.kind,
            text=b.text,
            line_start=b.line_start,
            line_end=b.line_end,
            frontmatter=parsed.frontmatter,
            embedding=emb,
        )
        for b, emb in zip(blocks_with_ids, embeddings, strict=True)
        if b.existing_id  # defensive
    ]

    if not dry_run:
        rep.indexed += store.upsert_chunks(chunks)
        store.set_file_signature(
            FileSig(relpath=relpath, size=size, mtime_ns=mtime_ns, content_hash=chash)
        )
    rep.changed += 1
    return rep


async def ingest(
    vault_path: Path,
    store: DuckDBStore,
    embedder: Embedder,
    *,
    ignore_globs: list[str] | None = None,
    dry_run: bool = False,
    force: bool = False,
    on_progress: Callable[[IngestReport], Awaitable[None]] | None = None,
) -> IngestReport:
    """Bulk one-shot pass over the vault. Files are processed sequentially in v0.1."""
    rep = IngestReport()
    seen_relpaths: set[str] = set()

    for path in iter_vault(vault_path, ignore_globs):
        relpath = path.relative_to(vault_path).as_posix()
        seen_relpaths.add(relpath)
        await ingest_file(
            path,
            vault_path,
            store,
            embedder,
            dry_run=dry_run,
            force=force,
            report=rep,
        )
        if on_progress is not None:
            await on_progress(rep)

    # Detect deletions: files in the manifest no longer present on disk.
    if not dry_run:
        for sig_relpath in _all_manifest_relpaths(store):
            if sig_relpath not in seen_relpaths:
                if (vault_path / sig_relpath).exists():
                    continue
                store.delete_file(sig_relpath)
                rep.deleted += 1

    return rep


def _all_manifest_relpaths(store: DuckDBStore) -> list[str]:
    rows = store._con.execute("SELECT relpath FROM files").fetchall()  # noqa: SLF001
    return [r[0] for r in rows]
