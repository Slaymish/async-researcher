# Component Map

## Purpose

Every named component from `ArchitectureSpecification.md` and `LocalAgenticRAGArch.md`, mapped to:

- **Package** — which directory in the monorepo owns it (per `04_PROJECT_STRUCTURE.md`).
- **v0.1 status** — `in` (built for MVP), `stub` (interface only, no real implementation), `deferred` (skipped entirely, picked up in named later version).
- **Interface** — the surface the rest of the system sees. For deferred components, the interface that v0.1 should design *toward* so the real thing can drop in later without rewrites.

Anything that appears in either spec should appear here. If a component is missing, the map is wrong.

## Cross-cutting design rules

Two rules govern every entry below. They exist because the biggest risk in a research prototype is that a deferred component bakes assumptions into the codebase that block its real implementation later.

1. **Every external system is accessed through a single adapter package.** No retrieval logic in `apps/orchestrator`, no inference calls in `packages/citation`. Adapters can be swapped without touching consumers.
2. **All cross-component data flows carry `^id` block references.** The `^id` is the lingua franca — retrieval returns chunks tagged with `^id`s, the citation engine consumes them, the surfacing UI renders them as backlinks. No component is allowed to strip the `^id` from a chunk in transit.

## Retrieval & knowledge layer

| Component | Source | Package | v0.1 | Interface |
|---|---|---|---|---|
| Vault ingestion / `^id` injection | RAG §"Obsidian Block Identifiers" | `packages/ingestion` | in | `ingest(vault_path) -> IngestReport`. Idempotent. Emits events on change. |
| LightRAG graph | RAG §"LightRAG" | `packages/retrieval` (adapter) | in | `graph.query(query, level) -> list[GraphNode]`. Local server, auto-started. |
| DuckDB vector store | RAG §"Embedded Vector Substrates" | `packages/retrieval` (adapter) | in | `vector.search(query, k, filters) -> list[Chunk]`. SQL for metadata. |
| Hybrid retrieval fusion | RAG §"Embedded Vector Substrates" (last para) | `packages/retrieval` | in | `retrieve(query, k) -> list[Chunk]` — fuses graph + vector, returns with `^id`. |
| Shared Blackboard (Redis + vector) | OS §2.1 | `packages/retrieval` (interface only) | stub | DuckDB acts as the blackboard in v0.1; Redis added when concurrency demands it. |
| Embedding model | RAG §"Multi-Model Orchestration" | `packages/inference` | in | Called via the inference adapter; one model fixed in config. |

## Orchestration & agents

| Component | Source | Package | v0.1 | Interface |
|---|---|---|---|---|
| LangGraph state machine | RAG §"Agentic RAG and the State Machine Orchestrator" | `apps/orchestrator` | in (v0.2.1, per ADR-0020) | Linear graph: `retrieve → synthesise → verify → (repair → verify) → assemble`. `research()` signature unchanged from v0.1. ROMA nodes land additively in v0.2.2 (deliverable 2). |
| ROMA Atomizer | OS §1.1 | `apps/orchestrator` | in (v0.2.2, per ADR-0021) | LLM call on the judge model returning `AtomizerVerdict`. Bypassed when `/research` caller passes `decompose: true \| false`. |
| ROMA Planner | OS §1.1 | `apps/orchestrator` | in (v0.2.2, per ADR-0021) | LLM call on the synthesis model returning `Plan{sub_queries}`. Capped at `PLANNER_FANOUT_CAP=5`. Skipped on atomic path. |
| ROMA Executor | OS §1.1 | `apps/orchestrator` | in (v0.2.2, per ADR-0021) | LangGraph `Send` fan-out. Each invocation: `retrieve → synth → repair_loop`, emits a `SubReport` with per-Executor verification. |
| ROMA Aggregator | OS §1.1 | `apps/orchestrator` | in (v0.2.2, per ADR-0021) | Deterministic structural merge of `list[SubReport]` → `Report` + deduped chunks. Atomic case is passthrough; LLM rewrite is a v0.2.3 candidate. |
| Composer / Corroborator / Critic | OS §1.2 | `apps/orchestrator` | deferred → v0.3 | Adversarial review for synthesis quality. v0.1 has only a Composer-equivalent + the citation verifier (which is a degenerate Corroborator). |
| GEPA+ prompt optimization | OS §1.1 | `experiments/` | deferred → indefinite | Optimisation, not capability. Run as offline experiments once prompts stabilise. |

## Memory

| Component | Source | Package | v0.1 | Interface |
|---|---|---|---|---|
| Mem0 (Single-Pass ADD-only) | RAG §"The Agentic Memory Layer" | `packages/memory` | deferred → v0.2 | v0.1 has no cross-session memory. v0.2 adds `memory.recall(query) -> list[Fact]` and `memory.add(fact)`. |
| Tri-signal retrieval (semantic + BM25 + entity) | RAG §"Multi-Signal Retrieval Fusion" | `packages/memory` | deferred → v0.2 | Internal to the memory adapter; not exposed. |
| Agent-mode initialisation | RAG §"Storage Topologies" | `packages/memory` | deferred → v0.2 | CLI subcommand on the orchestrator. |

## Inference

| Component | Source | Package | v0.1 | Interface |
|---|---|---|---|---|
| OpenAI-compatible inference adapter | (new — implied by both specs) | `packages/inference` | in | `complete(messages, schema=None, model=None) -> Response`. Backed by Ollama/LM Studio on Mac. |
| llama-swap dynamic proxy | RAG §"llama-swap" | `infra/llama-swap` | deferred → phase 7 | Drop-in OpenAI endpoint replacement. Adapter URL changes in config; nothing else moves. |
| vLLM | RAG §"Deep Inference Optimization" | `infra/llama-swap` (config) | deferred → phase 7 | GPU-box only. Not relevant on Apple Silicon. |
| Transformers v5 / FP8 KV cache | RAG §"KV Cache Quantization" | `infra/llama-swap` (config) | deferred → phase 7 | GPU-box only. |
| Multi-head Latent Attention (MLA) | RAG §"KV Cache Quantization" | model selection | deferred → phase 7 | Property of chosen model; selected via config when GPU box is online. |
| PagedAttention / RadixAttention prefix caching | RAG §"Deep Inference Optimization" | `infra/llama-swap` (config) | deferred → phase 7 | vLLM/SGLang config flag. |
| Model hot-swap / FIFO queue / TTL | RAG §"llama-swap" | `infra/llama-swap` (config) | deferred → phase 7 | llama-swap responsibility. |

## Web & external sources

| Component | Source | Package | v0.1 | Interface |
|---|---|---|---|---|
| SearXNG metasearch (primary) | local-web-scraping report §"Metasearch Aggregation" | `packages/web` | deferred → v0.2 | `search(query, k) -> list[SearchHit]`. HTTP to a self-hosted Docker instance; JSON output mode. Per ADR-0018. |
| DDGS (Python lib, fallback) | local-web-scraping report §"Metasearch Aggregation" | `packages/web` | deferred → v0.2 | Same `search()` interface; used when SearXNG is not configured or returns nothing. Per ADR-0018. |
| Whoogle (Google-only proxy) | local-web-scraping report §"Metasearch Aggregation" | `packages/web` | deferred → v0.2.x | Tertiary fallback when SearXNG is throttled on Google. Not load-bearing. |
| Crawl4AI | RAG §"The Autonomous Web Scraping Engine" | `packages/web` | deferred → v0.2 | `fetch(url, schema=None) -> MarkdownDoc`. Async, returns LLM-ready Markdown. Default scraper with `enable_stealth=True`. |
| Playwright headless browser | RAG §"Asynchronous Execution" | `packages/web` (dep) | deferred → v0.2 | Transitive — Crawl4AI runs on it. |
| Schema-driven LLM extraction | RAG §"Asynchronous Execution" | `packages/web` | deferred → v0.2 | Internal to the web adapter; passed-through JSON schema. |
| `curl_cffi` TLS impersonation (fast path) | local-web-scraping report §"Protocol-Level Evasion" | `packages/web` | deferred → v0.2 | Lightweight HTTP fetch with Chrome/Firefox JA3 fingerprint. Tried first; falls back to Crawl4AI on 403/empty body. Selector heuristic lives in `packages/web/fetch.py`. |
| `nodriver` (CDP-driven browser) | local-web-scraping report §"Advanced DOM Interaction" | `packages/web` | deferred → "as needed" | Used only when Crawl4AI stealth fails. Direct Chrome DevTools Protocol; bypasses WebDriver detection. |
| FlareSolverr (Cloudflare bypass) | local-web-scraping report §"Solving Mandatory Challenges" | `infra/` (Docker) | deferred → "as needed" | Reverse proxy that solves Cloudflare interstitials and returns session cookies; cookie-passing strategy avoids paying browser cost on every request. |
| Tor + Privoxy + `stem` (IP rotation) | local-web-scraping report §"Infinite Local Proxies" | `infra/` | deferred → "as needed" | Free IP rotation via `NEWNYM` signal. Only deployed when a target rate-limits a single residential IP. Out of scope unless a real workload forces it. |
| Apache Nutch / YaCy (domain indexing) | local-web-scraping report §"Building a Local Index" | n/a | deferred indefinitely | Persistent local crawl of specific domains. Out of scope unless a concrete use case emerges (e.g. "fully index $domain locally"). |

## Citation & verification

| Component | Source | Package | v0.1 | Interface |
|---|---|---|---|---|
| `^id` block identifier protocol | RAG §"Obsidian Block Identifiers" | `packages/ingestion` | in | Stable canonical form; documented in `05_DECISIONS.md` when chosen. |
| JSON-schema-constrained generation | RAG §"Constrained Decoding" | `packages/citation` | in | `synthesise(context, schema) -> StructuredReport`. Uses inference adapter. |
| AST parser (assembled Markdown) | RAG §"Constrained Decoding" | `packages/citation` | in | `parse(report_md) -> list[Claim]`. Parses the **Markdown report assembled from the JSON synthesis output**, not the raw JSON. Two-stage flow: LLM emits JSON (claim/quote/^id triples), orchestrator assembles Markdown, AST parser walks the Markdown to extract claims for verification. Deterministic, no LLM. |
| Link verification (spatial grounding) | RAG §"Multi-Dimensional Verification" | `packages/citation` | in | `verify_link(claim) -> bool`. File-system check that `^id` exists. |
| Factual alignment judge | RAG §"Multi-Dimensional Verification" | `packages/citation` | in | `verify_support(claim, source_chunk) -> Verdict`. Small judge model call. |
| Iterative repair loop | RAG §"Multi-Dimensional Verification" | `packages/citation` | in | Internal to citation engine. Bounded retries (default 2). |

## UI / user interaction

| Component | Source | Package | v0.1 | Interface |
|---|---|---|---|---|
| Obsidian plugin shell | OS §7, RAG §"Human-in-the-Loop UX" | `apps/obsidian-plugin` | in | TypeScript plugin. Talks to backend over localhost HTTP. |
| Proactive surfacing side panel | (new — from vision) | `apps/obsidian-plugin` | in | Listens to file-open/edit events; calls `/surface` endpoint; renders results. |
| Deep research query input + report rendering | RAG §"Human-in-the-Loop UX" | `apps/obsidian-plugin` | in | Modal or sidebar input; renders returned report as a new note with backlinks. |
| HITL visual search-graph (node prune/expand) | RAG §"Human-in-the-Loop UX" | `apps/obsidian-plugin` | deferred → v0.2 | Canvas-based or D3-based; requires the LangGraph orchestrator to produce a real plan to visualise. |
| Terminal-style execution log | RAG §"Human-in-the-Loop UX" | `apps/obsidian-plugin` | deferred → v0.2 | Streams orchestrator events; meaningless without a multi-step orchestrator. |
| Obsidian Canvas as shared agent workspace | OS §7.2 | `apps/obsidian-plugin` | deferred → v0.3 | Agent reads/writes `.canvas` JSON files. Requires the agent layer to exist first. |
| Vault Agent Card (A2A server) | OS §7.3 | `apps/obsidian-plugin` | deferred → phase 8 | Hosts `/.well-known/agent.json`. Useless until external A2A clients exist. |
| Ingestion file watcher | OS §7.1 (subset) | `apps/orchestrator` | in | Always-on lightweight process re-ingesting changed vault files on save. v0.1 scope is ingestion only. See ADR-0017. |
| Autonomous daemon (filing + structural integrity + event flows) | OS §7.1 | `apps/orchestrator` | deferred → v0.3 | Extends the v0.1 ingestion watcher with autonomous filing, structural-integrity scans, and event-driven workflows. Same process, expanded responsibilities. |

## A2A / MCP / interoperability

| Component | Source | Package | v0.1 | Interface |
|---|---|---|---|---|
| A2A protocol (JSON-RPC over HTTPS) | OS §3.1 | `packages/a2a` | deferred → phase 8 | Only relevant once there are multiple agents/services to interoperate with. |
| Agent Cards (JSON manifests) | OS §3.2 | `packages/a2a` | deferred → phase 8 | Same. |
| MCP server integrations | OS §3 (referenced) | `packages/mcp` | deferred → phase 8 | The Obsidian plugin may expose MCP later for external Claude/Codex clients. |
| Server-Sent Events streaming | OS §3.1 | `packages/a2a` | deferred → phase 8 | Same. |

## Orchestration & infrastructure (system-level)

| Component | Source | Package | v0.1 | Interface |
|---|---|---|---|---|
| n8n event-driven workflows | OS §5 | `infra/n8n` | deferred → v0.3 | Replaces or augments the autonomous daemon for file-trigger flows. |
| n8n Queue Mode (Redis-backed workers) | OS §5.2 | `infra/n8n` | deferred → phase 8 | Only relevant at high throughput. |
| HashiCorp Vault for secrets | OS §5.2 | `infra/dev` | deferred → indefinite | Single-user local app; `.env` is sufficient for v0.1. |

## Governance & security

| Component | Source | Package | v0.1 | Interface |
|---|---|---|---|---|
| AGT policy engine (sub-ms interception) | OS §6.2 | `packages/governance` | deferred → phase 8 | Wraps every tool call. v0.1 has no untrusted tools; the citation engine is the only enforced constraint. |
| Policy-as-code (OPA Rego / Cedar / YAML) | OS §6.2 | `packages/governance` | deferred → phase 8 | Same. |
| POSIX-style capability sandboxing | OS §6.1 (ASI-02) | `packages/governance` | deferred → phase 8 | Same. |
| Execution ring isolation (Rings 0–3) | OS §6.1 (ASI-05) | `packages/governance` | deferred → phase 8 | Same. |
| Policy-controlled VFS | OS §6.1 (ASI-06) | `packages/governance` | deferred → phase 8 | v0.1 enforces read-only on user-authored notes via convention (plugin guards), not VFS. |
| AgentMesh / DIDs / IATP / SPIFFE | OS §6.3 | `packages/governance` | deferred → phase 8 | Only meaningful when multiple agents are exchanging messages over A2A. |
| Ed25519 / ML-DSA-65 signatures | OS §6.3 | `packages/governance` | deferred → phase 8 | Same. |
| Cross-Model Verification Kernel | OS §6.1 (ASI-06) | `packages/governance` | deferred → phase 8 | Same. |
| Trust score / circuit breakers / kill switch | OS §6.3 | `packages/governance` | deferred → phase 8 | Same. |
| AI-BOM (component provenance) | OS §6.1 (ASI-04) | `infra/dev` | deferred → phase 8 | Reproducible build manifest; meaningful once dependencies stabilise. |
| Human-in-the-loop approval policy (`require_approval`) | OS §6.2 | `packages/governance` | partial in v0.1 | v0.1 surfaces edits to user-authored notes for review (per vision §boundaries). The full policy engine is deferred; the principle is enforced by plugin convention. |

## Latent thought compression (research layer)

| Component | Source | Package | v0.1 | Interface |
|---|---|---|---|---|
| RecursiveMAS | OS §4 | `experiments/` | deferred → indefinite | Research-grade. No interface defined; revisit only if a working multi-agent system exists worth optimising. |
| RecursiveLink (Inner + Outer) | OS §4.1 | `experiments/` | deferred → indefinite | Same. |
| Dual-rate training loop | OS §4.2 | `experiments/` | deferred → indefinite | Same. |

## What's in v0.1, summarised

Counting only `in` and partial-`in` rows:

- Ingestion: vault walk, `^id` injection, incremental, always-on file watcher
- Retrieval: LightRAG + DuckDB hybrid
- Inference: OpenAI-compatible adapter (Ollama on Mac)
- Citation: JSON schema generation → Markdown assembly → AST parse → verify → repair
- UI: Obsidian plugin, surfacing panel, deep research query/report
- Partial: HITL approval on user-note edits (by convention)

That is the entire MVP surface area. Everything else in this map is intentionally absent from v0.1.
