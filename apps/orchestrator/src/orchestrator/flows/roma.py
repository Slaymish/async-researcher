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

import hashlib
import logging
import re
import statistics
from collections.abc import Callable
from typing import TYPE_CHECKING, Literal

from citation import Report, VerificationReport, repair_loop, synthesise
from citation.schema import Claim, Section
from inference import InferenceClient, InferenceTask, model_for_task
from pydantic import BaseModel, ConfigDict, Field
from retrieval import Chunk, DuckDBStore, Retriever, ScoredChunk

from ..prompts import build_atomizer_messages, build_planner_messages

if TYPE_CHECKING:
    from web import WebAdapter

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
    target: Literal["vault", "web"] = Field(
        default="vault",
        description=(
            "Where this sub-query will be routed. 'vault' = local knowledge base. "
            "'web' = live search + fetch via SearXNG/DDGS + Crawl4AI (ADR-0018). "
            "Web chunks are indexed in DuckDB with a web:// prefix (ADR-0019)."
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


# ── Web chunking helpers (used by the web Executor path) ─────────────────────

_WEB_PREFIX = "web://"
_HEADING_RE = re.compile(r"^#{1,6}\s", re.MULTILINE)
_MIN_CHUNK_CHARS = 100
_MAX_CHUNK_CHARS = 1400
_MAX_CHUNKS_PER_DOC = 15


def _web_block_id(url: str, idx: int, text: str) -> str:
    key = f"{url}\x00{idx}\x00{text.strip()}"
    return "ai-" + hashlib.blake2b(key.encode(), digest_size=6).hexdigest()


def _url_to_relpath(url: str) -> str:
    for scheme in ("https://", "http://"):
        if url.startswith(scheme):
            return _WEB_PREFIX + url[len(scheme):]
    return _WEB_PREFIX + url


def _split_web_markdown(content: str) -> list[str]:
    """Split fetched Markdown into indexable chunks on heading/paragraph boundaries."""
    boundaries = [m.start() for m in _HEADING_RE.finditer(content)]
    sections: list[str] = []
    for i, start in enumerate(boundaries):
        end = boundaries[i + 1] if i + 1 < len(boundaries) else len(content)
        sections.append(content[start:end].strip())
    if not sections:
        sections = [content.strip()]

    chunks: list[str] = []
    for section in sections:
        if len(section) <= _MAX_CHUNK_CHARS:
            if len(section) >= _MIN_CHUNK_CHARS:
                chunks.append(section)
        else:
            for para in section.split("\n\n"):
                para = para.strip()
                if len(para) >= _MIN_CHUNK_CHARS:
                    chunks.append(para[:_MAX_CHUNK_CHARS])
        if len(chunks) >= _MAX_CHUNKS_PER_DOC:
            break
    return chunks or ([content.strip()[:_MAX_CHUNK_CHARS]] if content.strip() else [])


async def _index_web_doc(
    url: str, content: str, store: DuckDBStore, client: InferenceClient
) -> list[Chunk]:
    """Chunk, embed, and upsert a fetched MarkdownDoc into DuckDB. ADR-0019."""
    if not content.strip():
        return []
    texts = _split_web_markdown(content)
    if not texts:
        return []
    embeddings = await client.embed(texts)
    relpath = _url_to_relpath(url)
    chunks: list[Chunk] = []
    line = 0
    for i, (text, emb) in enumerate(zip(texts, embeddings, strict=False)):
        line_count = text.count("\n") + 1
        chunks.append(Chunk(
            block_id=_web_block_id(url, i, text),
            relpath=relpath,
            kind="web-paragraph",
            text=text,
            line_start=line,
            line_end=line + line_count,
            frontmatter={"url": url},
            embedding=emb,
        ))
        line += line_count
    store.upsert_chunks(chunks)
    return chunks


# ── Executor ──────────────────────────────────────────────────────────────────


async def execute_sub_query(
    sub_query: SubQuery,
    *,
    retriever: Retriever,
    store: DuckDBStore,
    client: InferenceClient,
    synthesis_client: InferenceClient | None = None,
    k: int,
    max_repair_attempts: int,
    skip_alignment: bool,
    web_adapter: WebAdapter | None = None,
    on_event: Callable[[dict], None] | None = None,
) -> SubReport:
    """Run a focused sub-query through the v0.2.1 spine (minus assemble).

    For vault sub-queries: retrieve → synth → verify+repair (unchanged).
    For web sub-queries: search → fetch → index in DuckDB → retrieve → synth → verify+repair.

    `client` is always used for embeddings. `synthesis_client` (if provided) is
    used for synthesis/repair LLM calls; otherwise falls back to `client`.

    Per sign-off #2 and #3 each Executor runs the *full* verify+repair cycle
    before emitting its SubReport. Failed sub-Reports still surface so the
    Aggregator + post-merge cycle can react.
    """
    synth = synthesis_client if synthesis_client is not None else client
    if sub_query.target == "web":
        chunks = await _execute_web(
            sub_query,
            store=store,
            client=client,
            retriever=retriever,
            k=k,
            web_adapter=web_adapter,
            on_event=on_event,
        )
    else:
        chunks = await retriever.retrieve(sub_query.text, k=k)

    scores = [sc.score for sc in chunks]
    # `score` on Retriever output is cosine similarity vs the query
    # (see retrieval.hybrid module docstring). RRF is used internally
    # for ordering only.
    log.info(
        "executor target=%s sub_query=%r k=%d retrieved=%d top_cos=%.3f mean_cos=%.3f",
        sub_query.target,
        sub_query.text,
        k,
        len(chunks),
        scores[0] if scores else 0.0,
        statistics.fmean(scores) if scores else 0.0,
    )
    initial = await synthesise(sub_query.text, chunks, synth)
    outcome = await repair_loop(
        initial,
        sub_query.text,
        chunks,
        store,
        synth,
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


async def _execute_web(
    sub_query: SubQuery,
    *,
    store: DuckDBStore,
    client: InferenceClient,
    retriever: Retriever,
    k: int,
    web_adapter: WebAdapter | None,
    on_event: Callable[[dict], None] | None = None,
) -> list[ScoredChunk]:
    """Search, fetch, index, then retrieve for a web-targeted sub-query.

    Falls back to vault retrieval if the web adapter is absent or search/fetch
    yields nothing — ensures the Executor always returns *some* chunks to synth.
    """
    if web_adapter is None:
        log.warning(
            "sub_query.target='web' but WebAdapter is not configured; "
            "falling back to vault retrieval for %r",
            sub_query.text,
        )
        return await retriever.retrieve(sub_query.text, k=k)

    hits = await web_adapter.search(sub_query.text, k=web_adapter.max_fetch_urls)
    log.info("web search %r → %d hits", sub_query.text, len(hits))
    if on_event and hits:
        on_event({
            "type": "web_search",
            "sub_query": sub_query.text,
            "hits": [{"url": h.url, "title": h.title} for h in hits[:8]],
        })

    indexed_count = 0
    for hit in hits:
        if not hit.url:
            continue
        if on_event:
            on_event({
                "type": "web_fetch",
                "sub_query": sub_query.text,
                "url": hit.url,
                "title": hit.title,
            })
        doc = await web_adapter.fetch(hit.url)
        if not doc.content.strip():
            log.debug("empty fetch for %s", hit.url)
            if on_event:
                on_event({
                    "type": "web_fetch_done",
                    "sub_query": sub_query.text,
                    "url": hit.url,
                    "chunks": 0,
                })
            continue
        new_chunks = await _index_web_doc(hit.url, doc.content, store, client)
        indexed_count += len(new_chunks)
        if on_event:
            on_event({
                "type": "web_fetch_done",
                "sub_query": sub_query.text,
                "url": hit.url,
                "chunks": len(new_chunks),
            })

    log.info("web executor indexed %d chunks for %r", indexed_count, sub_query.text)

    # Retrieve from the now-enriched index (mixed vault + web).
    return await retriever.retrieve(sub_query.text, k=k)


# ── Planner ───────────────────────────────────────────────────────────────────


async def plan(
    query: str,
    client: InferenceClient,
    *,
    max_sub_queries: int = PLANNER_FANOUT_CAP,
    memory_facts: list[str] | None = None,
    source_filter: str = "auto",
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
        memory_facts=memory_facts,
        source_filter=source_filter,
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
