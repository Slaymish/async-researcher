"""Markdown → logical blocks.

Pure functions, no I/O. A "logical block" is the unit retrieval returns and citation
cites: a heading line, a paragraph, an individual list item, a fenced code block, or a
table. Frontmatter is stripped and returned separately so the indexer can store it as
queryable metadata. Block-IDs already present on a block (per the Obsidian `^id`
convention) are detected and reported via `existing_id` so the id-injector knows not to
overwrite them.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, replace
from typing import Literal

import yaml
from markdown_it import MarkdownIt

BlockKind = Literal["heading", "para", "list_item", "code", "table"]

# Obsidian block-id token. Must appear at end of block (last non-blank line).
# Allowed chars per Obsidian: letters, digits, hyphen, underscore.
_BLOCK_ID_RE = re.compile(r"\s*\^([A-Za-z0-9][A-Za-z0-9\-_]*)\s*$")


@dataclass(frozen=True)
class Block:
    kind: BlockKind
    text: str
    line_start: int  # 0-indexed, inclusive, relative to body (post-frontmatter)
    line_end: int  # 0-indexed, exclusive
    existing_id: str | None  # the bare id, no `^` prefix


@dataclass(frozen=True)
class ParsedDocument:
    frontmatter: dict
    body: str
    body_line_offset: int  # line index in the original file where body starts
    blocks: list[Block]


_FRONTMATTER_RE = re.compile(r"\A---\r?\n(.*?)\r?\n---\r?\n", re.DOTALL)


def _split_frontmatter(text: str) -> tuple[dict, str, int]:
    m = _FRONTMATTER_RE.match(text)
    if not m:
        return {}, text, 0
    raw = m.group(1)
    try:
        data = yaml.safe_load(raw) or {}
        if not isinstance(data, dict):
            data = {"_raw": data}
    except yaml.YAMLError:
        data = {"_unparseable": raw}
    body = text[m.end() :]
    offset = text[: m.end()].count("\n")
    return data, body, offset


def _extract_id(text: str) -> tuple[str, str | None]:
    """Strip a trailing `^id` token from a block's text. Returns (clean_text, id_or_None)."""
    lines = text.split("\n")
    i = len(lines) - 1
    while i >= 0 and lines[i].strip() == "":
        i -= 1
    if i < 0:
        return text, None
    m = _BLOCK_ID_RE.search(lines[i])
    if not m:
        return text, None
    bare = lines[i][: m.start()]
    if bare.strip():
        lines[i] = bare.rstrip()
    else:
        lines.pop(i)
    return "\n".join(lines).rstrip(), m.group(1)


def _keep_leaf_list_items(blocks: list[Block]) -> list[Block]:
    """Drop list_items whose range strictly contains another list_item.

    markdown-it emits a `list_item_open` token for every level of nesting; an outer
    list item ends up covering the same lines as its nested children. Citation needs
    one block per leaf, so non-leaf containers are dropped. A trailing `^id` written
    onto a nested item would otherwise be parsed as the existing id of *both* the
    outer and inner blocks, producing duplicate primary keys downstream.
    """
    list_items = [(i, b) for i, b in enumerate(blocks) if b.kind == "list_item"]
    drop: set[int] = set()
    for i, outer in list_items:
        for j, inner in list_items:
            if i == j:
                continue
            if (
                outer.line_start <= inner.line_start
                and inner.line_end <= outer.line_end
                and (inner.line_start, inner.line_end) != (outer.line_start, outer.line_end)
            ):
                drop.add(i)
                break
    return [b for i, b in enumerate(blocks) if i not in drop]


def parse_markdown(text: str) -> ParsedDocument:
    frontmatter, body, offset = _split_frontmatter(text)
    body_lines = body.split("\n")
    md = MarkdownIt("commonmark", {"html": False}).enable("table")
    tokens = md.parse(body)

    blocks: list[Block] = []

    def _emit(kind: BlockKind, line_start: int, line_end: int) -> None:
        snippet = "\n".join(body_lines[line_start:line_end])
        clean, existing = _extract_id(snippet)
        if not clean.strip():
            # Standalone `^id` block (Obsidian convention: attaches to preceding block).
            if existing and blocks and blocks[-1].existing_id is None:
                blocks[-1] = replace(blocks[-1], existing_id=existing)
            return
        blocks.append(
            Block(
                kind=kind,
                text=clean,
                line_start=line_start,
                line_end=line_end,
                existing_id=existing,
            )
        )

    i = 0
    while i < len(tokens):
        t = tokens[i]
        if t.type == "heading_open" and t.map:
            _emit("heading", t.map[0], t.map[1])
            while i < len(tokens) and tokens[i].type != "heading_close":
                i += 1
        elif t.type == "paragraph_open" and t.map and t.level == 0:
            _emit("para", t.map[0], t.map[1])
            while i < len(tokens) and tokens[i].type != "paragraph_close":
                i += 1
        elif t.type == "fence" and t.map and t.level == 0:
            _emit("code", t.map[0], t.map[1])
        elif t.type == "code_block" and t.map and t.level == 0:
            _emit("code", t.map[0], t.map[1])
        elif t.type == "table_open" and t.map and t.level == 0:
            _emit("table", t.map[0], t.map[1])
            while i < len(tokens) and tokens[i].type != "table_close":
                i += 1
        elif t.type == "list_item_open" and t.map:
            _emit("list_item", t.map[0], t.map[1])
        i += 1

    blocks = _keep_leaf_list_items(blocks)

    return ParsedDocument(
        frontmatter=frontmatter,
        body=body,
        body_line_offset=offset,
        blocks=blocks,
    )
