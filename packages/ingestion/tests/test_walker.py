from pathlib import Path

from ingestion.walker import file_signature, iter_vault


def test_iter_vault_yields_only_md(tmp_path: Path):
    (tmp_path / "a.md").write_text("a")
    (tmp_path / "b.txt").write_text("b")
    (tmp_path / "nested").mkdir()
    (tmp_path / "nested" / "c.md").write_text("c")
    found = sorted(p.relative_to(tmp_path).as_posix() for p in iter_vault(tmp_path))
    assert found == ["a.md", "nested/c.md"]


def test_ignore_globs_respected(tmp_path: Path):
    (tmp_path / "a.md").write_text("a")
    (tmp_path / ".obsidian").mkdir()
    (tmp_path / ".obsidian" / "ignored.md").write_text("x")
    found = sorted(
        p.relative_to(tmp_path).as_posix()
        for p in iter_vault(tmp_path, ignore_globs=[".obsidian/**"])
    )
    assert found == ["a.md"]


def test_signature_changes_on_edit(tmp_path: Path):
    p = tmp_path / "a.md"
    p.write_text("one")
    sig1 = file_signature(p)
    # Force a different mtime: write distinct content with an artificial delay.
    import os
    import time

    time.sleep(0.01)
    p.write_text("one two")
    os.utime(p, None)
    sig2 = file_signature(p)
    assert sig1 != sig2
