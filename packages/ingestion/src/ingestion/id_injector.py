"""Deterministic, idempotent ^id assignment. See ADR-0012.

Generated ids carry the prefix `ai-` to distinguish them from user-authored block ids;
this matters in v0.3 when the autonomous filing daemon edits notes. The hash is
blake2b(relpath || index || normalised text) truncated to 8 hex chars. Two blocks in the
same file that hash identically (e.g. a duplicated paragraph) get a `-1`, `-2`
disambiguator suffix.

`inject_ids` is pure: it returns the rewritten file text and the blocks with ids filled
in. Disk I/O is the caller's responsibility.
"""

from __future__ import annotations

import hashlib
import re
from dataclasses import replace

from .parser import Block, ParsedDocument

GENERATED_PREFIX = "ai-"
_HASH_LEN = 8
_WHITESPACE_RE = re.compile(r"\s+")


def _normalise(text: str) -> str:
    return _WHITESPACE_RE.sub(" ", text).strip()


def compute_id(relpath: str, index: int, text: str) -> str:
    """Pure id derivation. Stable across runs; depends only on (relpath, index, text)."""
    payload = f"{relpath}\x00{index}\x00{_normalise(text)}".encode()
    digest = hashlib.blake2b(payload, digest_size=_HASH_LEN // 2).hexdigest()
    return f"{GENERATED_PREFIX}{digest}"


def _disambiguate(base: str, used: set[str]) -> str:
    if base not in used:
        return base
    n = 1
    while f"{base}-{n}" in used:
        n += 1
    return f"{base}-{n}"


def assign_ids(
    relpath: str,
    blocks: list[Block],
    *,
    reserved: set[str] | None = None,
) -> list[Block]:
    """Fill in missing ids on a list of blocks.

    Existing ids on the blocks themselves are preserved verbatim. `reserved` is the set
    of ids already in use elsewhere (typically: ids in other files' chunks) — generated
    ids will be disambiguated against this set as well as against the current file.
    """
    used: set[str] = set(reserved or ())
    used.update(b.existing_id for b in blocks if b.existing_id)
    used.discard(None)  # type: ignore[arg-type]
    result: list[Block] = []
    for idx, b in enumerate(blocks):
        if b.existing_id:
            result.append(b)
            continue
        candidate = _disambiguate(compute_id(relpath, idx, b.text), used)
        used.add(candidate)
        result.append(replace(b, existing_id=candidate))
    return result


def _append_id_to_line(line: str, block_id: str) -> str:
    stripped = line.rstrip()
    if not stripped:
        return f"^{block_id}"
    return f"{stripped} ^{block_id}"


def _inject_into_lines(body_lines: list[str], block: Block, block_id: str) -> None:
    """Mutate body_lines in place, inserting `^id` for the given block.

    Rules:
    - For paragraphs and list items, the id is appended trailing on the block's last
      non-blank line.
    - For headings, code fences, and tables, the id goes on its own line immediately
      after the block (Obsidian convention — trailing tokens inside code/tables are
      illegal).
    """
    last = block.line_end - 1
    while last >= block.line_start and not body_lines[last].strip():
        last -= 1
    if last < block.line_start:
        return

    if block.kind in ("para", "list_item"):
        body_lines[last] = _append_id_to_line(body_lines[last], block_id)
    else:
        # Insert id on its own line, with a blank line on each side so the next parse
        # sees it as a standalone block (the parser attaches a standalone `^id` to the
        # preceding block — idempotence depends on the surrounding blanks).
        insert_at = block.line_end
        if insert_at < len(body_lines) and body_lines[insert_at].strip() == "":
            # Existing blank above; ensure a blank below too.
            id_pos = insert_at + 1
            body_lines.insert(id_pos, f"^{block_id}")
            if id_pos + 1 >= len(body_lines) or body_lines[id_pos + 1].strip() != "":
                body_lines.insert(id_pos + 1, "")
        else:
            body_lines.insert(insert_at, "")
            body_lines.insert(insert_at + 1, f"^{block_id}")
            body_lines.insert(insert_at + 2, "")


def inject_ids(
    file_text: str,
    parsed: ParsedDocument,
    relpath: str,
    *,
    reserved: set[str] | None = None,
) -> tuple[str, list[Block]]:
    """Return (rewritten_text, blocks_with_ids).

    Idempotence:
    - Blocks whose `existing_id` is already populated are left untouched in the file.
    - Re-running this on the rewritten text produces a no-op: the second parse will see
      every block already has an id.
    """
    blocks_with_ids = assign_ids(relpath, parsed.blocks, reserved=reserved)

    # Identify blocks that need to be written into the file (didn't have an id before).
    needs_write = [
        (b, b.existing_id)
        for b, original in zip(blocks_with_ids, parsed.blocks, strict=True)
        if original.existing_id is None
    ]
    if not needs_write:
        return file_text, blocks_with_ids

    body_lines = parsed.body.split("\n")
    # Process in reverse line order so earlier inserts don't shift later block ranges.
    for block, block_id in sorted(needs_write, key=lambda x: -x[0].line_start):
        assert block_id is not None  # assign_ids guarantees this
        _inject_into_lines(body_lines, block, block_id)

    new_body = "\n".join(body_lines)
    # Reattach frontmatter, if any.
    if parsed.body_line_offset > 0:
        # Reconstruct the original frontmatter slice from file_text.
        head_end = 0
        nl = 0
        for i, ch in enumerate(file_text):
            if ch == "\n":
                nl += 1
                if nl == parsed.body_line_offset:
                    head_end = i + 1
                    break
        head = file_text[:head_end]
        return head + new_body, blocks_with_ids
    return new_body, blocks_with_ids
