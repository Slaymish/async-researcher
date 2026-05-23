import asyncio
from pathlib import Path

import pytest
from ingestion.watcher import watch


@pytest.mark.asyncio
async def test_watcher_fires_on_change(tmp_path: Path):
    seen: list[Path] = []
    done = asyncio.Event()

    async def on_change(p: Path) -> None:
        seen.append(p)
        done.set()

    task = asyncio.create_task(
        watch(tmp_path, on_change, debounce_ms=50, ignore_globs=[])
    )
    # Give watchdog time to start its observer thread.
    await asyncio.sleep(0.2)
    target = tmp_path / "a.md"
    target.write_text("hello")

    try:
        await asyncio.wait_for(done.wait(), timeout=3.0)
    finally:
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass

    assert seen and seen[0].name == "a.md"


@pytest.mark.asyncio
async def test_watcher_debounces_bursts(tmp_path: Path):
    seen: list[Path] = []

    async def on_change(p: Path) -> None:
        seen.append(p)

    task = asyncio.create_task(
        watch(tmp_path, on_change, debounce_ms=200, ignore_globs=[])
    )
    await asyncio.sleep(0.2)
    target = tmp_path / "a.md"
    for content in ("v1", "v2", "v3"):
        target.write_text(content)
        await asyncio.sleep(0.02)

    # Wait past the debounce window.
    await asyncio.sleep(0.6)

    task.cancel()
    try:
        await task
    except asyncio.CancelledError:
        pass

    # Burst of three writes within debounce should produce at most a couple of fires,
    # not three. Allow some slack for FSEvents granularity.
    assert 1 <= len(seen) <= 2
