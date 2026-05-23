"""Vault traversal + change detection.

Cheap: stat-only signature (size, mtime_ns). No file content reads. The pipeline does
the actual content read once it decides the file has changed.
"""

from __future__ import annotations

from collections.abc import Iterator
from fnmatch import fnmatch
from pathlib import Path


def _matches_any(relpath: str, globs: list[str]) -> bool:
    return any(fnmatch(relpath, g) or fnmatch(relpath, f"**/{g}") for g in globs)


def iter_vault(vault_path: Path, ignore_globs: list[str] | None = None) -> Iterator[Path]:
    """Yield `.md` paths under `vault_path`, skipping anything matching `ignore_globs`."""
    ignore = ignore_globs or []
    for path in vault_path.rglob("*.md"):
        if not path.is_file():
            continue
        rel = path.relative_to(vault_path).as_posix()
        if _matches_any(rel, ignore):
            continue
        yield path


def file_signature(path: Path) -> tuple[int, int]:
    """(size_bytes, mtime_ns). Cheap change-detection primitive."""
    st = path.stat()
    return st.st_size, st.st_mtime_ns
