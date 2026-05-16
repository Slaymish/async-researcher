# Researcher Obsidian Plugin

Researcher turns markdown notes into a lightweight async research workflow. Notes are the source of truth; the sidebar is an index over notes with `research-*` frontmatter.

## Development

```bash
pnpm install
pnpm run build
```

## Manual installation

Copy these files into a test vault at `.obsidian/plugins/researcher/`:

- `manifest.json`
- `main.js`
- `styles.css`
- `sidecar/deep_research_stub.py`
- `sidecar/setup-open-deep-research.sh`
- `sidecar/.env.example`

Enable the plugin in Obsidian community plugin settings.

## V1 behavior

- Creates research idea notes in `Research Ideas` by default.
- Captures selected editor text into a new research idea.
- Tracks status in frontmatter.
- Shows a sidebar grouped by research status.
- Starts stub deep research runs from the active research note.
- Shows latest run progress on sidebar cards.
- Generates clarifying questions only when the command is explicitly run.
- Uses Ollama or an OpenAI-compatible `/chat/completions` provider when a model is configured.
- Falls back to deterministic placeholder questions when no model is configured.

## Deep research run contract

The command `Start deep research on active note` creates a folder under `Research Runs`:

- `run.json` — full run request and current status
- `status.json` — compact progress status for UI watching
- `report.md` — final report output

The default runner is the internal stub. Switch **Deep research runner** to **Sidecar process** to spawn a Python sidecar. With an empty script path, the plugin uses:

```text
.obsidian/plugins/researcher/sidecar/deep_research_stub.py
```

The bundled sidecar supports three engines:

- `auto` — use Open Deep Research if importable, otherwise use the stub
- `stub` — always use the deterministic contract-test runner
- `open_deep_research` — require `langchain-ai/open_deep_research` to be importable

For Open Deep Research, install its Python environment separately and point **Sidecar command** at that environment's Python executable. The sidecar invokes the compiled `open_deep_research.deep_researcher` LangGraph and writes `open-deep-research-result.json` alongside `report.md`.

Quick setup from the installed plugin folder:

```bash
cd /path/to/vault/.obsidian/plugins/researcher/sidecar
./setup-open-deep-research.sh
```

Useful environment variables for the sidecar:

- `RESEARCHER_RESEARCH_MODEL`
- `RESEARCHER_SUMMARIZATION_MODEL`
- `RESEARCHER_COMPRESSION_MODEL`
- `RESEARCHER_FINAL_REPORT_MODEL`
- `RESEARCHER_SEARCH_API`
- `RESEARCHER_MAX_ITERATIONS`
- `RESEARCHER_MAX_TOOL_CALLS`
- `RESEARCHER_MAX_CONCURRENCY`

The sidecar does not write API keys into the vault. Configure provider keys in the Python environment.

While Open Deep Research is running, the sidecar writes heartbeat progress to `run.json` and `status.json` so the Obsidian sidebar can keep showing that work is alive even during long graph execution.
