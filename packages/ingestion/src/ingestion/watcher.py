"""Always-on file watcher (watchdog-based). v0.1, ADR-0017.

Bridges watchdog's threaded event loop into asyncio: the watchdog handler pushes events
onto a thread-safe queue, an asyncio task drains them, debounces per-path, and invokes
the async `on_change` callback. Single asyncio task — no concurrency on `on_change`,
which lets the pipeline's per-file sequential semantics hold.
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Awaitable, Callable
from fnmatch import fnmatch
from pathlib import Path

from watchdog.events import FileSystemEvent, FileSystemEventHandler
from watchdog.observers import Observer

log = logging.getLogger(__name__)

OnChange = Callable[[Path], Awaitable[None]]
OnDelete = Callable[[Path], Awaitable[None]]


class _Handler(FileSystemEventHandler):
    def __init__(self, loop: asyncio.AbstractEventLoop, queue: asyncio.Queue) -> None:
        self._loop = loop
        self._queue = queue

    def _push(self, kind: str, path: str) -> None:
        if not path.endswith(".md"):
            return
        # call_soon_threadsafe is the standard asyncio bridge from a non-async thread.
        self._loop.call_soon_threadsafe(self._queue.put_nowait, (kind, path))

    def on_modified(self, event: FileSystemEvent) -> None:
        if not event.is_directory:
            self._push("modified", event.src_path)

    def on_created(self, event: FileSystemEvent) -> None:
        if not event.is_directory:
            self._push("modified", event.src_path)

    def on_moved(self, event) -> None:  # type: ignore[no-untyped-def]
        if not event.is_directory:
            # Treat as delete-of-src + modified-of-dest.
            self._push("deleted", event.src_path)
            self._push("modified", event.dest_path)

    def on_deleted(self, event: FileSystemEvent) -> None:
        if not event.is_directory:
            self._push("deleted", event.src_path)


def _matches_any(rel: str, globs: list[str]) -> bool:
    return any(fnmatch(rel, g) or fnmatch(rel, f"**/{g}") for g in globs)


async def watch(
    vault_path: Path,
    on_change: OnChange,
    on_delete: OnDelete | None = None,
    *,
    debounce_ms: int = 500,
    ignore_globs: list[str] | None = None,
) -> None:
    """Run until cancelled. Cancellation stops the watchdog observer cleanly."""
    ignore = ignore_globs or []
    loop = asyncio.get_running_loop()
    queue: asyncio.Queue[tuple[str, str]] = asyncio.Queue()
    pending: dict[Path, asyncio.TimerHandle] = {}
    pending_kinds: dict[Path, str] = {}

    observer = Observer()
    observer.schedule(_Handler(loop, queue), str(vault_path), recursive=True)
    observer.start()
    log.info("watcher started on %s", vault_path)

    async def _fire(path: Path) -> None:
        kind = pending_kinds.pop(path, "modified")
        pending.pop(path, None)
        try:
            if kind == "deleted":
                if on_delete is not None:
                    await on_delete(path)
                else:
                    await on_change(path)  # pipeline handles missing-file as deletion
            else:
                await on_change(path)
        except Exception:
            log.exception("watcher callback failed for %s", path)

    def _schedule(path: Path) -> None:
        existing = pending.pop(path, None)
        if existing is not None:
            existing.cancel()
        handle = loop.call_later(
            debounce_ms / 1000.0,
            lambda: asyncio.create_task(_fire(path)),
        )
        pending[path] = handle

    try:
        while True:
            kind, raw_path = await queue.get()
            path = Path(raw_path)
            try:
                rel = path.relative_to(vault_path).as_posix()
            except ValueError:
                continue
            if _matches_any(rel, ignore):
                continue
            # Last-writer-wins for the kind: a 'deleted' arriving after 'modified' overrides.
            pending_kinds[path] = kind
            _schedule(path)
    except asyncio.CancelledError:
        log.info("watcher stopping")
        for handle in pending.values():
            handle.cancel()
        observer.stop()
        observer.join(timeout=2.0)
        raise
