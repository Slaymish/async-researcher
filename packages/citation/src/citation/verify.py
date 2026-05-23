"""Stage 3b of ADR-0013: per-claim verification.

Three checks per claim:
1. **Link**: the cited `^id` exists in the index (deterministic SQL lookup).
2. **Quote-in-source**: the JSON's `quote` string is a substring of the cited
   chunk's text after whitespace normalisation (deterministic; cheap; catches
   fabricated quotes without a model call).
3. **Factual alignment**: a small judge model rules on whether the claim follows
   from the quote (model call; only fires when checks 1 and 2 pass).

Failures are returned as structured records so the repair loop can hand them back
to the synthesis model with specific guidance per claim.

Note that the `quote` field comes from the synthesis JSON, not the assembled
Markdown. The AST parser doesn't carry the quote into `ParsedClaim`, so the
verifier consumes the original `Report` *and* the assembled Markdown side by side:
the Markdown's claim sentence + cited `^id` is the user-facing surface; the JSON's
quote is the supporting evidence that the model claimed exists.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from enum import StrEnum

from inference import InferenceClient, Message
from pydantic import BaseModel, Field
from retrieval import Chunk, DuckDBStore

from .assemble import assemble
from .ast_parse import parse_report
from .schema import Claim, Report

log = logging.getLogger(__name__)


class FailureKind(StrEnum):
    BROKEN_LINK = "broken_link"  # block_id doesn't exist
    QUOTE_NOT_IN_SOURCE = "quote_not_in_source"  # fabricated quote
    UNSUPPORTED = "unsupported"  # judge says quote doesn't support claim
    MISSING_CITATION = "missing_citation"  # AST found a claim with no link


@dataclass(frozen=True)
class ClaimFailure:
    kind: FailureKind
    section_heading: str
    claim_text: str
    block_id: str | None
    detail: str  # short human-readable reason; included verbatim in repair prompt


@dataclass(frozen=True)
class VerificationReport:
    total_claims: int
    failures: list[ClaimFailure]

    @property
    def pass_rate(self) -> float:
        if self.total_claims == 0:
            return 1.0
        return max(0.0, 1.0 - len(self.failures) / self.total_claims)

    @property
    def passed(self) -> bool:
        return not self.failures


# --- substring check ---------------------------------------------------------

_WS_RE = re.compile(r"\s+")


def _normalise(s: str) -> str:
    return _WS_RE.sub(" ", s).strip().lower()


def quote_in_source(quote: str, source_text: str) -> bool:
    return _normalise(quote) in _normalise(source_text)


# --- judge-model alignment check ---------------------------------------------


class _AlignmentVerdict(BaseModel):
    supported: bool = Field(
        description="True iff the quote directly supports the claim."
    )
    reason: str = Field(
        description="One-sentence rationale. Used by the repair loop if false."
    )


_JUDGE_SYSTEM = (
    "You are a strict citation verifier. You will be given a CLAIM and a QUOTE that "
    "the writer says supports the claim. Your job is to determine if the quote, "
    "read literally, directly supports the claim. Be conservative: if the quote is "
    "ambiguous, tangential, or requires unstated inference, return supported=false. "
    "Return JSON only."
)


async def judge_alignment(
    client: InferenceClient,
    claim_text: str,
    quote: str,
    *,
    threshold: float = 0.8,  # reserved for future probabilistic judges
) -> _AlignmentVerdict:
    _ = threshold  # noqa: F841 (interface stability — see config.factual_alignment_threshold)
    messages: list[Message] = [
        {"role": "system", "content": _JUDGE_SYSTEM},
        {
            "role": "user",
            "content": (
                f"CLAIM: {claim_text}\n\nQUOTE: {quote}\n\n"
                "Return JSON: { \"supported\": bool, \"reason\": str }"
            ),
        },
    ]
    return await client.complete(
        messages,
        response_model=_AlignmentVerdict,
        model=client.config.judge_model,
        max_repair_attempts=1,
    )


# --- top-level verifier ------------------------------------------------------


async def verify_report(
    report: Report,
    store: DuckDBStore,
    client: InferenceClient,
    *,
    skip_alignment: bool = False,
) -> VerificationReport:
    """Run all three checks across every claim in the report.

    `skip_alignment=True` runs only the deterministic checks — useful for unit
    tests that don't want to spin up the judge model, and for the v0.1 fast path
    when the deterministic substring check already kills a claim.
    """
    all_claims: list[tuple[str, Claim]] = [
        (section.heading, claim)
        for section in report.sections
        for claim in section.claims
    ]
    chunks_by_id = store.get_chunks_by_ids([c.block_id for _, c in all_claims])
    failures: list[ClaimFailure] = []

    assembled = assemble(report, chunks_by_id)
    parsed = parse_report(assembled)
    json_claims_by_key = {
        (_normalise_claim_text(claim.text), heading): claim
        for heading, claim in all_claims
    }
    parsed_keys: set[tuple[str, str | None]] = set()
    for parsed_claim in parsed.claims:
        key = (
            _normalise_claim_text(parsed_claim.text),
            parsed_claim.section_heading,
        )
        parsed_keys.add(key)
        if parsed_claim.block_id is None and parsed_claim.url is None:
            failures.append(
                ClaimFailure(
                    kind=FailureKind.MISSING_CITATION,
                    section_heading=parsed_claim.section_heading or "",
                    claim_text=parsed_claim.text,
                    block_id=None,
                    detail=(
                        f"Assembled Markdown line {parsed_claim.line_no} has a "
                        "claim without a recognised citation. Every section claim "
                        "must render with a [[note#^id]] backlink."
                    ),
                )
            )
            continue
        json_claim = json_claims_by_key.get(key)
        if json_claim is not None and parsed_claim.block_id != json_claim.block_id:
            failures.append(
                ClaimFailure(
                    kind=FailureKind.BROKEN_LINK,
                    section_heading=parsed_claim.section_heading or "",
                    claim_text=parsed_claim.text,
                    block_id=parsed_claim.block_id,
                    detail=(
                        "Assembled Markdown citation does not match the JSON "
                        f"claim block_id `{json_claim.block_id}`."
                    ),
                )
            )

    for heading, claim in all_claims:
        key = (_normalise_claim_text(claim.text), heading)
        if key not in parsed_keys:
            failures.append(
                ClaimFailure(
                    kind=FailureKind.MISSING_CITATION,
                    section_heading=heading,
                    claim_text=claim.text,
                    block_id=claim.block_id,
                    detail=(
                        "JSON claim did not survive Markdown assembly/parsing with "
                        "a recognised citation. Check assembler output."
                    ),
                )
            )

    for heading, claim in all_claims:
        chunk = chunks_by_id.get(claim.block_id)
        if chunk is None:
            failures.append(
                ClaimFailure(
                    kind=FailureKind.BROKEN_LINK,
                    section_heading=heading,
                    claim_text=claim.text,
                    block_id=claim.block_id,
                    detail=(
                        f"Cited block_id `{claim.block_id}` does not exist in the "
                        "index. Pick a block_id that appeared in the retrieval "
                        "context for this query."
                    ),
                )
            )
            continue
        if not quote_in_source(claim.quote, chunk.text):
            failures.append(
                ClaimFailure(
                    kind=FailureKind.QUOTE_NOT_IN_SOURCE,
                    section_heading=heading,
                    claim_text=claim.text,
                    block_id=claim.block_id,
                    detail=(
                        f"The quote you provided is not a verbatim substring of the "
                        f"chunk at `{chunk.relpath}#^{claim.block_id}`. Quote text "
                        "must appear in the source word-for-word (whitespace-"
                        "insensitive). Pick a real substring."
                    ),
                )
            )
            continue
        if skip_alignment:
            continue
        try:
            verdict = await judge_alignment(client, claim.text, claim.quote)
        except Exception:
            log.exception("alignment judge failed for claim; treating as unsupported")
            failures.append(
                ClaimFailure(
                    kind=FailureKind.UNSUPPORTED,
                    section_heading=heading,
                    claim_text=claim.text,
                    block_id=claim.block_id,
                    detail="Alignment judge call failed; rewrite the claim more conservatively.",
                )
            )
            continue
        if not verdict.supported:
            failures.append(
                ClaimFailure(
                    kind=FailureKind.UNSUPPORTED,
                    section_heading=heading,
                    claim_text=claim.text,
                    block_id=claim.block_id,
                    detail=f"Judge: {verdict.reason}",
                )
            )
    return VerificationReport(total_claims=len(all_claims), failures=failures)


def chunks_for_context(
    store: DuckDBStore, report: Report
) -> dict[str, Chunk]:
    """Convenience pass-through for callers (assembler) needing the same lookup."""
    return store.get_chunks_by_ids(
        [c.block_id for s in report.sections for c in s.claims]
    )


def _normalise_claim_text(text: str) -> str:
    return _normalise(text).rstrip(".")
