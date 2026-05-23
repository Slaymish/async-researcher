"""Stage 2 of ADR-0013: deterministic JSON → Markdown render.

Pure function. The synthesis model emits a `Report` (see `schema.py`); the assembler
renders it to Markdown with each claim's citation inlined as an Obsidian backlink:

    Claim sentence. [[Folder/Note#^ai-abc]]

For web-sourced chunks (relpath prefixed with `web://` per ADR-0019), the link form
becomes `[anchor text](url)` instead of `[[…]]`. Both shapes are downstream-parseable
by `ast_parse.py`; both are stable round-trips for the same JSON input.

This module deliberately does **no** validation of `block_id`s — the verifier handles
that on the assembled output. Keeping assembly pure means the same JSON always
produces the same Markdown, which is essential for the AST round-trip to be
meaningful as a verification surface.
"""

from __future__ import annotations

from retrieval import Chunk

from .schema import Claim, Report

WEB_PREFIX = "web://"


def _link(claim: Claim, chunk: Chunk | None) -> str:
    """Render one claim's citation token.

    - Vault chunk: `[[<relpath without .md>#^<block_id>]]` (Obsidian convention).
    - Web chunk:   `[<host>](<url>)` — the URL is the relpath after stripping the
      `web://` prefix; the host is the netloc.
    - Unknown chunk (id not in retrieval context): `[[#^<block_id>]]` — produces a
      broken link that the verifier will catch. Better than dropping the citation
      and silently severing the claim from its source.
    """
    if chunk is None:
        return f"[[#^{claim.block_id}]]"
    if chunk.relpath.startswith(WEB_PREFIX):
        url = chunk.relpath[len(WEB_PREFIX) :]
        host = url.split("/", 1)[0] if "/" in url else url
        return f"[{host}](https://{url})"
    note = chunk.relpath.removesuffix(".md")
    return f"[[{note}#^{claim.block_id}]]"


def assemble(report: Report, chunks_by_id: dict[str, Chunk] | None = None) -> str:
    """Render a `Report` as Markdown.

    `chunks_by_id` lets the assembler resolve `block_id` → `relpath` so it can write
    full `[[note#^id]]` backlinks. When a chunk is missing from the mapping the
    citation falls back to an anchor-only form (`[[#^id]]`) — the verifier will flag
    it as a broken link, which is the correct, visible failure mode.
    """
    by_id = chunks_by_id or {}
    out: list[str] = [f"# {report.title}", "", report.summary.strip(), ""]
    for section in report.sections:
        out.append(f"## {section.heading}")
        out.append("")
        for claim in section.claims:
            chunk = by_id.get(claim.block_id)
            sentence = claim.text.rstrip()
            # Strip a trailing period so we can re-add it after the citation.
            if sentence.endswith("."):
                sentence = sentence[:-1]
            out.append(f"{sentence}. {_link(claim, chunk)}")
            out.append("")
    # Drop trailing blank line for cleanliness; ensure single trailing newline.
    while out and out[-1] == "":
        out.pop()
    return "\n".join(out) + "\n"
