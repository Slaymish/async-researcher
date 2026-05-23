# MVP Scope (v0.1)

## Purpose of this document

Define the smallest end-to-end slice of the system that (a) proves the core architectural hypotheses, (b) delivers daily value to a single user, and (c) ships in weeks, not months. Everything outside this scope is deferred to a numbered later version with explicit justification.

The MVP is **Mac-only**, **local-inference-only**, and explicitly a **research prototype** — throwaway code is acceptable where it accelerates learning.

## Core hypotheses v0.1 must prove

If any of these is false, the whole project needs rethinking. v0.1 exists to test them as cheaply as possible.

1. **Deterministic citation works.** A constrained-decoding + AST-verify pipeline can produce LLM output where 100% of citations resolve to real `^id` blocks containing text that supports the claim.
2. **Hybrid retrieval beats flat vector search.** LightRAG graph traversal + DuckDB vector search produces more relevant context for vault questions than vector search alone — measurably, on a small eval set.
3. **A local model is good enough for synthesis.** A model that fits on the user's Mac (~7B–14B class) can produce useful long-form research output when given high-quality retrieved context and a strict output schema.
4. **Proactive surfacing is wanted, not annoying.** When the system pushes related notes into a side panel on file-open, the user finds it useful more often than noisy.

If hypothesis 3 fails on the Mac, the project waits for the GPU box — but the orchestrator, retrieval, and citation layers remain valid and will move over unchanged.

## In scope for v0.1

### Substrate (shared by both headline capabilities)

- **Vault ingestion pipeline.** Walks the vault, parses Markdown, assigns a deterministic `^id` block identifier to every logical block (paragraph, list item, heading section) that lacks one. Idempotent: re-running produces no churn. Incremental: only re-processes changed files. **Runs as a lightweight always-on file watcher** (per ADR-0017) — re-ingests individual files on save without manual invocation. A one-shot CLI mode also exists for bulk initial ingestion. The v0.3 autonomous daemon extends this watcher with filing and structural-integrity capabilities; v0.1 scope is ingestion only.
- **Hybrid index.** LightRAG graph (entities + relations) plus DuckDB vector store (chunks + embeddings, with YAML frontmatter as queryable metadata). Both indexes share `^id` as their primary join key.
- **Retrieval API.** A single Python function: `retrieve(query, k) -> list[Chunk]` where each chunk carries its `^id`, source file, and verbatim text. Internally fuses graph + vector results.
- **Local inference adapter.** OpenAI-compatible HTTP client pointing at Ollama (or LM Studio) running on the Mac. Model selection lives in config. No model orchestration logic — one model per call, no swapping. The interface is shaped so phase 7 can swap in llama-swap without touching callers.
- **Citation engine.** JSON-schema-constrained generation → AST parse → per-claim verification (does the `^id` exist? does its text support the claim?) → bounded repair loop on failure. Single pass, no agentic complexity.

### Capability 1: Proactive surfacing (dumb version)

- Obsidian plugin opens a side panel.
- On file-open or significant edit (debounced), the plugin sends the active note's content to the backend.
- Backend runs the retrieval API against that content as the query, returns top-K related blocks from *other* files.
- Side panel lists them with one-line context and a click-through to the source.
- No contradiction detection, no temporal reasoning, no "forgotten thread" detection — those are v0.2+.

### Capability 2: Deep research (single-turn)

- Obsidian plugin exposes a query input.
- User types a research question.
- Backend retrieves with high `k`, calls the local model with strict JSON schema, runs the citation engine, returns a structured report.
- Plugin renders the report as a new note in the vault, with citations as native Obsidian backlinks (`[[note#^id]]`).
- **No LangGraph orchestrator yet.** No planner/executor split, no reflection loop, no web sub-agent. Single retrieve → synthesise → verify pass.

### Project infrastructure

- Monorepo skeleton per `04_PROJECT_STRUCTURE.md`.
- A tiny eval harness: 20–30 hand-written (question, expected source `^id`s) pairs against a snapshot of the vault, runnable with one command. Used to test hypothesis 2 and to detect regressions when changing retrieval or models.

## Explicitly out of scope for v0.1

Each deferral is annotated with the version that picks it up and why it's safe to wait.

| Feature | Deferred to | Why it's safe to wait |
|---------|-------------|------------------------|
| LangGraph orchestrator (planner/executor split, reflection) | v0.2 | Single-turn deep research is enough to test hypotheses 1 and 3. Agentic depth is meaningless until those pass. |
| Wide-to-Deep with HITL visual graph UI | v0.2 | Biggest UX piece in the spec. Worth nothing if the underlying research quality is bad. Validate quality first. |
| Web sub-agent (Crawl4AI) | v0.2 | Live web sources expand scope dramatically (rate limits, content filtering, freshness). Vault-only is enough to test the citation engine. |
| Mem0 persistent memory | v0.2 | Single-session use is fine for v0.1. Memory only matters once the user is running many sessions per week. |
| Autonomous filing of fleeting notes | v0.3 | Requires reliable categorisation against an evolving folder ontology. Premature without a stable vault model. |
| Contradiction detection in surfacing | v0.3 | Needs the agentic orchestrator (v0.2) underneath. |
| Vault structural integrity (orphan detection, link repair) | v0.3 | Standalone capability; not on the critical path for the headline pillars. |
| Multi-model hot-swap via llama-swap + vLLM | Phase 7 (GPU box) | One-model-per-call is fine on Mac. The inference adapter interface is already designed for swap-in. |
| AI OS expansion: ROMA holonic decomposition, A2A agent cards, n8n triggers, AGT policy engine | Phase 8+ | These are scaling layers for a working system. The MVP doesn't need them to function. |
| Latent thought compression (RecursiveMAS) | Indefinite | Research-grade. Re-evaluate when there's a stable multi-agent system worth optimising. |
| Cross-LLM-family routing, FP8 quantisation, MLA, PagedAttention | Phase 7 | GPU box only. Irrelevant on Apple Silicon. |

## Success criteria for v0.1

The MVP is done when, against the user's actual vault:

1. Re-running ingestion on an unchanged vault produces zero file modifications and completes in under 10 seconds.
2. On the eval set, hybrid retrieval beats vector-only retrieval on a defined metric (precision@5 against expected `^id`s) by a measurable margin.
3. Across 50 deep-research queries against the live vault, **at least 95% of generated citations pass the verification loop on the first or second pass** (i.e., the `^id` exists and the claim is supported).
4. The proactive surfacing panel updates within 2 seconds of opening a new file in Obsidian.
5. **Per-pillar cadence,** sustained for two consecutive weeks without disabling either feature:
   - *Surfacing (passive, daily):* the side panel is open and useful during typical daily work — most working days produce at least one surfaced item the user clicks through to.
   - *Deep research (active, weekly):* the user runs at least one deep research query per week.

## What "shippable" means here

"Shippable" does not mean "shareable with strangers." It means:

- Runs on the user's Mac with one command per process (ingestion daemon, backend, Obsidian plugin enabled).
- Survives a vault edit, a backend restart, and an Obsidian reload without manual recovery.
- The user trusts it enough to use it daily without checking its work every time.

It does not need: a setup wizard, error telemetry, multi-user support, packaging for distribution, documentation for anyone but the author.

## Estimated effort

Deliberately rough — research prototype, single developer, evenings/weekends pace. Each phase is "until done," not calendar-locked.

| Phase within MVP | Rough effort |
|------------------|--------------|
| Repo scaffold + Obsidian plugin shell + Python backend wired | 1 week |
| Ingestion pipeline + file watcher (`^id` injection, LightRAG, DuckDB, incremental) | 2 weeks |
| Citation engine (schema, AST parse, verifier, repair) | 2 weeks |
| Single-turn deep research end-to-end | 1 week |
| Proactive surfacing side panel | 1 week |
| Eval dataset curation (20–30 hand-written (question, expected `^id`) pairs) | ~3 days |
| Eval harness code + hypothesis validation | ~4 days |

Total: ~8–9 weeks of focused work for a v0.1 that proves or disproves the core architecture.
