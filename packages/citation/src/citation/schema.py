"""JSON schema for synthesis output (claim/quote/^id triples). See ADR-0013.

The synthesis model emits a `Report` matching this shape. The wire format is JSON;
Pydantic validates on receipt and the orchestrator deterministically renders the
result to Markdown (see `assemble.py`). The AST verifier walks the *assembled
Markdown*, not the JSON — but extracting claims from the Markdown depends on this
structure being predictable, so changes here must move in lock-step with both
`assemble.py` and `ast_parse.py`.
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field


class Claim(BaseModel):
    """One assertion grounded in a single source block."""

    model_config = ConfigDict(extra="forbid")

    text: str = Field(
        min_length=1,
        description=(
            "The natural-language claim. One sentence. No citation markers — the "
            "assembler injects those deterministically from `block_id`."
        ),
    )
    quote: str = Field(
        min_length=1,
        description=(
            "Verbatim substring from the cited source that supports `text`. The "
            "verifier checks this substring exists in the source chunk."
        ),
    )
    block_id: str = Field(
        min_length=1,
        description=(
            "The bare `^id` of the source chunk (no leading `^`). Must resolve to a "
            "chunk that was included in the retrieval context for this query."
        ),
    )


class Section(BaseModel):
    model_config = ConfigDict(extra="forbid")

    heading: str = Field(min_length=1, description="Section title; rendered as H2.")
    claims: list[Claim] = Field(
        min_length=1,
        description="Claims in this section, in narrative order.",
    )


class Report(BaseModel):
    model_config = ConfigDict(extra="forbid")

    title: str = Field(min_length=1, description="Report title; rendered as H1.")
    summary: str = Field(
        min_length=1,
        description=(
            "One-paragraph TL;DR. Uncited prose — the verifier does NOT walk this; "
            "treat it as a navigational header. Claims belong in sections."
        ),
    )
    sections: list[Section] = Field(min_length=1)


def report_json_schema() -> dict:
    """Return the JSON-Schema document for the response. Passed to the inference
    adapter when constrained generation is requested."""
    return Report.model_json_schema()
