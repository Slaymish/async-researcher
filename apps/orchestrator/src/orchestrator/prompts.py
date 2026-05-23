from __future__ import annotations

import json
from typing import Any

from inference import Message

PLANNER_SYSTEM_TEMPLATE = """\
You are a research planner. Given a user question, decompose it into the smallest
useful set of focused sub-questions. A downstream agent will answer each sub-question
independently against a personal knowledge vault, and a final pass will compose the
sub-answers into a single report.

HARD RULES — your output is rejected if any of these are violated:

1. **Output is JSON only.** Conform exactly to the schema you are given. No prose,
   no markdown fences, no preamble.

2. **At least 1, at most {planner_fanout_cap} sub-queries.** Prefer fewer. Each
   sub-query costs a full retrieval + synthesis pass downstream.

3. **Self-contained sub-queries.** Each sub-query is a standalone question. Do not
   use pronouns that depend on sibling sub-queries ("it", "this", "the above").

4. **One rationale per sub-query.** A single sentence explaining why this
   sub-query is in the plan — what aspect of the user's question it covers.

5. **Route each sub-query to "vault" or "web".** Use "vault" for questions
   answerable from the user's personal knowledge base (their notes, saved
   research, documents). Use "web" when the vault is unlikely to have the
   answer — recent events, current public data, external documentation, or
   anything the user would need to look up online. Bias toward "vault":
   web routing triggers additional fetching cost; only choose it when vault
   retrieval would clearly come up empty.

If the user question turns out to be naturally atomic (single topic, single fact,
no decomposition useful), return exactly ONE sub-query equal to the user question.
This keeps the downstream agent invariant — there is always at least one Executor
to run.
"""

ATOMIZER_SYSTEM = """\
You decide whether a research question should be broken into focused sub-questions
before being answered, or whether a single retrieve-then-answer pass is enough.

Return JSON: {"decompose": <true|false>, "rationale": "<one sentence>"}.

Decompose if the question:
- covers multiple distinct topics, entities, or time periods;
- is a research spec / multi-paragraph brief rather than a single question;
- requires retrieving from multiple unrelated parts of a knowledge vault to
  answer well.

Otherwise return decompose=false.

Bias toward false when in doubt. A wrong "true" wastes downstream LLM calls;
a wrong "false" still produces a useful single-pass answer.

Output JSON only. No prose, no markdown fences.
"""


def planner_system(planner_fanout_cap: int) -> str:
    return PLANNER_SYSTEM_TEMPLATE.format(planner_fanout_cap=planner_fanout_cap)


def build_planner_messages(
    query: str,
    *,
    max_sub_queries: int,
    planner_fanout_cap: int,
    plan_schema: dict[str, Any],
    memory_facts: list[str] | None = None,
) -> list[Message]:
    schema = json.dumps(plan_schema, indent=2)
    user = (
        f"USER QUESTION:\n{query}\n\n"
        f"Use at most {max_sub_queries} sub-queries for this run.\n\n"
        "Produce a JSON document matching exactly this schema:\n\n"
        f"```\n{schema}\n```\n"
    )
    if memory_facts:
        facts_block = "\n".join(f"- {f}" for f in memory_facts)
        user = (
            "KNOWN FACTS FROM MEMORY (pre-context only — do not cite these as "
            "vault sources; they inform sub-query focus but are not evidence):\n"
            f"{facts_block}\n\n"
        ) + user
    return [
        {"role": "system", "content": planner_system(planner_fanout_cap)},
        {"role": "user", "content": user},
    ]


def build_atomizer_messages(query: str) -> list[Message]:
    return [
        {"role": "system", "content": ATOMIZER_SYSTEM},
        {"role": "user", "content": f"QUESTION:\n{query}"},
    ]


def build_repair_failure_brief(failures: list[Any]) -> str:
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
