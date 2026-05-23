"""LangGraph state machine for deep research (ADR-0010, ADR-0020, ADR-0021).

v0.2.1: linear graph `retrieve → synth → verify → repair → assemble`
v0.2.2: ROMA decomposition layered on top. See `docs/v0.2.2_ROMA_PLAN.md` for
the design + sign-off record.

Flow shape (v0.2.2):

    START
      ↓
    atomize            (LLM on judge model; sets `decompose` decision)
      ↓ conditional
      ├─ decompose=True  → plan        (LLM on synth model; emits Plan)
      │                    ↓ conditional (Send fan-out, one per SubQuery)
      │                  execute  ... execute  ... execute
      │                    ↓ reducer-merged into ResearchState.sub_reports
      └─ decompose=False → execute     (single Send, sub_query = original query)
                            ↓
                          aggregate    (deterministic merge → single Report)
                            ↓
                          verify       (post-merge; catches cross-Report drift)
                            ↓ conditional
                          ┌─→ repair → verify (bounded retry)
                          └─→ assemble → END

Per sign-off:
  - Atomizer is an LLM call on the judge model, not a heuristic (#5).
  - Each Executor runs the full per-Executor verify+repair cycle before
    emitting its SubReport (#2, #3). The post-merge cycle runs as well to
    catch cross-Report inconsistencies — bought with the cost of running
    verify twice on atomic queries.
  - Aggregator is a deterministic structural merge — no LLM call (#4).
  - User can override the Atomizer via `decompose: bool | "auto"` on the
    `/research` API (#7); the resolved decision lives in `state["decompose"]`.

Heavy dependencies (`store`, `client`, `retriever`) are injected via
`RunnableConfig.configurable` — they aren't serialisable state.
"""

from __future__ import annotations

import operator
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Annotated, Any, Callable, Literal, TypedDict

from citation import (
    Report,
    VerificationReport,
    assemble,
    chunks_for_context,
    verify_report,
)
from citation.synth import build_messages
from inference import InferenceClient, Message
from langchain_core.runnables import RunnableConfig
from langgraph.graph import END, START, StateGraph
from langgraph.types import Send
from retrieval import DuckDBStore, Retriever, ScoredChunk

if TYPE_CHECKING:
    from web import WebAdapter

from .roma import (
    AtomizerVerdict,
    Plan,
    SubQuery,
    SubReport,
    aggregate,
    atomize,
    execute_sub_query,
    resolve_decompose,
)
from .roma import (
    plan as plan_query,
)

ATOMIZE = "atomize"
PLAN = "plan"
EXECUTE = "execute"
AGGREGATE = "aggregate"
VERIFY = "verify"
REPAIR = "repair"
ASSEMBLE = "assemble"


class ResearchState(TypedDict, total=False):
    # — inputs (unchanged from v0.2.1) —
    query: str
    k: int
    max_repair_attempts: int
    skip_alignment: bool
    max_sub_queries: int

    # — new in v0.2.2 (ROMA) —
    # User override on the Atomizer decision. "auto" = ask the Atomizer.
    # True/False bypass the Atomizer LLM call entirely.
    decompose_override: Literal["auto"] | bool
    atomizer_verdict: AtomizerVerdict | None  # None when overridden
    decompose: bool  # resolved final decision
    plan: Plan | None  # None when decompose=False

    # Fan-out reducer field. Each Executor (Send-spawned) appends one SubReport
    # via `operator.add`; LangGraph merges concurrent writes into a single list.
    # No reducer = race-condition crash when Send fans out.
    sub_reports: Annotated[list[SubReport], operator.add]

    # — existing (post-Aggregator) —
    chunks: list[ScoredChunk]
    report: Report
    verification: VerificationReport
    convo: list[Message]
    attempts: int
    markdown: str


@dataclass(frozen=True)
class ResearchDeps:
    store: DuckDBStore
    client: InferenceClient
    retriever: Retriever
    web_adapter: WebAdapter | None = field(default=None)


def _deps(config: RunnableConfig) -> ResearchDeps:
    return config["configurable"]["deps"]


def _maybe_progress(config: RunnableConfig, message: str) -> None:
    cb: Callable[[str], None] | None = config.get("configurable", {}).get("on_progress")
    if cb is not None:
        cb(message)


# ── Atomizer node ─────────────────────────────────────────────────────────────


async def _atomize(state: ResearchState, config: RunnableConfig) -> dict[str, Any]:
    _maybe_progress(config, "Analyzing your question…")
    deps = _deps(config)
    override = state.get("decompose_override", "auto")
    if override == "auto":
        verdict = await atomize(state["query"], deps.client)
    else:
        # Skip the LLM call entirely when the API caller overrode the decision.
        verdict = None
    decompose = resolve_decompose(override, verdict)
    return {"atomizer_verdict": verdict, "decompose": decompose}


def _route_after_atomize(state: ResearchState) -> str | list[Send]:
    """Decompose → Planner. Atomic → single-Send fan-out to Executor."""
    if state["decompose"]:
        return PLAN
    # Atomic case: skip planner, run one Executor with the original query as
    # its sub-query. Keeps a uniform downstream pipeline.
    atomic_sub_query = SubQuery(
        text=state["query"],
        rationale="atomic — Atomizer/override said no decomposition needed",
    )
    return [Send(EXECUTE, _executor_payload(state, atomic_sub_query))]


# ── Planner node + fan-out ────────────────────────────────────────────────────


async def _plan(state: ResearchState, config: RunnableConfig) -> dict[str, Any]:
    _maybe_progress(config, "Planning sub-questions…")
    deps = _deps(config)
    p = await plan_query(state["query"], deps.client, max_sub_queries=state["max_sub_queries"])
    return {"plan": p}


def _fanout_from_plan(state: ResearchState) -> list[Send]:
    """One Send per SubQuery — parallel Executor invocations."""
    plan_obj = state["plan"]
    if plan_obj is None:
        raise ValueError("_fanout_from_plan invoked without a Plan in state")
    return [Send(EXECUTE, _executor_payload(state, sq)) for sq in plan_obj.sub_queries]


def _executor_payload(state: ResearchState, sub_query: SubQuery) -> dict[str, Any]:
    """Build the payload dict that becomes the Executor invocation's state.

    Send payloads bypass the parent ResearchState — the Executor only sees
    what we pack here. Forward the budget/skip knobs so per-Executor
    repair_loop respects the same user-facing settings.
    """
    return {
        "sub_query": sub_query,
        "k": state["k"],
        "max_repair_attempts": state["max_repair_attempts"],
        "skip_alignment": state["skip_alignment"],
    }


# ── Executor node ─────────────────────────────────────────────────────────────


async def _execute(payload: dict[str, Any], config: RunnableConfig) -> dict[str, Any]:
    """One Executor invocation — runs in parallel with siblings via Send.

    `payload` is what `_executor_payload` packed — NOT the parent state. The
    write-back goes through the parent state's `sub_reports` reducer
    (`Annotated[list[SubReport], operator.add]`) so concurrent Executors
    don't race.
    """
    sub_query_text = payload["sub_query"].text
    preview = sub_query_text[:60] + "…" if len(sub_query_text) > 60 else sub_query_text
    _maybe_progress(config, f"Researching: {preview}")
    deps = _deps(config)
    sub_report = await execute_sub_query(
        payload["sub_query"],
        retriever=deps.retriever,
        store=deps.store,
        client=deps.client,
        k=payload["k"],
        max_repair_attempts=payload["max_repair_attempts"],
        skip_alignment=payload["skip_alignment"],
        web_adapter=deps.web_adapter,
    )
    return {"sub_reports": [sub_report]}


# ── Aggregator node ───────────────────────────────────────────────────────────


def _aggregate(state: ResearchState, config: RunnableConfig) -> dict[str, Any]:
    _maybe_progress(config, "Combining results…")
    sub_reports = state.get("sub_reports") or []
    merged_report, merged_chunks = aggregate(
        sub_reports,
        query=state["query"],
        plan=state.get("plan"),
    )
    # Seed verification + attempts from the atomic case's per-Executor outcome
    # so `ResearchResult.verification` / `.attempts` keep their v0.2.1
    # semantics when no decomposition happened. For decomposed queries the
    # post-merge verify+repair cycle overwrites these.
    if len(sub_reports) == 1:
        only = sub_reports[0]
        verification = only.verification
        attempts = only.attempts
        # No convo needed — post-merge repair is skipped in the atomic case
        # (the per-Executor cycle was authoritative; re-running verify on the
        # same Report against the same chunks would be wasted work).
        convo: list[Message] = []
    else:
        # Decomposed path: post-merge cycle starts fresh.
        verification = None  # type: ignore[assignment]
        attempts = 1
        # Seed the post-merge repair convo with synth-prompt-on-merged-context.
        convo = list(build_messages(state["query"], merged_chunks))
    out: dict[str, Any] = {
        "report": merged_report,
        "chunks": merged_chunks,
        "convo": convo,
        "attempts": attempts,
    }
    if verification is not None:
        out["verification"] = verification
    return out


def _route_after_aggregate(state: ResearchState) -> str:
    """Atomic → straight to assemble. Decomposed → post-merge verify cycle.

    Sign-off #2 wanted post-Aggregator verify to catch cross-Report drift.
    In the atomic case there's only one Report so there's nothing to cross-
    check; running verify+repair again is pure waste. Skipping it here
    preserves v0.2.1's observational invariance for atomic queries.
    """
    if len(state.get("sub_reports") or []) <= 1:
        return ASSEMBLE
    return VERIFY


# ── Verify / Repair / Assemble (lifted from v0.2.1, unchanged behaviour) ──────


async def _verify(state: ResearchState, config: RunnableConfig) -> dict[str, Any]:
    _maybe_progress(config, "Verifying citations…")
    deps = _deps(config)
    verification = await verify_report(
        state["report"],
        deps.store,
        deps.client,
        skip_alignment=state["skip_alignment"],
    )
    return {"verification": verification}


def _route_after_verify(state: ResearchState) -> str:
    verification = state["verification"]
    if not verification.failures:
        return ASSEMBLE
    if state["attempts"] > state["max_repair_attempts"]:
        return ASSEMBLE
    return REPAIR


async def _repair(state: ResearchState, config: RunnableConfig) -> dict[str, Any]:
    """One post-merge repair attempt — same body as v0.2.1's `_repair`."""
    _maybe_progress(config, "Correcting citation issues…")
    deps = _deps(config)
    report = state["report"]
    failures = state["verification"].failures
    convo: list[Message] = [
        *state["convo"],
        {"role": "assistant", "content": report.model_dump_json()},
        {"role": "user", "content": _failure_brief(failures)},
    ]
    new_report = await deps.client.complete(
        convo,
        response_model=Report,
        max_repair_attempts=1,  # schema fixup; semantic loop is THIS graph
    )
    return {
        "report": new_report,
        "convo": convo,
        "attempts": state["attempts"] + 1,
    }


def _assemble(state: ResearchState, config: RunnableConfig) -> dict[str, Any]:
    _maybe_progress(config, "Assembling your report…")
    deps = _deps(config)
    markdown = assemble(state["report"], chunks_for_context(deps.store, state["report"]))
    return {"markdown": markdown}


def _failure_brief(failures: list) -> str:
    # Kept inline so the graph module is self-contained; the citation
    # package's own brief lives in `citation.repair` and is identical.
    lines = [
        "Your previous report had the following verification failures. Produce a "
        "new report that fixes every one of them. You may drop a claim if you "
        "cannot ground it, but you must NOT keep the broken version.",
        "",
    ]
    for i, f in enumerate(failures, 1):
        bid = f.block_id or "(none)"
        lines.append(f"[{i}] section=`{f.section_heading}` block_id=`{bid}` kind={f.kind.value}")
        lines.append(f"    claim: {f.claim_text}")
        lines.append(f"    why:   {f.detail}")
    return "\n".join(lines)


# ── Wiring ────────────────────────────────────────────────────────────────────


def build_research_graph():
    g: StateGraph = StateGraph(ResearchState)
    g.add_node(ATOMIZE, _atomize)
    g.add_node(PLAN, _plan)
    g.add_node(EXECUTE, _execute)
    g.add_node(AGGREGATE, _aggregate)
    g.add_node(VERIFY, _verify)
    g.add_node(REPAIR, _repair)
    g.add_node(ASSEMBLE, _assemble)

    g.add_edge(START, ATOMIZE)
    g.add_conditional_edges(ATOMIZE, _route_after_atomize, [PLAN, EXECUTE])
    g.add_conditional_edges(PLAN, _fanout_from_plan, [EXECUTE])
    g.add_edge(EXECUTE, AGGREGATE)
    g.add_conditional_edges(AGGREGATE, _route_after_aggregate, [VERIFY, ASSEMBLE])
    g.add_conditional_edges(VERIFY, _route_after_verify, {REPAIR: REPAIR, ASSEMBLE: ASSEMBLE})
    g.add_edge(REPAIR, VERIFY)
    g.add_edge(ASSEMBLE, END)
    return g.compile()


_GRAPH = build_research_graph()


async def run_research_graph(
    query: str,
    *,
    deps: ResearchDeps,
    k: int,
    max_repair_attempts: int,
    skip_alignment: bool,
    max_sub_queries: int,
    decompose: Literal["auto"] | bool = "auto",
    on_progress: Callable[[str], None] | None = None,
) -> ResearchState:
    initial: ResearchState = {
        "query": query,
        "k": k,
        "max_repair_attempts": max_repair_attempts,
        "skip_alignment": skip_alignment,
        "max_sub_queries": max_sub_queries,
        "decompose_override": decompose,
        "sub_reports": [],  # reducer needs a starting list
    }
    final = await _GRAPH.ainvoke(
        initial,
        config={
            "configurable": {"deps": deps, "on_progress": on_progress},
            "max_concurrency": 1,
        },
    )
    return final  # type: ignore[return-value]
