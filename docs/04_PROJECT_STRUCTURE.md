# Project Structure

## Purpose

Concrete repo layout, language choices, build tooling, runtime topology, and dev environment. The structure is shaped by one constraint: **a research prototype must stay easy to throw pieces away.** Heavy monorepo tooling, framework-of-the-month dependencies, or premature abstractions all make discard harder. The default answer is the boring one.

## Language choices

| Layer | Language | Why |
|---|---|---|
| Obsidian plugin | TypeScript | Obsidian's plugin API is TS-only. No alternative. |
| Backend (orchestrator, all `packages/*`) | Python 3.12+ | LightRAG, Mem0, Crawl4AI, LangGraph, vLLM all have Python as their primary or only binding. The cost of cross-language bridges far exceeds the cost of Python's runtime overhead at single-user scale. |
| Eval harness | Python | Lives next to the components it evaluates. |
| Infra configs | YAML / TOML | Tool-mandated. |

No Rust, no Go, no second compiled language. If a hotspot demands it later, drop it in via a single FFI call site — but not until measurement forces the question.

## Repo layout

```
AI_OS/
├── apps/
│   ├── obsidian-plugin/              TypeScript Obsidian plugin
│   │   ├── src/
│   │   │   ├── main.ts               Plugin entry, lifecycle
│   │   │   ├── api/                  HTTP client to backend
│   │   │   ├── surfacing/            Side panel for proactive surfacing
│   │   │   ├── research/             Deep research query + report rendering
│   │   │   └── settings.ts
│   │   ├── manifest.json
│   │   ├── package.json
│   │   └── tsconfig.json
│   │
│   └── orchestrator/                  Python FastAPI backend
│       ├── src/orchestrator/
│       │   ├── main.py               FastAPI app entry
│       │   ├── routes/
│       │   │   ├── surface.py        POST /surface — proactive surfacing
│       │   │   ├── research.py       POST /research — deep research
│       │   │   └── health.py
│       │   ├── flows/                v0.1: flat functions. v0.2: LangGraph graphs.
│       │   │   ├── research_flow.py
│       │   │   └── surface_flow.py
│       │   └── config.py
│       └── pyproject.toml
│
├── packages/                          Python libraries, importable across apps
│   ├── ingestion/
│   │   └── src/ingestion/
│   │       ├── walker.py             Vault traversal, change detection
│   │       ├── watcher.py            Always-on file watcher (watchdog) — v0.1
│   │       ├── parser.py             Markdown → blocks
│   │       ├── id_injector.py        `^id` assignment, idempotent
│   │       └── pipeline.py           Top-level `ingest(vault_path)` and `watch(vault_path)`
│   ├── retrieval/
│   │   └── src/retrieval/
│   │       ├── graph.py              LightRAG adapter
│   │       ├── vector.py             DuckDB adapter
│   │       ├── hybrid.py             Fusion + re-ranking
│   │       └── types.py              Chunk, GraphNode dataclasses
│   ├── citation/
│   │   └── src/citation/
│   │       ├── schema.py             JSON schema for structured reports
│   │       ├── synth.py              Constrained JSON generation (claim/quote/^id triples)
│   │       ├── assemble.py           JSON → assembled Markdown report
│   │       ├── ast_parse.py          AST of assembled Markdown for verification
│   │       ├── verify.py             Link + factual alignment checks
│   │       └── repair.py             Bounded repair loop
│   ├── inference/
│   │   └── src/inference/
│   │       ├── client.py             OpenAI-compatible client
│   │       ├── routing.py            Model-per-task selection (config-driven)
│   │       └── types.py
│   ├── memory/                       Interface only in v0.1; Mem0 lands v0.2
│   │   └── src/memory/
│   │       └── adapter.py
│   └── web/                          Interface only in v0.1; Crawl4AI lands v0.2
│       └── src/web/
│           └── adapter.py
│
├── infra/
│   ├── llama-swap/                   Phase 7 config — model definitions, TTLs, ports
│   └── dev/
│       ├── docker-compose.yml        Optional services (Redis, etc.) for later phases
│       └── .env.example
│
├── eval/
│   └── harness/
│       ├── src/eval/
│       │   ├── runner.py             One-command eval execution
│       │   ├── metrics.py            Precision@k, citation pass rate
│       │   └── reports.py
│       ├── datasets/                 (question, expected `^id`s) pairs
│       └── snapshots/                Vault snapshots for reproducible eval
│
├── experiments/                       Throwaway notebooks. Not packaged. Not tested.
│
├── docs/                              Planning docs (this directory)
│
├── pyproject.toml                     Workspace root (uv workspace config)
├── uv.lock                            Pinned Python deps
├── .python-version                    3.12 (or current)
├── pnpm-workspace.yaml                TS workspace config
├── package.json                       Workspace root
├── .gitignore
└── README.md                          Quick-start, links to docs/
```

## Build tooling

### Python — `uv`

`uv` (Astral) is the package and workspace manager. Reasons: fast, single binary, native workspaces, lockfile-by-default, drop-in `pip`/`virtualenv` semantics. Avoids the Poetry/Hatch/PDM debate.

Workspace layout: each `packages/*` and `apps/*/` Python project has its own `pyproject.toml` declaring dependencies. The root `pyproject.toml` declares the workspace members. Inter-package dependencies are local path references (`{ workspace = true }`).

```bash
uv sync                     # install everything in the workspace
uv run pytest               # run all tests
uv run orchestrator-dev     # start the FastAPI backend
```

### TypeScript — `pnpm`

`pnpm` for the Obsidian plugin (and any future TS package). Reasons: workspace support, content-addressable store, minimal disk footprint. Single plugin in v0.1 — workspace is overkill now but future-proof.

```bash
pnpm install
pnpm --filter obsidian-plugin build      # esbuild bundle
pnpm --filter obsidian-plugin dev        # watch mode
```

### Cross-language

No unified monorepo tool (Nx, Turborepo, Bazel). Two top-level commands in a `Makefile` or `justfile` wrap both:

```makefile
install:        uv sync && pnpm install
test:           uv run pytest && pnpm test
lint:           uv run ruff check && pnpm lint
```

That's all the cross-language tooling the prototype needs.

## Runtime topology

### v0.1 (Mac-only)

```
┌─────────────────────────┐
│  Obsidian (host)        │
│  ┌───────────────────┐  │
│  │ obsidian-plugin   │  │  TS, in-process
│  └─────────┬─────────┘  │
└────────────┼────────────┘
             │ HTTP (localhost:8765)
             ▼
┌─────────────────────────┐
│  orchestrator           │  Python, FastAPI, single process
│  ├─ /surface            │
│  ├─ /research           │
│  ├─ /health             │
│  └─ file watcher        │  watchdog-based, always on (ADR-0017)
│                         │
│  In-process imports:    │
│  ├─ packages/ingestion  │
│  ├─ packages/retrieval  │  ─┐
│  ├─ packages/citation   │   │
│  └─ packages/inference  │  ─┤
└──┬─────────┬────────────┘   │
   │         │                │
   │  fs     │ HTTP           ▼
   │  events ▼                │
┌──┴──────┐  ┌────────────┐   ▼
│ Vault   │  │ Local LLM  │  ┌──────────────────────────────────┐
│ (FS)    │  │ (Ollama)   │  │ Local stores                     │
│         │  │ :11434     │  │ ~/Library/Application Support/   │
└─────────┘  └────────────┘  │   ai_os/                         │
                             │   ├─ index.duckdb                │
                             │   └─ lightrag/                   │
                             └──────────────────────────────────┘
```

Three processes total: Obsidian, the Python orchestrator, the local model server. The orchestrator is monolithic — every `package` is imported in-process, and the file watcher runs as an asyncio task inside the same FastAPI process. No microservices, no message queues, no Redis until concurrency demands it.

### v0.3 (autonomous daemon expanded)

The v0.1 ingestion file watcher (already always-on) expands its responsibilities: filing, structural integrity, event-driven workflows. Same process, broader scope. No new startup mode required — capabilities toggled via config under `[daemon]`.

### Phase 7 (GPU box added)

The local LLM box moves to a second machine. The inference adapter's base URL changes in config; the orchestrator stays on the Mac. Optional: run the orchestrator on the GPU box too if network latency dominates.

```
Mac:  Obsidian + orchestrator      GPU box:  llama-swap → vLLM
        │                              ▲
        └──────── HTTP over LAN ───────┘
```

## Inter-process protocols

| Boundary | Protocol | Why |
|---|---|---|
| Plugin → orchestrator | HTTP/JSON | Trivial to debug from curl. FastAPI gives free OpenAPI docs. |
| Plugin → orchestrator (streaming reports) | Server-Sent Events | Aligns with the A2A protocol (OS §3.1) for future compatibility. |
| Orchestrator → local LLM | OpenAI-compatible HTTP | Standard; works with Ollama, LM Studio, llama-swap, vLLM, all major hosted providers. |
| Orchestrator → DuckDB | In-process via Python client | Embedded; no IPC. |
| Orchestrator → LightRAG | In-process Python | Embedded; no IPC. |
| Orchestrator → vault filesystem (reads + `^id` injection) | Direct filesystem calls | Same machine in v0.1. |
| Vault filesystem → orchestrator (change events) | `watchdog` library (FSEvents on macOS) | v0.1 file watcher per ADR-0017. |

No gRPC, no Protobuf, no message queues in v0.1. They land only when a phase demands them.

## Configuration

Single config file: `config.toml` at repo root, gitignored. Schema-validated at startup.

```toml
[vault]
path = "/Users/hamish/Documents/Vault"
inbox_dirs = ["00_Inbox", "01_Fleeting"]

[storage]
# macOS Application Support convention. Override per machine if needed.
data_dir = "~/Library/Application Support/ai_os"
duckdb_path = "${data_dir}/index.duckdb"
lightrag_dir = "${data_dir}/lightrag"

[inference]
base_url = "http://localhost:11434/v1"
synthesis_model = "qwen2.5:14b-instruct"
embedding_model = "nomic-embed-text"
judge_model = "qwen2.5:7b-instruct"

[retrieval]
vector_top_k = 20
graph_depth = 2
hybrid_fusion = "rrf"     # reciprocal rank fusion

[citation]
max_repair_attempts = 2
factual_alignment_threshold = 0.8

[watcher]
# v0.1 file watcher tuning (ADR-0017).
debounce_ms = 500
ignore_globs = [".obsidian/**", ".trash/**", ".git/**"]

[server]
port = 8765
```

Per-environment overlays (`config.local.toml`) can land later if useful. Secrets via `.env` until phase 8 makes vault-managed secrets meaningful.

## Testing

| Surface | Tool | What's tested |
|---|---|---|
| Python packages | `pytest` | Unit + integration tests per package. Property-based via `hypothesis` for the `^id` injector (idempotency is the property). |
| Orchestrator routes | `pytest` + `httpx` AsyncClient | Endpoint contract tests. |
| TS plugin | `vitest` | Unit tests for client logic. Manual smoke for UI. |
| End-to-end research quality | `eval/harness` | Runs the full pipeline against a vault snapshot. Reports precision@k and citation pass rate. Run on every PR (when CI exists) and before any release. |

No Selenium / Playwright for the Obsidian plugin itself. UI is small enough for manual verification at this stage; revisit if it grows.

## Dev environment

### Required on the dev machine

- macOS 14+ (Apple Silicon).
- Python 3.12 (managed via `uv`).
- Node 20+ (managed via `corepack`).
- `pnpm` (via `corepack enable`).
- `uv` (single-binary install).
- Obsidian (latest stable).
- A local LLM server: Ollama (recommended for v0.1 simplicity) or LM Studio.
- Models pulled locally: an instruction-tuned ~14B for synthesis, a ~7B for judging, an embedding model.

### First-run sequence

```bash
git clone <repo>
cd AI_OS
cp config.toml.example config.toml      # then edit vault path
make install                            # uv sync && pnpm install
ollama pull qwen2.5:14b-instruct
ollama pull qwen2.5:7b-instruct
ollama pull nomic-embed-text
uv run orchestrator-ingest              # initial bulk vault ingestion (one-time)
uv run orchestrator-dev                 # start backend (includes always-on file watcher)
pnpm --filter obsidian-plugin build
# symlink plugin into vault's .obsidian/plugins/ and enable in Obsidian
```

Documented in the `README.md` as the canonical quick-start.

## Versioning and releases

- Git tags match roadmap phases: `v0.1.0`, `v0.2.0`, etc. Patch bumps within a phase.
- No semver pretence — single-user prototype. Breaking changes are expected within a phase; tags exist for personal recovery, not for downstream consumers.
- `CHANGELOG.md` deferred until v0.2 — the roadmap doc is the changelog substitute for v0.1.

## What this structure deliberately omits

| Omitted | Why |
|---|---|
| Dockerised dev environment | Mac-native is faster and matches deployment for v0.1. Compose file is staged in `infra/dev/` for when Redis/etc. arrive. |
| CI/CD | Single developer, single machine. A local `make test` pre-commit hook is sufficient. Add CI when collaborators or a GPU-box runner exists. |
| Linting beyond `ruff` + `prettier` | More tooling than the codebase warrants at v0.1 size. |
| Telemetry / observability stack | Local stdout logging is enough until phase 8. Structlog from day one for forward compatibility. |
| Auth between plugin and backend | Localhost-only binding. Tightened in phase 8 when external clients arrive. |
| Database migrations framework | DuckDB schema is reset by re-ingesting. LightRAG manages its own indices. No migration story needed at this stage. |
