# Decision Log

## Purpose

Append-only record of architectural decisions. One entry per genuine choice between alternatives — not every default, not every minor convention. The bar: *would future-me, six months from now, ask "why did we do it this way?"* If yes, write the ADR.

## Format

```
## ADR-XXXX — Title
Date: YYYY-MM-DD
Status: accepted | superseded by ADR-YYYY | deprecated

Context.        What forced the decision? What were the constraints?
Decision.       What was chosen.
Alternatives.   What was rejected and why.
Consequences.   What this enables, what it costs, what it locks in.
```

Status transitions: never delete an ADR. Mark it `superseded` and write a new one. The history of decisions matters more than the current state.

---

## ADR-0001 — Use lightweight ADR format for this log
Date: 2026-05-17
Status: accepted

**Context.** Planning docs (`00`–`04`) make many architectural calls. Without a log, the *why* is lost as the docs evolve.
**Decision.** Maintain `05_DECISIONS.md` as an append-only ADR log. Decisions made in other planning docs are restated here at the point of decision.
**Alternatives.** No log (lose context); per-decision files in `docs/adr/` (overkill at this scale).
**Consequences.** Adds friction to every architectural call. Worth it because the prototype will outlast the planning conversation.

---

## ADR-0002 — Treat both specs as buildable as written
Date: 2026-05-17
Status: accepted

**Context.** `ArchitectureSpecification.md` and `LocalAgenticRAGArch.md` describe components ranging from production-ready (LightRAG, LangGraph) to research-grade or speculative (RecursiveMAS latent thought compression, Microsoft AGT with sub-millisecond guarantees). The user explicitly chose to plan as if everything is real.
**Decision.** Component map and roadmap take spec claims at face value. Verification happens at implementation time, per component, not in planning.
**Alternatives.** Reality-check every spec component upfront (rejected by user as adding friction; also slower).
**Consequences.** Higher risk that deferred components (Phase 7, 8, Backlog) hit dead ends. Mitigation: phased gates with entry criteria force a check before commitment. Components are accessed through adapters, so a dead-end implementation can be swapped without rewriting consumers.

---

## ADR-0003 — MVP is the Obsidian plugin slice, not the broader AI OS
Date: 2026-05-17
Status: accepted

**Context.** Specs describe two systems: a Personal AI OS (the broader vision) and a deep-research plugin (the knowledge-node implementation). User asked for help choosing the MVP. The plugin slice includes both proactive surfacing and deep research as co-equal pillars (see ADR-0004).
**Decision.** The Obsidian plugin slice (surfacing + deep research) is v0.1. The broader OS is **deferred across multiple later phases, not all to Phase 8**: ROMA decomposition lands in v0.2, basic n8n flows in v0.3, GPU inference in Phase 7, and A2A/MCP/AGT governance in Phase 8.
**Alternatives.** Start with the autonomous daemon (deferred to v0.3); start with inference infrastructure (deferred to Phase 7 because Mac-first delays its value).
**Consequences.** The OS spec's grander claims (latent compression, RecursiveMAS) defer to the backlog indefinitely. The plugin slice is enough to validate the foundational hypotheses cheaply. The broader OS is built *on top of* a working plugin, not in parallel.

---

## ADR-0004 — Two equal headline capabilities: proactive surfacing + deep research
Date: 2026-05-17
Status: accepted

**Context.** Initial vision draft demoted deep research below proactive surfacing. User pushed back: both must be first-class.
**Decision.** Vision and MVP scope treat surfacing and research as co-equal pillars. Both ship in v0.1.
**Alternatives.** Surfacing-only v0.1 (faster, but skips citation engine validation); research-only v0.1 (faster, but misses the dream interaction).
**Consequences.** Slightly larger v0.1. Justifiable because both pillars share substrate — ingestion, retrieval, citation, inference — so the marginal cost of adding the second pillar is the UI surface plus the side panel, not a second backend.

---

## ADR-0005 — Local inference only for this system's direct LLM calls
Date: 2026-05-17
Status: accepted

**Context.** User identified local-inference as a non-negotiable boundary in vision Q&A. The project is sovereignty-first. Originally framed as "vault contents never leave the machine," but Phase 8's MCP server exposes vault retrieval to external clients (e.g., Claude Desktop, Codex) that may themselves be cloud-backed — creating a transitive exposure question.
**Decision.** **All LLM inference originated by this system runs on local hardware** (Mac in v0.1, GPU box in Phase 7). No code path inside this codebase sends vault content to a cloud LLM API. Public-web fetches (Crawl4AI in v0.2) are allowed because they read external content, not vault content. **Scope of this ADR is limited to direct calls made by this system.** External MCP/A2A clients (Phase 8) are *not* governed by this ADR; the user chooses which clients to connect, and the user accepts that vault content reaching a cloud-backed external client may transit that client's chosen cloud LLM. Per-client policy lives outside this ADR.
**Alternatives.** Hybrid (cloud for synthesis, local for embedding) — rejected. Cloud fallback when local is slow — rejected. Tighter framing covering transitive exposure via external clients — rejected by user as overly restrictive of Phase 8 interoperability.
**Consequences.** Synthesis quality is capped by what runs on local hardware. Drives the Phase 7 GPU-box plan. Eliminates an entire class of design choices for this system's direct calls (provider routing, cost optimisation, prompt-leakage mitigation). All inference goes through one adapter (ADR-0009) to enforce this at one chokepoint. Phase 8 MCP integration explicitly accepts that the *user* may route vault content into cloud LLMs by their choice of external client; this is a deliberate trade for interoperability.

---

## ADR-0006 — Python for the backend; TypeScript only for the Obsidian plugin
Date: 2026-05-17
Status: accepted

**Context.** Most named components (LightRAG, Mem0, Crawl4AI, LangGraph, vLLM) have Python as their primary or only binding. Obsidian's plugin API is TS-only.
**Decision.** Backend, packages, eval harness all Python 3.12+. Plugin is TypeScript. No third language.
**Alternatives.** Rust or Go for a hot path (deferred until measurement forces it). Full TS stack with Node bindings to Python tools (rejected — fragile bridges, smaller ecosystem).
**Consequences.** Python's GIL and runtime overhead are accepted. Cross-language complexity is paid only at the one plugin↔backend boundary, which is HTTP — already a network call, no FFI tax.

---

## ADR-0007 — Monolithic in-process orchestrator in v0.1; defer microservices
Date: 2026-05-17
Status: accepted

**Context.** v0.1 is single-user, single-machine. Microservices, message queues, and service discovery solve problems v0.1 doesn't have.
**Decision.** One FastAPI process imports every `packages/*` module in-process. No Redis, no Celery, no gRPC. The autonomous daemon (v0.3) is a second startup mode of the same codebase, not a separate service.
**Alternatives.** Service-per-package from day one (rejected — premature). Background worker via Celery + Redis (rejected — single-user load doesn't justify the operational cost).
**Consequences.** Locks in a single-machine assumption that becomes a real refactor at Phase 8 when external A2A clients arrive. Acceptable trade — Phase 8 is gated on a concrete external use case, so the refactor will have a clear ROI by the time it's needed.

---

## ADR-0008 — `uv` for Python, `pnpm` for TypeScript, no monorepo framework
Date: 2026-05-17
Status: accepted

**Context.** Two languages, multiple packages each, need a workspace story. Monorepo frameworks (Nx, Turborepo, Bazel) solve problems at much larger scale.
**Decision.** `uv` workspaces for Python, `pnpm` workspaces for TS. A top-level `Makefile` wraps both. No unified monorepo tool.
**Alternatives.** Nx (cross-language but heavy); Bazel (industrial-strength, hostile DX for prototypes); Poetry/PDM/Hatch (slower than `uv`, no clear win).
**Consequences.** Cross-language commands require two underlying invocations. Trivial at this scale. Easy to migrate to a real monorepo tool later if it becomes warranted.

---

## ADR-0009 — Single OpenAI-compatible inference adapter as the only LLM call path
Date: 2026-05-17
Status: accepted

**Context.** v0.1 uses Ollama on Mac. Phase 7 swaps to llama-swap+vLLM on a GPU box. Phase 8 may introduce model routing per-task. If every component calls its own model client, every swap is a multi-file change.
**Decision.** All LLM calls in the codebase go through `packages/inference/client.py`. The client speaks the OpenAI HTTP API. Backend URL is a single config value.
**Alternatives.** Direct Ollama-Python bindings in callers (rejected — locks in Ollama). LangChain's model abstractions (rejected — heavy dep for one chokepoint).
**Consequences.** Migrating from Ollama to llama-swap is a config change. Every model provider (current and future) must implement the OpenAI API surface or be wrapped to match. Cost: a thin adapter layer for any provider that doesn't speak OpenAI natively.

---

## ADR-0010 — LangGraph as orchestrator when one is needed (v0.2+); flat function in v0.1
Date: 2026-05-17
Status: accepted

**Context.** `LocalAgenticRAGArch.md` benchmarks (Table 1) place LangGraph at the lowest latency and best token efficiency for state-machine flows compared to LangChain, AutoGen, CrewAI.
**Decision.** When the orchestrator gains real state-machine structure in v0.2, it's LangGraph. v0.1 ships without — a flat Python function behind the same `research()` signature. The signature is the contract; the body changes.
**Alternatives.** AutoGen (rejected — conversational overhead per spec). CrewAI (rejected — heaviest profile per spec). Custom state machine (rejected — reinvents LangGraph badly).
**Consequences.** v0.2 swap should be invisible to callers if the v0.1 signature is well-designed. Couples the orchestrator to LangGraph's API; replaceable later but with rewrite cost.

---

## ADR-0011 — Hybrid LightRAG + DuckDB retrieval; not pure GraphRAG, not pure vector
Date: 2026-05-17
Status: accepted

**Context.** Spec argues GraphRAG is too expensive for incremental updates, pure vector loses topological intelligence of Obsidian's link graph.
**Decision.** LightRAG handles entities and relations with cheap incremental updates. DuckDB handles vector similarity and metadata filtering via SQL. A fusion layer in `packages/retrieval/hybrid.py` merges both. Both indices share `^id` as their join key.
**Alternatives.** Pure DuckDB / LanceDB / embedded vector (rejected — no graph traversal). Standard GraphRAG via Microsoft's library (rejected — expensive reindex per spec). Milvus, Weaviate, Pinecone (rejected — deployment overhead for single-user).
**Consequences.** Two indices to maintain. Mitigation: both rebuilt by `packages/ingestion/pipeline.py`, both incremental. Hybrid fusion is a quality unknown; eval harness explicitly tests "hybrid beats vector-only" as hypothesis 2.

---

## ADR-0012 — `^id` block identifier as the universal data-flow token
Date: 2026-05-17
Status: accepted

**Context.** The deterministic citation claim hinges on every claim mapping to a specific block. If chunks lose `^id`s in transit between components, citation breaks.
**Decision.** Every data structure that carries a chunk of vault content carries its `^id`. No component is permitted to strip `^id`s. Both LightRAG nodes and DuckDB chunks store `^id` as a primary field. The citation engine's verifier is the ultimate enforcement: a claim without a resolvable `^id` fails verification.
**Alternatives.** File-path + offset (rejected — brittle under edits). Content hash (rejected — invalidated by trivial whitespace changes). Embedding similarity matching at citation time (rejected — defeats the determinism claim).
**Consequences.** Ingestion must inject `^id`s into user files (one-time, idempotent). User notes accumulate generated `^id`s — visible in source but invisible in rendered Markdown. Acceptable per Obsidian convention.

---

## ADR-0013 — Deterministic citation via two-stage JSON-then-Markdown pipeline
Date: 2026-05-17
Status: accepted

**Context.** Spec cites empirical evidence that LLM-self-cited citations drop 42% in accuracy as retrieval scales. The headline differentiator of this project is zero-hallucination traceability. The spec (`LocalAgenticRAGArch.md` §"Constrained Decoding and AST Parsing") describes a two-stage flow: constrained JSON generation, then assembly into Markdown, then AST evaluation of the assembled Markdown. The flow needs to be made explicit because "JSON schema" and "AST parser" can otherwise be read as alternative approaches.
**Decision.** Three-stage citation pipeline:
  1. **Generation:** the synthesis model emits JSON conforming to a schema with explicit `claim`/`quote`/`^id` fields. JSON is the wire format from the LLM — it never emits free-form prose directly.
  2. **Assembly:** the orchestrator deterministically renders the JSON into a Markdown report, with citations inlined as `[[note#^id]]` Obsidian backlinks.
  3. **Verification:** an AST parser walks the assembled Markdown to extract claims and their inline citations. For each: a link check confirms the `^id` exists, and a judge-model call confirms the source text supports the claim. Failures trigger a bounded repair loop.
**Alternatives.** Prompt the model to self-cite and trust it (rejected — the failure mode being avoided). RAG-fusion / re-rank only (rejected — improves retrieval, not citation honesty). Single-stage Markdown generation with citations (rejected — no schema enforcement at generation time). Single-stage JSON consumption without Markdown assembly (rejected — loses Obsidian backlink integration and the AST verification surface).
**Consequences.** Synthesis is slower (constrained decoding + per-claim verification). Quality of the verifier judge model becomes a critical dependency. v0.1 measures "citation pass rate ≥95%" as the headline metric. The Markdown assembly step lives in `packages/citation/assemble.py` between `synth.py` (JSON gen) and `ast_parse.py` (verification).

---

## ADR-0014 — Mac-first development; GPU box deferred to Phase 7
Date: 2026-05-17
Status: accepted

**Context.** User has Mac for dev now, plans to add a GPU box later.
**Decision.** v0.1 through v0.3 target macOS + Apple Silicon. Inference is via Ollama or LM Studio. CUDA-specific optimisations (FP8 KV cache, PagedAttention, MLA) are deferred to Phase 7, behind the inference adapter.
**Alternatives.** Wait for GPU box before starting (rejected — delays everything). Develop on cloud GPU instances (rejected — violates ADR-0005). Use MLX as the inference backend (deferred — Ollama is more universal; MLX is a Phase 7 alternative).
**Consequences.** Synthesis quality is capped by Mac-runnable models (~14B class) until Phase 7. v0.1 hypothesis 3 ("a local model is good enough") is the test of whether this cap is acceptable.

---

## ADR-0015 — Phased delivery with hard entry-criteria gates
Date: 2026-05-17
Status: accepted

**Context.** Research prototypes commonly collapse by adding scope mid-build. The roadmap defines six phases; without gating, scope creeps backwards (into the current phase) instead of forward (into the next one).
**Decision.** Each phase has explicit entry criteria in `03_ROADMAP.md`. The next phase does not start until the current phase is delivering daily user value and the listed criteria are met. Drift detection is a planning question, not a coding one.
**Alternatives.** Flexible scope per phase (rejected — same as no gates). Date-locked phases (rejected — single-developer, evenings/weekends pace).
**Consequences.** Some phases will take longer than estimated. Some deliverables will be cut to ship a phase. Accept both. The cost of skipping a gate has historically been worse than the cost of any cut deliverable.

---

## ADR-0016 — Single `config.toml`, secrets via `.env`, no secrets manager until Phase 8
Date: 2026-05-17
Status: accepted

**Context.** Spec recommends HashiCorp Vault for credentials. Single-user single-machine deployment doesn't justify the operational cost.
**Decision.** Configuration in `config.toml` at repo root, gitignored. Secrets (when any exist — v0.1 has none, since local Ollama needs no auth) in `.env`. Vault-grade secret management deferred to Phase 8 only if a real multi-agent scenario demands it.
**Alternatives.** HashiCorp Vault from day one (rejected — overkill). macOS Keychain integration (deferred — useful at some point, not v0.1).
**Consequences.** `.env` files must never be committed. Repo `.gitignore` enforces. Acceptable risk for a single-user prototype.

---

## ADR-0017 — Always-on file watcher for v0.1 ingestion
Date: 2026-05-17
Status: accepted

**Context.** v0.1 proactive surfacing requires reasonably fresh indexes — if the user edits a note, then opens a related note, surfacing should reflect the edit. The original planning had ingestion as a one-shot CLI (stale) or implicitly required a daemon (overlapped scope with the v0.3 autonomous daemon). The MVP scope, project structure, and component map disagreed on which model was correct.
**Decision.** v0.1 ships a **lightweight always-on file watcher** as part of the orchestrator process. The watcher uses `watchdog` (FSEvents on macOS), debounces file-change events, and triggers per-file incremental re-ingestion. Scope is strictly ingestion: re-parse, re-`^id`-inject, re-index. The v0.3 autonomous daemon extends this same watcher with filing, structural-integrity scans, and event-driven workflows — same process, broader responsibilities, no separate codebase.
**Alternatives.** One-shot CLI (rejected — stale indexes; manual re-runs degrade UX). Plugin-triggered re-ingest on save (rejected — couples plugin lifecycle to indexing; breaks when plugin is disabled or Obsidian is closed). Full v0.3 autonomous daemon now (rejected — premature scope expansion; filing logic isn't needed yet).
**Consequences.** One extra long-running process to manage in v0.1 (runs inside the FastAPI orchestrator via asyncio, not a separate OS process). Adds `watchdog` as a v0.1 dependency. v0.3 daemon work becomes an extension, not a from-scratch build.

---

## ADR-0018 — Web search adapter: SearXNG primary, DDGS fallback
Date: 2026-05-17
Status: accepted

**Context.** Roadmap v0.2 calls for a Crawl4AI-based web sub-agent that the Planner can dispatch to as an Executor type. The original wording assumed URLs would arrive from somewhere — but for a real deep-research loop the agent must *find* URLs before *fetching* them. The `local-web-scraping-and-aggregating.md` report (2026-05-17, repo root) made this explicit and surveyed the open-source options: SearXNG (self-hosted Dockerized metasearch over 70+ engines), DDGS (Python library, zero-infrastructure), Whoogle (Google-specific proxy). Commercial APIs (Google Custom Search, Bing) are metered and economically unviable for recursive research loops, and routing vault-derived queries through cloud search providers also sits awkwardly next to ADR-0005's local-first ethos (queries themselves can leak the user's research interests).

**Decision.** v0.2 ships **two complementary search adapters** behind a single `search(query, k) -> list[SearchHit]` interface in `packages/web`:
1. **SearXNG (primary)** when the user has it deployed locally. Docker container, JSON output mode enabled in `settings.yml`, configurable engine weighting. Reached over HTTP from `packages/web`.
2. **DDGS (fallback)** as a pure-Python library dependency. No infrastructure cost; the agent falls back to it when SearXNG is not configured or returns no results. This makes the system usable for a single-developer experimenter without the Docker overhead.

Whoogle is **deferred** to v0.2.x or beyond — useful as a tertiary fallback specifically when SearXNG's Google-via-scraping is throttled and DDGS doesn't carry the desired result. Not load-bearing.

**Alternatives.**
- Direct calls to Google/Bing official APIs (rejected — metered, 100 queries/day free tier on Google CSE collapses immediately under multi-agent recursive research).
- Per-engine scraping in our own code (rejected — exactly what SearXNG already solves at scale; fragile, duplicates maintenance).
- No search layer; let the user paste URLs (rejected — defeats the purpose of an agentic loop and contradicts the v0.2 deliverable wording about parallel Executors).
- Single-adapter (SearXNG only) (rejected — forces every user to run Docker; raises the floor unnecessarily for early experimentation).
- Single-adapter (DDGS only) (rejected — caps query throughput at one provider's rate limits; loses SearXNG's per-engine routing).

**Consequences.** Adds two dependencies to `packages/web` (`ddgs`; SearXNG access is via plain HTTP, no SDK). Adds an optional Docker dependency for SearXNG. Search results are URL+title+snippet triples — these feed into the citation engine as `(url, anchor)` per CLAUDE.md's existing convention, not as `^id`s. The DDGS DHT-network sub-50ms cache claim from the report is **not** load-bearing in our architecture — we treat DDGS as a plain query interface with normal latency expectations.

---

## ADR-0019 — Web-fetched content shares the main DuckDB index, distinguished by relpath prefix
Date: 2026-05-17
Status: accepted

**Context.** v0.2 adds web sub-agent fetching (ADR-0018 + roadmap deliverable 5). The fetched Markdown needs to be indexed so retrieval can return web chunks alongside vault chunks. The `local-web-scraping-and-aggregating.md` report (repo root) describes alternatives: a single persistent index, a separate web-only index, or ephemeral per-research-session vector DBs (`sqlite-vec`) per query. The choice shapes the retriever, the citation engine, and the ops surface.

**Decision.** **Web-fetched content lands in the same DuckDB index used for vault content**, distinguished by a `web://` prefix on the `relpath` column. Specifically:
- Vault chunks: `relpath = "Folder/note.md"` (as today).
- Web chunks: `relpath = "web://<host>/<path>[?query]"`.
- `chunks.block_id` continues to be an `ai-` hash; for web chunks, the hash is over `(url, chunk_index, normalised_text)` — the same shape as ADR-0012, with the URL filling the role of the vault relpath.
- Retrieval consumers can opt-in or opt-out of web content via the existing `relpath_prefix` filter (already implemented in `DuckDBStore.search`) — `relpath_prefix="web://"` for web-only, or omitted for "anything."
- The citation engine renders web chunks as `(url, anchor)` rather than `[[note#^id]]`, using a column or `relpath`-prefix dispatch at render time. The internal `^id` stays uniform.

**Alternatives.**
- *Ephemeral per-research-session sqlite-vec DBs* (rejected — adds cross-DB query plumbing; loses cross-session web cache benefit; orchestrator now manages an unbounded set of small DB files).
- *Separate permanent web DuckDB* (rejected — doubles the operational surface (two DBs to migrate, two to back up, two to maintain dim alignment for) for no clear benefit at v0.2 scale).
- *No web persistence — re-fetch every time* (rejected — burns scrape budget and triggers rate limits faster; can't even build a v0.2 eval set around web sources if they aren't reproducible).

**Consequences.**
- Retrieval scoring is over a mixed corpus. A web chunk's cosine similarity is directly comparable to a vault chunk's because both go through the same embedding model. Users get unified ranking.
- The `relpath` column is now overloaded — it's a vault path OR a URL. Code that assumes `relpath` is a real filesystem path must check the `web://` prefix. The risk surfaces in the ingestion watcher (which must not try to `Path()` web relpaths) and in any future "edit this chunk's file" UX.
- Web chunks bypass ADR-0012's "inject `^id` into the source file" rule — the source file is not under our control. The synthetic `ai-` hash still gives us a stable join key.
- Index size grows with web crawl volume. A future "trim web chunks older than N days" maintenance pass becomes useful; sketched but not built in v0.2.

---

## ADR-0020 — LangGraph swap is a linear graph in v0.2.1; ROMA nodes land in v0.2.2
Date: 2026-05-17
Status: accepted

**Context.** ADR-0010 reserved LangGraph as the orchestrator when one was needed in v0.2. v0.2 roadmap deliverable 1 is the swap itself, deliverable 2 is ROMA decomposition (Atomizer/Planner/Executor/Aggregator). The roadmap is explicit that deliverable 1 ships "no new capabilities — proves the swap is invisible to callers." Two routes were considered: (a) keep the existing `citation.repair_loop` as a black box behind a single LangGraph node (lowest swap risk, highest theatricality — barely uses LangGraph); (b) decompose the existing logic into nodes (`retrieve`, `synthesise`, `verify`, `repair`, `assemble`) wired with a real conditional edge for the verify→repair loop.

**Decision.** Route (b). The graph in `apps/orchestrator/src/orchestrator/flows/graph.py` is intentionally linear in v0.2.1 — no decomposition or parallelism yet — but the verify→repair iteration is a LangGraph `add_conditional_edges` over discrete nodes rather than a hand-rolled while loop. State is a `TypedDict` (`ResearchState`); non-serialisable dependencies (`store`, `client`, `retriever`) are injected via `RunnableConfig.configurable` rather than threaded through state. `citation.repair_loop` stays in the citation package as a public symbol (other callers may want the loop without the graph); the orchestrator no longer uses it.

**Alternatives.**
- *Route (a) — single-node wrapper around repair_loop.* Rejected: defers all real LangGraph integration risk to deliverable 2, where it will be entangled with ROMA scope. Better to take the wiring cost now under a no-capability-change gate.
- *Put `store`/`client` in graph state.* Rejected: they aren't serialisable, aren't data, and would prevent future use of LangGraph checkpointers without a refactor.
- *Skip LangGraph entirely and keep growing the flat function.* Rejected by ADR-0010.

**Consequences.**
- New runtime dep: `langgraph>=0.2.50` (1.2.0 resolved). Inherits `langchain-core` transitively for `RunnableConfig`.
- The `research()` signature in `flows/research_flow.py` is byte-identical to v0.1. The FastAPI route, CLI, and tests didn't change.
- Deliverable 2 (ROMA) becomes additive — the Atomizer node slots in front of `retrieve`; the Planner spawns parallel sub-graphs whose Executors reuse the existing `retrieve`/`synthesise`/`verify` nodes; the Aggregator composes Executor outputs before `assemble`.
- Deliverable 7 (terminal-style execution log) now has discrete node boundaries to stream events at. Without route (b) it would have had nothing to surface.
- `attempts` counting semantics preserved exactly: `attempts == 1` after the initial synth, incremented inside `_repair`, gate is `attempts > max_repair_attempts` (matches v0.1's `attempts <= max_repair_attempts` loop predicate).

---

## ADR-0021 — ROMA decomposition layered on the LangGraph spine (v0.2.2)
Date: 2026-05-17
Status: accepted

**Context.** v0.2.1 (ADR-0020) shipped a linear LangGraph wrapper around the v0.1 `retrieve → synth → verify → repair → assemble` flow. Daily-use feedback after v0.2.1 surfaced two complaints from the user: (a) irrelevant citations dominate long-form queries, and (b) verification failures land in reports. (a) is a retrieval-relevance problem the spec's ROMA framework (`ArchitectureSpecification.md` §1.1) directly addresses via tighter sub-queries; (b) is a synthesis-honesty problem ROMA does not directly fix but for which v0.2.2 adds a diagnostic shim so a future iteration can target the right cause with evidence. Detailed sign-off and the rationale per decision live in `docs/v0.2.2_ROMA_PLAN.md`.

**Decision.** Layer the four ROMA roles on top of the v0.2.1 LangGraph spine as discrete nodes:

- **Atomizer** (`_atomize`) — one LLM call on the **judge model** (`qwen2.5:7b-instruct`) returning `AtomizerVerdict{decompose: bool, rationale: str}`. Bypassed entirely when the `/research` API caller overrides `decompose` to `true`/`false`.
- **Planner** (`_plan`) — one LLM call on the synthesis model returning `Plan{sub_queries: list[SubQuery]}`. Capped at `PLANNER_FANOUT_CAP=5`. Skipped on the atomic path.
- **Executor** (`_execute`, fan-out via `langgraph.types.Send`) — each parallel invocation runs `retrieve → synth → repair_loop` against its own retrieved chunks and emits a `SubReport` carrying its own per-Executor `VerificationReport`. Per-Executor `max_repair_attempts` budget is independent.
- **Aggregator** (`_aggregate`) — deterministic structural merge. One section per sub-query (in Plan order, not completion order), chunks deduped by `block_id` keeping max score, summary concatenates each SubReport's summary prefixed by its sub-query rationale. **Atomic case (1 SubReport) passes through unchanged** to preserve v0.2.1 observational invariance.

The existing `verify → repair → assemble` chain becomes the **post-merge cycle**, running only on the decomposed path (`len(sub_reports) > 1`). For atomic queries the per-Executor verify is authoritative — running verify again would be wasted work since the merged Report = the sub-Report.

The `/research` API gains `decompose: Literal["auto"] | bool = "auto"` (default `"auto"` = LLM-decided). Responses gain `atomizer` and `executions` fields (per-Executor sub_query / rationale / chunks / scores / failures) — the diagnostic shim. The plugin gains a "Decomposition" dropdown and an "Append debug section to reports" toggle.

**Alternatives.**
- *Heuristic Atomizer (regex on query length + conjunctions).* Rejected at sign-off — semantic decisions outperform string heuristics on the user's actual use case (multi-paragraph spec-note inputs via the plugin's "use note as input" feature). 7B judge model latency was accepted.
- *Verify once post-Aggregator only.* Rejected at sign-off — bad sub-Reports would contaminate the merge before being caught. The per-Executor verify+repair cycle catches them early and gives each Executor its own repair budget.
- *Per-Executor verify but no per-Executor repair.* Rejected — failures would propagate up with no recovery attempt at the level that produced them.
- *LLM Aggregator that rewrites the merged Report into single-narrative prose.* Deferred to v0.2.3 — the deterministic merge is transparent (the user sees which sub-query produced what), and if daily use proves it reads poorly we promote then.
- *Recursive ROMA.* Deferred. v0.2.2 is single-level: one Atomizer → one Planner → N flat Executors → one Aggregator. The recursive case in the spec is a v0.2.3+ candidate once we have eval data on the flat case.
- *Skip the diagnostic shim, ship slimmer v0.2.2.* Rejected at sign-off — without it we'd be flying blind on the verification-failures question, which was half of the original user pain.

**Consequences.**
- New dependency on `langgraph.types.Send` for parallel fan-out (already pulled in transitively in v0.2.1).
- Worst-case decomposed cost: ~20 LLM calls per research run (1 Atomizer + 1 Planner + 5 × (1 synth + 2 repairs + verify) + post-merge verify + 2 post-merge repairs). Headline latency risk; the levers are `PLANNER_FANOUT_CAP` and per-Executor `max_repair_attempts`. Roadmap budget is 30s for typical queries — we measure and adjust in eval.
- Atomic path keeps v0.2.1 cost + 1 judge call (the Atomizer). Negligible overhead.
- `ResearchResult.attempts` semantics: in v0.2.2 this is the post-merge cycle's attempts (decomposed path) or the per-Executor attempts (atomic path, surfaced via the Aggregator passthrough). Per-Executor attempts on the decomposed path live in `sub_reports[].attempts`.
- The Aggregator's deterministic merge produces structured-but-not-narrative reports for decomposed queries. The user accepted this in sign-off as a transparency feature; if it reads poorly v0.2.3 promotes the Aggregator to an LLM call.
- Existing v0.2.1 swap-invisibility tests (`test_research_flow.py`) keep passing by explicitly passing `decompose=False` — they remain the regression gate for the bare spine. New tests (`test_roma_flow.py`) cover the Atomizer-decides paths and the parallel fan-out.
- The post-merge verify+repair cycle is skipped when there's only one SubReport. This deviates from a literal reading of sign-off #2 ("post-merge always runs") but matches its intent (cross-Report drift can't exist with only one Report). Documented in `_route_after_aggregate` and the plan doc.

---

## How to add a new ADR

1. Use the next number in sequence. Never reuse a number, even for a superseded one.
2. If superseding an existing ADR, the new ADR includes a "Supersedes ADR-NNNN" note in Context, and the old one is updated to `Status: superseded by ADR-MMMM`.
3. If the decision feels obvious in hindsight, write it anyway — that means it might get undone by accident later.
4. If you can't articulate the alternatives, you haven't actually decided. Stop and think before writing.
