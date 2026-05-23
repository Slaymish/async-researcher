.PHONY: install test lint format dev ingest plugin-build plugin-dev clean

install:
	uv sync --all-packages
	pnpm install

test:
	uv run pytest packages/ apps/ eval/
	pnpm --filter obsidian-plugin test

lint:
	uv run ruff check .
	pnpm --filter obsidian-plugin lint

format:
	uv run ruff format .
	uv run ruff check --fix .

dev:
	uv run orchestrator-dev

ingest:
	uv run orchestrator-ingest

plugin-build:
	pnpm --filter obsidian-plugin build

plugin-dev:
	pnpm --filter obsidian-plugin dev

clean:
	rm -rf .venv node_modules
	find . -type d -name __pycache__ -exec rm -rf {} +
	find . -type d -name .pytest_cache -exec rm -rf {} +
	find . -type d -name dist -exec rm -rf {} +
