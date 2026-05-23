"""ROMA decomposition: schemas, nodes, helpers. v0.2.2 deliverable 2.

See `docs/v0.2.2_ROMA_PLAN.md` for the full design + sign-off record. This
module owns the Pydantic schemas, the node bodies (atomize / plan / execute /
aggregate), and the diagnostic shim. Graph wiring lives in `graph.py`.

The four ROMA roles are described in `ArchitectureSpecification.md` §1.1
(Atomizer/Planner/Executor/Aggregator). v0.2.2 implements the *single-level*
flat case — sub-queries do not recursively re-enter the Atomizer. Recursion
is a v0.2.3+ candidate once we have eval data on the flat case.
"""

from __future__ import annotations

import logging
import statistics
from typing import Literal

from citation import Report, VerificationReport, repair_loop, synthesise
from citation.schema import Claim, Section
from inference import InferenceClient, InferenceTask, model_for_task
from pydantic import BaseModel, ConfigDict, Field
from retrieval import DuckDBStore, Retriever, ScoredChunk

from ..prompts import build_atomizer_messages, build_planner_messages

log = logging.getLogger(__name__)


class AtomizerVerdict(BaseModel):
    """Output of the Atomizer LLM call.

    Runs on the judge model (per sign-off — small, fast). Drives whether the
    Planner is invoked at all.
    """

    model_config = ConfigDict(extra="forbid")

    decompose: bool = Field(
        description=(
            "True if the question should be broken into focused sub-queries; "
            "False if a single retrieve→synth pass is enough."
        ),
    )
    rationale: str = Field(
        min_length=1,
        max_length=400,
        description=(
            "One sentence explaining the decision. Logged + surfaced in the "
            "execution log so the user can audit the Atomizer's calls."
        ),
    )


class SubQuery(BaseModel):
    """One focused sub-question the Planner emits."""

    model_config = ConfigDict(extra="forbid")

    text: str = Field(min_length=1, description="The focused sub-question.")
    rationale: str = Field(
        min_length=1,
        max_length=400,
        description="One sentence: why this sub-query exists in the plan.",
    )
    target: Literal["vault"] = Field(
        default="vault",
        description=(
            "Where this sub-query will be routed. v0.2.2 = vault only. "
            "Web routing arrives with deliverable 4-5; the field exists now "
            "so the schema doesn't break later."
        ),
    )


# Hard cap on Planner fan-out width — sign-off chose 5. Per Risk R2, if
# end-to-end latency breaches the roadmap's 30s ceiling, this is the first
# lever to drop.
PLANNER_FANOUT_CAP = 5


class Plan(BaseModel):
    """Planner output: an ordered list of focused sub-queries.

    Constraint min_length=1 keeps the Aggregator's "len(sub_reports) >= 1"
    invariant honest — even when the Atomizer says decompose but the Planner
    can't actually decompose, the Planner must emit one sub-query equal to
    the input rather than returning an empty list.
    """

    model_config = ConfigDict(extra="forbid")

    sub_queries: list[SubQuery] = Field(
        min_length=1,
        max_length=PLANNER_FANOUT_CAP,
    )


class SubReport(BaseModel):
    """One Executor's output: a sub-Report plus per-Executor verification.

    The Aggregator consumes a `list[SubReport]` and produces a single `Report`
    + the unioned `chunks` for the post-merge verify+assemble pass.

    Per sign-off (#2, #3): each Executor runs the full verify+repair cycle
    before emitting its SubReport, so `verification` reflects per-Executor
    state. The post-merge cycle runs against the merged Report and catches
    cross-Report inconsistencies the per-Executor cycle could not see.
    """

    model_config = ConfigDict(extra="forbid", arbitrary_types_allowed=True)

    sub_query: SubQuery
    chunks: list[ScoredChunk]
    report: Report
    verification: VerificationReport
    attempts: int = Field(
        ge=1,
        description=(
            "Synth + repair count for this Executor (matches "
            "citation.repair_loop's `attempts` semantics)."
        ),
    )


# ── Aggregator ────────────────────────────────────────────────────────────────


def _title_for_merged(query: str, max_len: int = 120) -> str:
    """Truncate the original user query for use as the merged Report title."""
    collapsed = " ".join(query.split())
    if len(collapsed) <= max_len:
        return collapsed
    return collapsed[: max_len - 1].rstrip() + "…"


def _order_sub_reports(sub_reports: list[SubReport], plan: Plan | None) -> list[SubReport]:
    """Order SubReports by Plan position.

    `Annotated[..., operator.add]` accumulates in completion order under
    LangGraph fan-out, which is non-deterministic. The Plan is the canonical
    order — sub-reports without a Plan match (shouldn't happen in practice)
    fall to the end in stable insertion order.
    """
    if plan is None:
        return list(sub_reports)
    order: dict[str, int] = {sq.text: i for i, sq in enumerate(plan.sub_queries)}
    return sorted(
        sub_reports,
        key=lambda sr: order.get(sr.sub_query.text, len(plan.sub_queries)),
    )


def _dedupe_chunks(sub_reports: list[SubReport]) -> list[ScoredChunk]:
    """Union of every Executor's retrieved chunks, deduped by block_id.

    When two Executors retrieved the same chunk, keep the one with the higher
    score (it's the same content; the higher score is the more informative
    signal about which sub-query it most belonged to). Result ordered by
    descending score so the assembler's downstream contextualisation reads in
    relevance order.
    """
    best: dict[str, ScoredChunk] = {}
    for sr in sub_reports:
        for sc in sr.chunks:
            bid = sc.chunk.block_id
            existing = best.get(bid)
            if existing is None or sc.score > existing.score:
                best[bid] = sc
    return sorted(best.values(), key=lambda sc: sc.score, reverse=True)


def _merged_summary(sub_reports: list[SubReport]) -> str:
    """Concatenate sub-summaries with each one prefixed by its sub-query rationale.

    The rationale prefix lets the reader see which decomposition produced which
    chunk of the overall summary — important for transparency in the structural
    merge (sign-off #4).
    """
    parts = []
    for sr in sub_reports:
        sub_summary = sr.report.summary.strip()
        parts.append(f"{sr.sub_query.rationale.rstrip('.')}: {sub_summary}")
    return "\n\n".join(parts)


def _flatten_claims(sub_report: SubReport) -> list[Claim]:
    return [claim for section in sub_report.report.sections for claim in section.claims]


def aggregate(
    sub_reports: list[SubReport],
    *,
    query: str,
    plan: Plan | None,
) -> tuple[Report, list[ScoredChunk]]:
    """Merge `list[SubReport]` into a single Report + the unioned chunks.

    Per sign-off #4: deterministic structural merge, no LLM call. Layout:
      - title: the original user query (truncated)
      - summary: per-sub-query rationale + sub-summary, joined
      - sections: one section per SubReport (in Plan order), heading = the
        sub-query text, claims = flat union of every claim in that SubReport
      - chunks: union over all Executors' chunks, deduped by block_id

    Atomic case (single SubReport): the SubReport's Report passes through
    unchanged — preserves observational invariance with v0.2.1 for queries
    the Atomizer marked atomic.
    """
    if not sub_reports:
        raise ValueError("aggregate() requires at least one SubReport")

    if len(sub_reports) == 1:
        sr = sub_reports[0]
        return sr.report, list(sr.chunks)

    ordered = _order_sub_reports(sub_reports, plan)
    sections = [
        Section(heading=sr.sub_query.text, claims=_flatten_claims(sr))
        for sr in ordered
        # Drop sub-reports whose every section had zero claims (shouldn't
        # happen — citation.Section enforces min_length=1 — but defensively
        # avoids creating a Section with empty claims, which the schema would
        # reject anyway).
        if any(_flatten_claims(sr))
    ]
    if not sections:
        # Every sub-report was claimless. Surface the first sub-report's Report
        # rather than fabricating; the post-merge verifier will flag the
        # resulting state.
        sr = ordered[0]
        return sr.report, _dedupe_chunks(ordered)

    merged = Report(
        title=_title_for_merged(query),
        summary=_merged_summary(ordered),
        sections=sections,
    )
    return merged, _dedupe_chunks(ordered)


# ── Executor ──────────────────────────────────────────────────────────────────


async def execute_sub_query(
    sub_query: SubQuery,
    *,
    retriever: Retriever,
    store: DuckDBStore,
    client: InferenceClient,
    k: int,
    max_repair_attempts: int,
    skip_alignment: bool,
) -> SubReport:
    """Run a focused sub-query through the v0.2.1 spine (minus assemble).

    Per sign-off #2 and #3 each Executor runs the *full* verify+repair cycle
    against its own retrieved context before emitting a SubReport. Failed
    sub-Reports still surface (with their `verification.failures` populated)
    so the Aggregator + post-merge cycle can react. Dropping silently here
    would hide real signal.

    The repair budget is per-Executor: a runaway sub-query can't exhaust the
    budget of its siblings.
    """
    chunks = await retriever.retrieve(sub_query.text, k=k)
    scores = [sc.score for sc in chunks]
    log.info(
        "executor sub_query=%r k=%d retrieved=%d top_score=%.3f mean_score=%.3f",
        sub_query.text,
        k,
        len(chunks),
        scores[0] if scores else 0.0,
        statistics.fmean(scores) if scores else 0.0,
    )
    initial = await synthesise(sub_query.text, chunks, client)
    outcome = await repair_loop(
        initial,
        sub_query.text,
        chunks,
        store,
        client,
        max_repair_attempts=max_repair_attempts,
        skip_alignment=skip_alignment,
    )
    log.info(
        "executor sub_query=%r attempts=%d pass_rate=%.2f failures=%d",
        sub_query.text,
        outcome.attempts,
        outcome.verification.pass_rate,
        len(outcome.verification.failures),
    )
    return SubReport(
        sub_query=sub_query,
        chunks=chunks,
        report=outcome.report,
        verification=outcome.verification,
        attempts=outcome.attempts,
    )


# ── Planner ───────────────────────────────────────────────────────────────────


async def plan(
    query: str,
    client: InferenceClient,
    *,
    max_sub_queries: int = PLANNER_FANOUT_CAP,
) -> Plan:
    """Ask the synthesis model to decompose `query` into <= PLANNER_FANOUT_CAP sub-queries.

    Runs on the synthesis model (per sign-off — Planner mistakes are expensive
    and we want the better model). JSON-mode + Pydantic + repair-on-invalid
    happens inside `inference.complete()`.
    """
    messages = build_planner_messages(
        query,
        max_sub_queries=max_sub_queries,
        planner_fanout_cap=PLANNER_FANOUT_CAP,
        plan_schema=Plan.model_json_schema(),
    )
    planned = await client.complete(messages, response_model=Plan)
    return Plan(sub_queries=planned.sub_queries[:max_sub_queries])


# ── Atomizer ──────────────────────────────────────────────────────────────────


async def atomize(query: str, client: InferenceClient) -> AtomizerVerdict:
    """Ask the judge model whether the query needs decomposition.

    Per sign-off #5 the Atomizer runs on the judge model (small + fast).
    JSON-mode + Pydantic validation + repair-on-invalid happens inside
    `inference.complete()` — content quality is the model's problem; the
    schema is enforced here.
    """
    messages = build_atomizer_messages(query)
    judge_model = model_for_task(client.config, InferenceTask.JUDGE)
    return await client.complete(
        messages,
        response_model=AtomizerVerdict,
        model=judge_model,
    )


def resolve_decompose(
    override: Literal["auto"] | bool,
    verdict: AtomizerVerdict | None,
) -> bool:
    """Combine the API-level override with the Atomizer's verdict.

    "auto" → use the verdict (must be present).
    True/False → use the override; verdict may be None.
    """
    if override == "auto":
        if verdict is None:
            raise ValueError("decompose_override='auto' requires the Atomizer to have run")
        return verdict.decompose
    return bool(override)


__all__ = [
    "AtomizerVerdict",
    "PLANNER_FANOUT_CAP",
    "Plan",
    "SubQuery",
    "SubReport",
    "aggregate",
    "atomize",
    "execute_sub_query",
    "plan",
    "resolve_decompose",
]
