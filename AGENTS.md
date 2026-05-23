# AGENTS.md

This file provides guidance to Codex (Codex.ai/code) when working with code in this repository.

## Status

Scaffold only — no real implementation yet. Planning lives in `docs/`; the two source specifications (`ArchitectureSpecification.md`, `LocalAgenticRAGArch.md`) at the repo root are the north star, not a literal build list (see ADR-0002). Before extending architecture, read `docs/05_DECISIONS.md` for the ADR log and `docs/02_COMPONENT_MAP.md` for what's `in` / `stub` / `deferred` in v0.1.

## Commands

Cross-language commands are wrapped in the `Makefile`:

```bash
make install       # uv sync && pnpm install
make test          # uv run pytest && pnpm test
make lint          # uv run ruff check . && pnpm lint
make format        # ruff format + autofix
make dev           # uv run orchestrator-dev (FastAPI + always-on file watcher)
make ingest        # uv run orchestrator-ingest (one-shot bulk vault ingest)
make plugin-build  # pnpm --filter obsidian-plugin build
make plugin-dev    # esbuild watch mode for the plugin
```

Running a single Python test: `uv run pytest packages/<pkg>/tests/test_x.py::test_name`. Plugin tests use `vitest`: `pnpm --filter obsidian-plugin test -- <name>`.

The plugin is loaded into Obsidian by symlinking: `ln -s "$(pwd)/apps/obsidian-plugin" "<vault>/.obsidian/plugins/ai-os"` then enabling it in Community plugins.

## Architecture

Three processes at runtime: Obsidian (host) ↔ orchestrator (Python FastAPI, `localhost:8765`) ↔ local LLM server (Ollama at `:11434`). The orchestrator is **monolithic and in-process** (ADR-0007): every `packages/*` module is imported directly, and the file watcher runs as an asyncio task inside the same FastAPI process — no Redis, no message queue, no microservices in v0.1.

Layout:

- `apps/orchestrator/` — FastAPI backend. Routes (`/surface`, `/research`, `/health`) are thin; logic lives in `flows/` (flat functions in v0.1; LangGraph in v0.2 per ADR-0010 — the `research()` signature is the contract, the body changes).
- `apps/obsidian-plugin/` — TypeScript plugin. The only client. Talks to the backend over HTTP/JSON (and SSE for streaming reports).
- `packages/` — Python libraries imported by the orchestrator: `ingestion`, `retrieval`, `citation`, `inference`, `memory` (stub in v0.1), `web` (stub in v0.1).
- `infra/` — `llama-swap/` and `dev/docker-compose.yml` are staged for later phases.
- `eval/harness/` — eval runner + datasets + vault snapshots; this is how hypotheses 1–3 are validated.
- `experiments/` — throwaway notebooks; not packaged, not tested.

### Cross-cutting design rules (from `docs/02_COMPONENT_MAP.md`)

1. **Every external system is accessed through a single adapter package.** No retrieval logic in `apps/orchestrator`, no inference calls in `packages/citation`. Adapters are the swap point — this is what makes Ollama → llama-swap (Phase 7), DuckDB → Redis blackboard, etc., a config change rather than a refactor.
2. **All cross-component data flows carry `^id` block references** (ADR-0012). The `^id` is the lingua franca: retrieval emits chunks tagged with `^id`s; the citation engine consumes them; the surfacing UI renders them as `[[note#^id]]` backlinks. **No component is allowed to strip the `^id` from a chunk in transit** — the citation verifier's link check is the enforcement.

### Two load-bearing pipelines

**Citation (ADR-0013) — three stages, do not collapse:**
1. *Generation* (`packages/citation/synth.py`): the synthesis model emits JSON conforming to a `claim`/`quote`/`^id` schema. JSON is the wire format from the LLM — never free-form prose.
2. *Assembly* (`packages/citation/assemble.py`): deterministic JSON → Markdown render, with citations inlined as `[[note#^id]]`.
3. *Verification* (`packages/citation/ast_parse.py` + `verify.py`): AST walks the **assembled Markdown** (not the JSON) to extract claims; per-claim link check (does `^id` exist?) + judge-model factual-alignment check. Failures hit a bounded repair loop (`repair.py`, default 2 attempts).

**Retrieval (ADR-0011) — hybrid, not pure-either:** LightRAG (entities/relations, cheap incremental updates) + DuckDB (vector similarity + SQL metadata filters). Both indices store `^id` as the join key. The fusion layer is `packages/retrieval/hybrid.py`. Tested explicitly in eval as hypothesis 2 (hybrid beats vector-only).

### Inference chokepoint (ADR-0009, ADR-0005)

**All LLM calls go through `packages/inference/client.py`** speaking the OpenAI HTTP API. The backend URL is a single config value. **No code path in this codebase may send vault content to a cloud LLM** — all inference originated by this system runs on local hardware (Mac v0.1, GPU box Phase 7). Public-web access via `packages/web` (v0.2) — both **search** (SearXNG + DDGS per ADR-0018) and **fetch** (Crawl4AI) — reads external content and is allowed; queries that go to search providers may carry topic signal but never vault content.

### File watcher (ADR-0017)

v0.1 ships a **lightweight always-on file watcher** inside the orchestrator process (`packages/ingestion/watcher.py`, `watchdog`/FSEvents). Scope is strictly ingestion: re-parse, re-`^id`-inject, re-index on save. The v0.3 autonomous daemon **extends this same watcher** with filing + structural-integrity scans — same process, broader responsibilities. Do not split into a separate codebase.

## Conventions

- Python 3.12+, managed by `uv` workspaces (members listed in root `pyproject.toml`). Inter-package deps are `{ workspace = true }` references.
- TS via `pnpm` workspace (`pnpm-workspace.yaml`). Single TS package today (`apps/obsidian-plugin`).
- `ruff` for Python lint/format (`line-length = 100`, rules `E,F,I,B,UP`). `tsc --noEmit` for plugin lint.
- Config is one `config.toml` at repo root, gitignored; copy from `config.toml.example`. Secrets via `.env` (ADR-0016) — no secrets manager until Phase 8.
- Local stores live at `~/Library/Application Support/ai_os/` (`index.duckdb`, `lightrag/`).
- No CI yet — `make test` is the gate.
