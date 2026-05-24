# Contributing to Lumen

Thanks for your interest. Lumen is a local-first personal knowledge tool, so contributions that preserve the privacy-first design (no vault content leaves the machine) are especially welcome.

## Reporting bugs

Open an issue at [github.com/Slaymish/Lumen/issues](https://github.com/Slaymish/Lumen/issues) using the **Bug report** template. Include:

- Lumen version (from `manifest.json`)
- Obsidian version and OS
- Ollama version and model names
- Any errors from the Obsidian developer console (`Cmd+Option+I` / `Ctrl+Shift+I`) or the orchestrator terminal

## Requesting features

Open an issue using the **Feature request** template. Explain the problem you're solving, not just the solution — this helps fit the idea into the existing architecture.

Before opening, skim `docs/05_DECISIONS.md` (the ADR log) to see if there's prior reasoning that covers the area.

## Submitting a pull request

1. **Fork** the repo and create a branch from `main`.
2. **Set up** the dev environment (see [README.md](README.md#quick-start)).
3. **Make your change.** Keep it focused — one logical change per PR.
4. **Run the checks:**
   ```bash
   make test    # Python tests + plugin vitest
   make lint    # ruff + tsc --noEmit
   ```
5. **Open the PR** against `main`. Fill in the PR template.

A few things that make review faster:

- Link the related issue in the PR description (`Closes #N`).
- If you're changing backend logic, add or update tests in the relevant `packages/*/tests/` directory.
- If you're changing the plugin, test it in Obsidian with the orchestrator running.
- For architecture changes, read `docs/05_DECISIONS.md` first and note any ADRs your change touches.

## Dev setup

```bash
cp config.toml.example config.toml   # fill in [vault].path
make install                          # uv sync + pnpm install
make dev                              # start the orchestrator
make plugin-dev                       # esbuild watch mode
```

Symlink the plugin into a test vault:

```bash
ln -s "$(pwd)/obsidian-plugin" "<vault>/.obsidian/plugins/lumen"
```

Then enable it in **Obsidian → Settings → Community plugins**.

Running a single Python test:

```bash
uv run pytest packages/<pkg>/tests/test_x.py::test_name
```

Running a single plugin test:

```bash
pnpm --filter obsidian-plugin test -- <name>
```

## Design constraints

These are non-negotiable for any contribution:

- **No vault content to cloud services.** All LLM inference must remain local (Ollama or a self-hosted endpoint). See ADR-0005.
- **All LLM calls through `packages/inference/client.py`** (with the documented Mem0 exception). See ADR-0009.
- **All data must carry `^id` block references** through retrieval, citation, and surfacing. No component may strip them in transit. See ADR-0012.

## Licence

By contributing, you agree your contributions will be licensed under the [MIT Licence](LICENSE).
