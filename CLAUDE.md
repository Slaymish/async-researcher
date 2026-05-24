# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Commands

Cross-language commands are wrapped in the `Makefile`:

```bash
make install       # uv sync --all-packages && pnpm install
make test          # uv run pytest packages/ apps/ eval/ && pnpm --filter obsidian-plugin test
make lint          # uv run ruff check . && pnpm --filter obsidian-plugin lint
make format        # ruff format + autofix
make dev           # uv run orchestrator-dev (FastAPI + always-on file watcher)
make ingest        # uv run orchestrator-ingest (one-shot bulk vault ingest)
make plugin-build  # pnpm --filter obsidian-plugin build
make plugin-dev    # esbuild watch mode for the plugin
```

Running a single Python test: `uv run pytest packages/<pkg>/tests/test_x.py::test_name`.
Plugin tests use vitest: `pnpm --filter obsidian-plugin test -- <name>`.

Use `pnpm` throughout — never `npm` or `yarn`.

### `ai-os` unified CLI

All backend functionality is also available via `ai-os <subcommand>`:

```bash
ai-os serve                          # same as make dev
ai-os setup                          # interactive first-time config wizard
ai-os ingest [--dry-run] [--force]
ai-os query <query> [-k N] [--prefix PATH] [--kind heading|para|list_item|code|table]
ai-os research <query> [-k N] [--repair N] [--skip-alignment]
```

### Loading the Obsidian plugin

```bash
ln -s "$(pwd)/obsidian-plugin" "<vault>/.obsidian/plugins/ai-os"
```
Then enable it in Obsidian → Settings → Community plugins.

## Architecture

Three processes at runtime: **Obsidian** (host) ↔ **orchestrator** (Python FastAPI, `localhost:8765`) ↔ **local LLM server** (Ollama at `:11434`). The orchestrator is monolithic and in-process (ADR-0007): every `packages/*` module is imported directly; the file watcher runs as an asyncio task in the same FastAPI process.

### Python backend

`apps/orchestrator/src/orchestrator/` layout:

- `routes/` — thin FastAPI routers for `/surface`, `/research`, `/research/stream` (SSE), `/health`. HTTP layer only; no logic.
- `flows/research_flow.py` — public contract: `research(query, ...) → ResearchResult`. Signature is stable; body delegates to the graph.
- `flows/graph.py` — LangGraph state machine. See graph shape below. Two event callbacks injected via `RunnableConfig.configurable`: `on_progress: Callable[[str], None]` (plain text status) and `on_event: Callable[[dict], None]` (structured events — `plan`, `web_search`, `web_fetch`, `web_fetch_done`, `executor_done`). Helpers: `_maybe_progress(config, msg)` and `_emit_event(config, event)`.
- `flows/roma.py` — ROMA node bodies + Pydantic schemas (`AtomizerVerdict`, `Plan`, `SubQuery`, `SubReport`). Graph wiring lives in `graph.py`.
- `flows/surface_flow.py` — surfacing flow (flat, unchanged since v0.1).
- `config.py` — `load_config()` reads `config.toml`. Lookup order: walk upward from cwd, then `~/Library/Application Support/ai_os/config.toml`. Override with `AI_OS_CONFIG=<path>`.

Packages imported by the orchestrator:

- `packages/ingestion/` — vault walker, Markdown parser, `^id` injector, file watcher (`watchdog`/FSEvents).
- `packages/retrieval/` — DuckDB vector store + LightRAG graph index, hybrid fusion (`hybrid.py`).
- `packages/citation/` — JSON-schema synthesis → AST parse → per-claim verification → bounded repair loop.
- `packages/inference/` — OpenAI-compatible HTTP client (points at Ollama). Three named model slots: `synthesis_model` (large), `judge_model` (small/fast), `embedding_model`. `routing.py` maps `InferenceTask` → model name.
- `packages/memory/` — Mem0 integration. `Memory.recall(query)` → facts injected into Planner. `Memory.add(text, metadata)` called by the `remember` graph node after successful runs.
- `packages/web/` — Search (SearXNG primary, `ddgs` fallback) + fetch (curl_cffi fast path, Crawl4AI fallback). Web chunks are indexed into DuckDB under a `web://` relpath prefix (ADR-0019) and retrieved alongside vault chunks.

### Research graph (v0.2.3 — ROMA + memory)

The LangGraph graph in `flows/graph.py` implements:

```
START → atomize (judge model, AtomizerVerdict{decompose, rationale})
          ├─ decompose=True  → plan (synth model, Plan{sub_queries}, max 5)
          │                    → fan-out: Send × N → execute
          └─ decompose=False → execute (single Send, original query as SubQuery)
                                ↓ (reducer: sub_reports accumulates via operator.add)
                              aggregate (deterministic merge → Report + chunks)
                                ├─ 1 sub_report → assemble   (skip post-merge verify)
                                └─ N sub_reports → verify → repair (loop) → assemble
                                                    ↓
                                                  remember → END
```

Key behaviours:
- **Atomizer** runs on the judge model every time; overridable via `decompose: bool | "auto"` on the `/research` route.
- **Executor** (`execute` node): runs the full per-Executor `synthesise → repair_loop` cycle before emitting a `SubReport`. Repair budget is per-Executor. For `target="web"` sub-queries, runs search → fetch → `_index_web_doc` → retrieve before synthesis.
- **Aggregator** (`aggregate` node): deterministic structural merge, no LLM call. Single-SubReport path passes the report through unchanged (observational invariance).
- **Remember** (`remember` node): writes `report.summary` to Mem0 if `memory_write=True` and `pass_rate ≥ threshold`. Skipped when memory is not configured.
- **`PLANNER_FANOUT_CAP = 5`** — first lever to pull if latency is too high.
- **`source_filter`** (`"auto"` / `"vault"` / `"web"`): per-run override stored in `ResearchState`; respected by the Planner prompt (SOURCE OVERRIDE instruction appended), by `_route_after_atomize` for atomic queries, and by `_execute` for each sub-query.
- **`memory_write: bool`**: per-run gate on the `remember` node.
- Dependencies are injected via `RunnableConfig.configurable` as `ResearchDeps` (fields: `store`, `client`, `retriever`, `synthesis_client`, `web_adapter`, `memory`). `synthesis_client` overrides `client` for synthesis-model calls; use `_synth_client(deps)` helper.

### Web search pipeline

`packages/web/adapter.py` → `WebAdapter.search()` returns `list[SearchHit]`; `WebAdapter.fetch()` returns `MarkdownDoc`. The `_execute_web` function in `roma.py` emits SSE events at each stage:
- `web_search` — after DDGS/SearXNG returns hits (before any fetching)
- `web_fetch` — immediately before fetching each URL
- `web_fetch_done` — after indexing (or on empty/failed fetch, with `chunks: 0`)

The web dependency is `ddgs` (package was renamed from `duckduckgo-search`).

### Obsidian plugin (`obsidian-plugin/`)

TypeScript plugin built with esbuild. The only HTTP client — talks to the orchestrator over HTTP/JSON. Research uses `POST /research/stream` (SSE) via native `fetch` + `ReadableStream`; all other calls use Obsidian's `requestUrl`.

Key source files:
- `src/main.ts` — plugin entry; registers views, commands, event hooks. `runDeepResearch()` owns the full research lifecycle.
- `src/research/index.ts` — `ResearchQueryModal` (question input + source toggles + submit).
- `src/research/sidebar.ts` — `ResearchStatusView` (`VIEW_TYPE_RESEARCH`): live research progress sidebar. Public API: `startResearch`, `onPlan`, `onWebSearch`, `onWebFetch`, `onWebFetchDone`, `onExecutorDone`, `onProgress`, `onDone`, `onError`. Auto-opens on plugin load unless the user closed it (`researchSidebarOpen` setting).
- `src/surfacing/` — "Related notes" side panel.
- `src/api/index.ts` — `OrchestratorClient` + typed SSE event interfaces (`ResearchPlanEvent`, `ResearchWebSearchEvent`, `ResearchWebFetchEvent`, `ResearchWebFetchDoneEvent`, `ResearchExecutorDoneEvent`).

Output is `main.js` at the plugin root (gitignored). TypeScript config is `obsidian-plugin/tsconfig.json`.

### Planner prompt behaviour

The Planner (in `prompts.py`) routes sub-queries to `"web"` by default for any external knowledge, and to `"vault"` only for questions specifically about the user's own notes. When `source_filter != "auto"`, a SOURCE OVERRIDE line is appended to the system prompt forcing all sub-queries to that target.

### Cross-cutting design rules

1. **Every external system through one adapter package.** No retrieval logic in `apps/orchestrator`; no inference calls in `packages/citation`. Adapters are the swap point for future model/search changes.
2. **All data flows carry `^id` block references** (ADR-0012). `^id` is the lingua franca across retrieval, citation, and surfacing. No component may strip it in transit.
3. **All LLM calls go through `packages/inference/client.py`** (ADR-0009). No vault content may be sent to a cloud LLM from this codebase (ADR-0005).

### Two load-bearing pipelines

**Citation (ADR-0013):** `packages/citation/synth.py` → `assemble.py` → `ast_parse.py` + `verify.py` → `repair.py`. JSON wire format from LLM → deterministic Markdown render → AST-level claim verification. The synthesis prompt appends a `VALID BLOCK IDS` list to every user message so the model can only cite block IDs that actually exist in the retrieved chunks. Do not collapse stages.

**Retrieval (ADR-0011):** LightRAG graph + DuckDB vector, fused in `packages/retrieval/hybrid.py`. Both share `^id` as the join key. Web chunks share the same DuckDB store under `web://` relpaths.

## Config

Copy `config.toml.example` → `config.toml` (gitignored). Secrets via `.env` (ADR-0016). Key sections: `[vault]`, `[storage]` (paths support `${data_dir}` expansion), `[inference]` (three model slots + `timeout_s`), `[web]` (`searxng_url`, `max_fetch_urls`, `fetch_timeout_s`), `[watcher]`, `[server]`. Run `ai-os setup` for interactive first-time generation.

## Planning docs

Architectural reasoning lives in `docs/`:
- `docs/00_VISION.md` — two pillars (surfacing + research)
- `docs/01_MVP_SCOPE.md` — v0.1 scope and success criteria
- `docs/02_COMPONENT_MAP.md` — component status (`in` / `stub` / `deferred`) and interfaces
- `docs/03_ROADMAP.md` — phased delivery with entry-criteria gates
- `docs/05_DECISIONS.md` — ADR log (append-only; read before extending architecture)
- `docs/v0.2.2_ROMA_PLAN.md` — ROMA decomposition design + sign-off record

Source specs (`ArchitectureSpecification.md`, `LocalAgenticRAGArch.md`) at repo root are the north star, not a literal build list (ADR-0002).
