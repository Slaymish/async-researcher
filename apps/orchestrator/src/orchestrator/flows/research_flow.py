"""Deep-research flow.

v0.1: flat function `research(query) -> ResearchResult`.
v0.2: same signature, internals replaced with LangGraph (ADR-0010, ADR-0020).

The signature is the contract. The body delegates to `graph.py` so that
deliverable 2 (ROMA decomposition) can extend the graph without touching
the public interface or any caller.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Callable, Literal

from citation import Report, VerificationReport
from inference import InferenceClient
from retrieval import DuckDBStore, Retriever

from .graph import ResearchDeps, run_research_graph
from .roma import PLANNER_FANOUT_CAP, AtomizerVerdict, SubReport

if TYPE_CHECKING:
    from memory import Memory
    from web import WebAdapter


@dataclass(frozen=True)
class ResearchResult:
    query: str
    report: Report
    markdown: str
    verification: VerificationReport
    attempts: int
    k: int
    # v0.2.2 additions. These surface decomposition + per-Executor outcomes to
    # the route layer so the plugin can render the diagnostic shim (step 8).
    atomizer_verdict: AtomizerVerdict | None = None
    sub_reports: tuple[SubReport, ...] = ()


async def research(
    query: str,
    *,
    store: DuckDBStore,
    client: InferenceClient,
    retriever: Retriever | None = None,
    web_adapter: WebAdapter | None = None,
    memory: Memory | None = None,
    k: int = 20,
    max_repair_attempts: int = 2,
    skip_alignment: bool = False,
    decompose: Literal["auto"] | bool = "auto",
    max_sub_queries: int = PLANNER_FANOUT_CAP,
    on_progress: Callable[[str], None] | None = None,
) -> ResearchResult:
    """Deep research: atomize → (plan → fan-out)? → execute → aggregate → verify+repair → assemble.

    `decompose` controls the Atomizer:
      - "auto" (default): the Atomizer LLM call decides.
      - True / False: skip the Atomizer and force the decision.
    """
    deps = ResearchDeps(
        store=store,
        client=client,
        retriever=retriever or Retriever(store, client),
        web_adapter=web_adapter,
        memory=memory,
    )
    final = await run_research_graph(
        query,
        deps=deps,
        k=k,
        max_repair_attempts=max_repair_attempts,
        skip_alignment=skip_alignment,
        max_sub_queries=max_sub_queries,
        decompose=decompose,
        on_progress=on_progress,
    )
    return ResearchResult(
        query=query,
        report=final["report"],
        markdown=final["markdown"],
        verification=final["verification"],
        attempts=final["attempts"],
        k=k,
        atomizer_verdict=final.get("atomizer_verdict"),
        sub_reports=tuple(final.get("sub_reports") or ()),
    )
