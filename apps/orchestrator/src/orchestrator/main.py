"""FastAPI app entry + CLI hooks. See docs/01_MVP_SCOPE.md, ADR-0017."""

from __future__ import annotations

import argparse
import asyncio
import logging
from contextlib import asynccontextmanager
from pathlib import Path

import uvicorn
from fastapi import FastAPI
from inference import InferenceClient, InferenceConfig
from ingestion import ingest, ingest_file, watch
from retrieval import DuckDBStore, Retriever

from .config import AppConfig, load_config
from .routes.health import router as health_router
from .routes.research import router as research_router
from .routes.surface import router as surface_router

log = logging.getLogger(__name__)


def _build_inference_config(cfg: AppConfig) -> InferenceConfig:
    return InferenceConfig(
        base_url=cfg.inference.base_url,
        api_key=cfg.inference.api_key,
        synthesis_model=cfg.inference.synthesis_model,
        embedding_model=cfg.inference.embedding_model,
        judge_model=cfg.inference.judge_model,
        timeout_s=cfg.inference.timeout_s,
    )


@asynccontextmanager
async def _lifespan(app: FastAPI):
    cfg: AppConfig = app.state.config
    store = DuckDBStore(
        cfg.storage.duckdb_path,
        cfg.inference.embedding_dim,
        read_only=True,
    )
    client = InferenceClient(_build_inference_config(cfg))
    app.state.store = store
    app.state.client = client
    app.state.vault_path = cfg.vault.path

    async def _on_change(path: Path) -> None:
        try:
            rep = await ingest_file(path, cfg.vault.path, store, client)
            log.info("ingested %s: %s", path, rep.as_dict())
        except Exception:
            log.exception("ingest_file failed for %s", path)

    watcher_task = asyncio.create_task(
        watch(
            cfg.vault.path,
            _on_change,
            debounce_ms=cfg.watcher.debounce_ms,
            ignore_globs=cfg.watcher.ignore_globs,
        ),
        name="ingestion-watcher",
    )
    log.info("orchestrator ready. vault=%s db=%s", cfg.vault.path, cfg.storage.duckdb_path)
    try:
        yield
    finally:
        watcher_task.cancel()
        try:
            await watcher_task
        except asyncio.CancelledError:
            pass
        await client.aclose()
        store.close()


def create_app(config: AppConfig | None = None) -> FastAPI:
    cfg = config or load_config()
    app = FastAPI(title="AI OS Orchestrator", version="0.0.0", lifespan=_lifespan)
    app.state.config = cfg
    app.include_router(health_router)
    app.include_router(research_router)
    app.include_router(surface_router)
    return app


def _setup_logging() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )


def dev() -> None:
    """Entry point for `orchestrator-dev` / `ai-os serve`. Starts FastAPI + file watcher."""
    _setup_logging()
    cfg = load_config()
    uvicorn.run(
        "orchestrator.main:create_app",
        factory=True,
        host=cfg.server.host,
        port=cfg.server.port,
        log_level="info",
        reload=False,
    )


def ai_os_cli() -> None:
    """Entry point for the `ai-os` command. Dispatches subcommands."""
    _setup_logging()
    parser = argparse.ArgumentParser(
        prog="ai-os",
        description="AI OS — local-first AI assistant backend for Obsidian.",
    )
    sub = parser.add_subparsers(dest="cmd", metavar="<command>")

    sub.add_parser("serve", help="Start the orchestrator server (FastAPI + file watcher).")
    sub.add_parser("setup", help="Interactive first-time setup wizard.")

    ingest_p = sub.add_parser("ingest", help="Bulk-ingest the vault into the index.")
    ingest_p.add_argument("--dry-run", action="store_true", help="Parse only; no writes.")
    ingest_p.add_argument("--force", action="store_true", help="Re-process unchanged files.")

    query_p = sub.add_parser("query", help="Query the index (smoke test).")
    query_p.add_argument("query", help="Natural-language query string.")
    query_p.add_argument("-k", type=int, default=5, help="Top-k results (default 5).")
    query_p.add_argument("--prefix", default=None)
    query_p.add_argument("--kind", action="append",
                         choices=["heading", "para", "list_item", "code", "table"])

    research_p = sub.add_parser("research", help="Run a single deep research query.")
    research_p.add_argument("query")
    research_p.add_argument("-k", type=int, default=20)
    research_p.add_argument("--repair", type=int, default=2)
    research_p.add_argument("--skip-alignment", action="store_true")

    args = parser.parse_args()

    if args.cmd == "serve":
        dev()
    elif args.cmd == "setup":
        from .setup_wizard import setup
        setup()
    elif args.cmd == "ingest":
        ingest_cli(args)
    elif args.cmd == "query":
        import asyncio
        raise SystemExit(asyncio.run(_run_query(args)))
    elif args.cmd == "research":
        import asyncio
        raise SystemExit(asyncio.run(_run_research(args)))
    else:
        parser.print_help()


async def _run_ingest(args: argparse.Namespace) -> int:
    cfg = load_config()
    store = DuckDBStore(cfg.storage.duckdb_path, cfg.inference.embedding_dim)
    client = InferenceClient(_build_inference_config(cfg))
    try:
        rep = await ingest(
            cfg.vault.path,
            store,
            client,
            ignore_globs=cfg.watcher.ignore_globs,
            dry_run=args.dry_run,
            force=args.force,
        )
        print(rep.as_dict())
        return 0
    finally:
        await client.aclose()
        store.close()


def ingest_cli(args: argparse.Namespace | None = None) -> None:
    """Entry point for `orchestrator-ingest` / `ai-os ingest`. One-shot bulk ingestion."""
    _setup_logging()
    if args is None:
        parser = argparse.ArgumentParser(prog="orchestrator-ingest")
        parser.add_argument("--dry-run", action="store_true", help="No file writes, no embedding.")
        parser.add_argument("--force", action="store_true", help="Re-process unchanged files.")
        args = parser.parse_args()
    raise SystemExit(asyncio.run(_run_ingest(args)))


async def _run_query(args: argparse.Namespace) -> int:
    cfg = load_config()
    store = DuckDBStore(cfg.storage.duckdb_path, cfg.inference.embedding_dim)
    client = InferenceClient(_build_inference_config(cfg))
    try:
        retriever = Retriever(store, client)
        results = await retriever.retrieve(
            args.query,
            k=args.k,
            relpath_prefix=args.prefix,
            kinds=args.kind or None,
        )
        for i, sc in enumerate(results, 1):
            head = sc.chunk.text.replace("\n", " ")[:120]
            print(f"{i:>2}. {sc.score:.3f}  [[{sc.chunk.relpath}#^{sc.chunk.block_id}]]")
            print(f"      {head}")
        if not results:
            print("(no results)")
        return 0
    finally:
        await client.aclose()
        store.close()


async def _run_research(args: argparse.Namespace) -> int:
    from .flows.research_flow import research

    cfg = load_config()
    store = DuckDBStore(cfg.storage.duckdb_path, cfg.inference.embedding_dim)
    client = InferenceClient(_build_inference_config(cfg))
    try:
        result = await research(
            args.query,
            store=store,
            client=client,
            k=args.k,
            max_repair_attempts=args.repair,
            skip_alignment=args.skip_alignment,
        )
        print(result.markdown)
        print("---")
        print(
            f"attempts={result.attempts}  "
            f"pass_rate={result.verification.pass_rate:.2%}  "
            f"failures={len(result.verification.failures)}"
        )
        for f in result.verification.failures:
            print(f"  [{f.kind.value}] {f.section_heading}: {f.detail}")
        return 0
    finally:
        await client.aclose()
        store.close()


def research_cli() -> None:
    """Entry point for `orchestrator-research`. Single-turn deep research."""
    _setup_logging()
    parser = argparse.ArgumentParser(prog="orchestrator-research")
    parser.add_argument("query")
    parser.add_argument("-k", type=int, default=20)
    parser.add_argument("--repair", type=int, default=2, help="Max repair attempts.")
    parser.add_argument(
        "--skip-alignment",
        action="store_true",
        help="Skip the judge-model alignment check (faster; deterministic-only verification).",
    )
    args = parser.parse_args()
    raise SystemExit(asyncio.run(_run_research(args)))


def query_cli() -> None:
    """Entry point for `orchestrator-query`. Smoke-test retrieval against live DB."""
    logging.basicConfig(level=logging.WARNING)
    parser = argparse.ArgumentParser(prog="orchestrator-query")
    parser.add_argument("query", help="Natural-language query string.")
    parser.add_argument("-k", type=int, default=5, help="Top-k results.")
    parser.add_argument(
        "--prefix", default=None, help="Limit to relpaths under this prefix."
    )
    parser.add_argument(
        "--kind",
        action="append",
        choices=["heading", "para", "list_item", "code", "table"],
        help="Restrict to one or more block kinds (repeatable).",
    )
    args = parser.parse_args()
    raise SystemExit(asyncio.run(_run_query(args)))
