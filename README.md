# AI OS — Async Researcher

A local-first AI system that turns an Obsidian vault from a passive store of notes into an active research collaborator. Runs entirely on local hardware — vault contents never leave the machine.

## What it does

**Proactive surfacing** — as you open or edit a note, the plugin pushes related notes, forgotten threads, and connections you wouldn't have made manually into a side panel.

**Deep research on demand** — ask a complex question and the system retrieves relevant vault content, synthesises a long-form report, and verifies every citation against a real `^id` block in your notes. No hallucinated references. Progress streams live as the local model works.

## Architecture

Three processes at runtime:

```
Obsidian plugin  ↔  FastAPI orchestrator (:8765)  ↔  Ollama (:11434)
```

- **`obsidian-plugin/`** — TypeScript plugin (esbuild). The only HTTP client. Handles surfacing side panel (related notes), deep research modal with live SSE progress, and report note writing.
- **`apps/orchestrator/`** — Python FastAPI backend. Thin routes; logic lives in `flows/`. Runs the always-on file watcher in-process.
- **`packages/`** — Python libraries: `ingestion`, `retrieval`, `citation`, `inference`, `memory` (stub), `web` (stub).
- **`eval/`** — eval harness + datasets for validating retrieval and citation quality.

## Quick start

```bash
# One-time setup
cp config.toml.example config.toml   # edit [vault].path
make install                          # uv sync + pnpm install

# Pull models (adjust to taste)
ollama pull qwen2.5:14b-instruct
ollama pull qwen2.5:7b-instruct
ollama pull nomic-embed-text

# Initial vault ingestion
make ingest

# Start the orchestrator (includes file watcher)
make dev

# Build and symlink the plugin into your vault
make plugin-build
ln -s "$(pwd)/obsidian-plugin" "<vault>/.obsidian/plugins/ai-os"
# Then enable it in Obsidian → Settings → Community plugins
```

## Commands

```bash
make install       # install all dependencies (Python + Node)
make dev           # start FastAPI orchestrator + file watcher
make ingest        # one-shot bulk vault ingestion
make plugin-build  # build obsidian-plugin/main.js
make plugin-dev    # esbuild watch mode
make test          # run Python tests + plugin vitest
make lint          # ruff + tsc --noEmit
make format        # ruff format + autofix
```

## Tech stack

- **Python 3.12** — `uv` workspaces, FastAPI, LightRAG, DuckDB, watchdog
- **TypeScript** — Obsidian API, esbuild
- **Ollama** — local inference via OpenAI-compatible API
- **pnpm** — Node package manager

## Planning docs

All architectural reasoning lives in `docs/`:

| File | Contents |
|------|----------|
| `docs/00_VISION.md` | What this is and who it's for |
| `docs/01_MVP_SCOPE.md` | v0.1 scope and success criteria |
| `docs/02_COMPONENT_MAP.md` | Every component, status, and interface |
| `docs/03_ROADMAP.md` | Phased delivery with entry-criteria gates |
| `docs/04_PROJECT_STRUCTURE.md` | Repo layout and rationale |
| `docs/05_DECISIONS.md` | ADR log |

Source specs (`ArchitectureSpecification.md`, `LocalAgenticRAGArch.md`) at the repo root are the north star — not a literal build list.
