"""Bounded semantic-repair loop for failed citations (ADR-0013).

Schema failures are handled by `inference.complete()`'s validation retry. This
module handles the *semantic* failures the verifier surfaces — broken links,
fabricated quotes, judge-rejected alignments — by handing the failure list back to
the synthesis model with specific, per-claim guidance and asking for a revised
report.

The loop is bounded (`max_repair_attempts`, default 2 per config) and short-
circuits as soon as verification passes. The final state — repaired or not — is
returned to the caller, which surfaces verification results to the UI.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass

from inference import InferenceClient, Message
from retrieval import DuckDBStore, ScoredChunk

from .schema import Report
from .synth import build_messages
from .verify import ClaimFailure, VerificationReport, verify_report

log = logging.getLogger(__name__)


@dataclass(frozen=True)
class RepairOutcome:
    report: Report
    verification: VerificationReport
    attempts: int  # number of synth calls made, including the initial one


def _failure_brief(failures: list[ClaimFailure]) -> str:
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


async def repair_loop(
    initial: Report,
    query: str,
    chunks: list[ScoredChunk],
    store: DuckDBStore,
    client: InferenceClient,
    *,
    max_repair_attempts: int = 2,
    skip_alignment: bool = False,
) -> RepairOutcome:
    """Verify; if passing, return. Otherwise feed failures back and retry."""
    report = initial
    attempts = 1
    verification = await verify_report(
        report, store, client, skip_alignment=skip_alignment
    )
    base_messages = build_messages(query, chunks)
    convo: list[Message] = list(base_messages)
    while verification.failures and attempts <= max_repair_attempts:
        log.info(
            "citation repair attempt %d/%d (%d failures, pass_rate=%.2f)",
            attempts,
            max_repair_attempts,
            len(verification.failures),
            verification.pass_rate,
        )
        convo = [
            *convo,
            {"role": "assistant", "content": report.model_dump_json()},
            {"role": "user", "content": _failure_brief(verification.failures)},
        ]
        report = await client.complete(
            convo,
            response_model=Report,
            max_repair_attempts=1,  # schema fixup; semantic loop is THIS loop
        )
        attempts += 1
        verification = await verify_report(
            report, store, client, skip_alignment=skip_alignment
        )
    return RepairOutcome(report=report, verification=verification, attempts=attempts)
