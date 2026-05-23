from __future__ import annotations

import json

from inference import Message
from retrieval import ScoredChunk

from .schema import report_json_schema

SYNTHESIS_SYSTEM = """\
You are a research synthesis agent operating on a private knowledge vault. You will
be given a USER QUERY and a list of CONTEXT CHUNKS retrieved from the vault.

Your task: produce a faithful, well-organised report that answers the query, citing
every claim back to a specific context chunk.

HARD RULES — your output is rejected if any of these are violated:

1. **Every claim cites exactly one block_id.** The `block_id` MUST be one of the
   ids in the supplied context — never invent a new one. If no chunk supports the
   claim you want to make, drop the claim.

2. **`quote` is verbatim.** The `quote` field on each claim MUST be a literal
   substring of the cited chunk's text. Whitespace differences are tolerated; word
   changes are not. Copy-paste from the source.

3. **`text` is your sentence.** The `text` field is the natural-language claim you
   want in the final report. It paraphrases or summarises the quote — it is NOT a
   copy of the quote.

4. **Sections are coherent.** Group related claims under each section heading; one
   sentence per claim.

5. **`summary` is uncited prose.** A short paragraph orienting the reader. Do not
   put claims in the summary.

6. **JSON only.** No markdown fences, no prose preamble, no trailing notes.
"""

JUDGE_ALIGNMENT_SYSTEM = (
    "You are a strict citation verifier. You will be given a CLAIM and a QUOTE that "
    "the writer says supports the claim. Your job is to determine if the quote, "
    "read literally, directly supports the claim. Be conservative: if the quote is "
    "ambiguous, tangential, or requires unstated inference, return supported=false. "
    "Return JSON only."
)


def format_context(chunks: list[ScoredChunk]) -> str:
    out: list[str] = []
    for i, sc in enumerate(chunks, 1):
        chunk = sc.chunk
        header = f"[{i}] block_id=`{chunk.block_id}`  source=`{chunk.relpath}`  kind={chunk.kind}"
        out.append(header)
        out.append("```")
        out.append(chunk.text)
        out.append("```")
        out.append("")
    return "\n".join(out).rstrip()


def build_synthesis_messages(query: str, chunks: list[ScoredChunk]) -> list[Message]:
    schema_json = json.dumps(report_json_schema(), indent=2)
    user_content = (
        f"USER QUERY: {query}\n\n"
        f"CONTEXT CHUNKS ({len(chunks)} items, ordered by relevance):\n\n"
        f"{format_context(chunks)}\n\n"
        "Produce a JSON document matching exactly this schema:\n\n"
        f"```\n{schema_json}\n```\n"
    )
    return [
        {"role": "system", "content": SYNTHESIS_SYSTEM},
        {"role": "user", "content": user_content},
    ]


def build_alignment_messages(claim_text: str, quote: str) -> list[Message]:
    return [
        {"role": "system", "content": JUDGE_ALIGNMENT_SYSTEM},
        {
            "role": "user",
            "content": (
                f"CLAIM: {claim_text}\n\nQUOTE: {quote}\n\n"
                'Return JSON: { "supported": bool, "reason": str }'
            ),
        },
    ]


def build_failure_brief(failures: list) -> str:
    lines = [
        "Your previous report had the following verification failures. Produce a "
        "new report that fixes every one of them. You may drop a claim if you "
        "cannot ground it, but you must NOT keep the broken version.",
        "",
    ]
    for i, f in enumerate(failures, 1):
        bid = f.block_id or "(none)"
        lines.append(
            f"[{i}] section=`{f.section_heading}` block_id=`{bid}` kind={f.kind.value}"
        )
        lines.append(f"    claim: {f.claim_text}")
        lines.append(f"    why:   {f.detail}")
    return "\n".join(lines)
