"""Stage 3a of ADR-0013: AST parse of the *assembled Markdown* → list[ParsedClaim].

This is the load-bearing verification surface. We parse the rendered Markdown rather
than trusting the JSON the LLM emitted, because the assembled document is what the
user actually sees and trusts. If the assembler ever drops a citation token, the AST
parser catches it as a claim-without-citation; if the model fabricates a citation
that survives Pydantic, the link/quote check downstream still kills it.

Deterministic, no LLM call. Pure function over a string.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from markdown_it import MarkdownIt

# Vault backlinks: [[anything#^id]]   |  web links: [text](https://...)
_VAULT_LINK_RE = re.compile(r"\[\[([^\]\#]*)#\^([A-Za-z0-9][A-Za-z0-9\-_]*)\]\]")
_WEB_LINK_RE = re.compile(r"\[([^\]]+)\]\((https?://[^)]+)\)")


@dataclass(frozen=True)
class ParsedClaim:
    text: str  # the sentence preceding the citation, stripped of the link
    block_id: str | None  # set when the citation is a vault backlink
    url: str | None  # set when the citation is a web link
    section_heading: str | None
    line_no: int  # 1-indexed line in the assembled document


@dataclass(frozen=True)
class ParsedReport:
    title: str | None
    claims: list[ParsedClaim]


def parse_report(markdown: str) -> ParsedReport:
    """Walk the assembled report. One `ParsedClaim` per claim-line emitted by
    `assemble.py`. Claims without a recognised citation are returned with
    `block_id=None, url=None` so the verifier can flag them."""
    md = MarkdownIt("commonmark", {"html": False})
    tokens = md.parse(markdown)
    lines = markdown.split("\n")

    title: str | None = None
    current_section: str | None = None
    claims: list[ParsedClaim] = []

    i = 0
    while i < len(tokens):
        t = tokens[i]
        if t.type == "heading_open" and t.map:
            level = int(t.tag[1])  # h1 -> 1
            # Inline tag carries the text.
            inline = tokens[i + 1] if i + 1 < len(tokens) else None
            text = inline.content if inline and inline.type == "inline" else ""
            if level == 1 and title is None:
                title = text.strip()
            elif level == 2:
                current_section = text.strip()
        elif t.type == "paragraph_open" and t.map and t.level == 0:
            inline = tokens[i + 1] if i + 1 < len(tokens) else None
            if inline is not None and inline.type == "inline":
                raw = "\n".join(lines[t.map[0] : t.map[1]])
                parsed = _parse_claim_line(raw, current_section, t.map[0] + 1)
                if parsed is not None:
                    claims.append(parsed)
        i += 1
    return ParsedReport(title=title, claims=claims)


def _parse_claim_line(
    raw: str, section: str | None, line_no: int
) -> ParsedClaim | None:
    """Pull (text, block_id|url) out of a single paragraph that the assembler wrote.

    Conventions written by `assemble.py`:
        <claim text>. [[<relpath>#^<id>]]
        <claim text>. [<host>](<url>)
    """
    vault = _VAULT_LINK_RE.search(raw)
    web = _WEB_LINK_RE.search(raw)
    # Match the citation that appears last (closest to end-of-paragraph).
    if vault and (not web or vault.start() > web.start()):
        text = raw[: vault.start()].rstrip().rstrip(".").rstrip()
        if not text:
            return None
        return ParsedClaim(
            text=text,
            block_id=vault.group(2),
            url=None,
            section_heading=section,
            line_no=line_no,
        )
    if web:
        text = raw[: web.start()].rstrip().rstrip(".").rstrip()
        if not text:
            return None
        return ParsedClaim(
            text=text,
            block_id=None,
            url=web.group(2),
            section_heading=section,
            line_no=line_no,
        )
    # Paragraph carries no citation. Only treat as a claim if section is set —
    # this skips the summary paragraph (which lives above any ## section).
    if section is not None:
        text = raw.strip()
        if not text:
            return None
        return ParsedClaim(
            text=text,
            block_id=None,
            url=None,
            section_heading=section,
            line_no=line_no,
        )
    return None
