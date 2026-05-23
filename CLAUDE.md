# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

@AGENTS.md

## Commands

Cross-language commands are wrapped in the `Makefile`:

```bash
make install       # uv sync && pnpm install
make test          # uv run pytest && plugin vitest
make lint          # uv run ruff check . && plugin tsc --noEmit
make format        # ruff format + autofix
make dev           # uv run orchestrator-dev (FastAPI + always-on file watcher)
make ingest        # uv run orchestrator-ingest (one-shot bulk vault ingest)
make plugin-build  # pnpm --filter obsidian-plugin build
make plugin-dev    # esbuild watch mode for the plugin
```

Running a single Python test: `uv run pytest packages/<pkg>/tests/test_x.py::test_name`.
Plugin tests use vitest: `pnpm --filter obsidian-plugin test -- <name>`.

Use `pnpm` throughout — never `npm` or `yarn`.

Load the plugin into Obsidian by symlinking:
```bash
ln -s "$(pwd)/obsidian-plugin" "<vault>/.obsidian/plugins/ai-os"
```
Then enable it in Obsidian → Settings → Community plugins.

## Architecture

Three processes at runtime: **Obsidian** (host) ↔ **orchestrator** (Python FastAPI, `localhost:8765`) ↔ **local LLM server** (Ollama at `:11434`). The orchestrator is monolithic and in-process (ADR-0007): every `packages/*` module is imported directly, and the file watcher runs as an asyncio task inside the same FastAPI process.

### Python backend

- `apps/orchestrator/` — FastAPI backend. Routes (`/surface`, `/research`, `/health`) are thin; logic lives in `flows/`. v0.1 is flat single-turn; v0.2 swaps in LangGraph behind the same interface (ADR-0010).
- `packages/ingestion/` — vault walker, Markdown parser, `^id` injector, file watcher.
- `packages/retrieval/` — DuckDB vector store + LightRAG graph index, hybrid fusion.
- `packages/citation/` — JSON-schema synthesis → AST parse → per-claim verification → bounded repair loop.
- `packages/inference/` — OpenAI-compatible HTTP client (points at Ollama; Phase 7 swaps to llama-swap).
- `packages/memory/` — stub in v0.1; Mem0 integration in v0.2.
- `packages/web/` — stub in v0.1; SearXNG + Crawl4AI in v0.2.
- `eval/harness/` — eval runner + datasets; validates retrieval and citation hypotheses.

Config: one `config.toml` at repo root (gitignored; copy from `config.toml.example`). Secrets via `.env` (ADR-0016).

### Obsidian plugin (`obsidian-plugin/`)

TypeScript plugin built with esbuild. The only HTTP client — talks to the orchestrator over HTTP/JSON (SSE for streaming).

- `src/main.ts` — plugin entry: lifecycle, commands, debounced surfacing trigger.
- `src/api/` — `OrchestratorClient` wrapping `/surface`, `/research`, `/health`.
- `src/surfacing/` — `SurfacingView` (`ItemView`): proactive related-notes side panel.
- `src/research/` — `ResearchQueryModal`, report note writer.
- `src/settings.ts` — settings schema + settings tab.

Output is `main.js` at the plugin root (esbuild, gitignored). TypeScript config is `obsidian-plugin/tsconfig.json`.

### Cross-cutting design rules

1. **Every external system through one adapter package.** No retrieval logic in `apps/orchestrator`; no inference calls in `packages/citation`. Adapters are the swap point for Phase 7 (Ollama → llama-swap) and v0.2 (stub → real Mem0/web).
2. **All data flows carry `^id` block references** (ADR-0012). `^id` is the lingua franca across retrieval, citation, and surfacing. No component may strip it in transit.

### Two load-bearing pipelines

**Citation (ADR-0013):** `packages/citation/synth.py` → `assemble.py` → `ast_parse.py` + `verify.py` → `repair.py`. JSON wire format from LLM → deterministic Markdown render → AST-level claim verification. Do not collapse stages.

**Retrieval (ADR-0011):** LightRAG graph + DuckDB vector, fused in `packages/retrieval/hybrid.py`. Both share `^id` as the join key.

## Planning docs

All architectural reasoning lives in `docs/`:
- `docs/00_VISION.md` — what this is, the two pillars
- `docs/01_MVP_SCOPE.md` — v0.1 scope and success criteria
- `docs/02_COMPONENT_MAP.md` — every component, v0.1 status, interface
- `docs/03_ROADMAP.md` — phased delivery with hard entry-criteria gates
- `docs/04_PROJECT_STRUCTURE.md` — repo layout and rationale
- `docs/05_DECISIONS.md` — ADR log

Source specs (`ArchitectureSpecification.md`, `LocalAgenticRAGArch.md`) at repo root are the north star, not a literal build list (ADR-0002).
