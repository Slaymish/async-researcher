"""`eval-run` entry point.

Dataset format is intentionally boring:

JSONL:
    {"question": "...", "expected_block_ids": ["ai-..."]}

or JSON:
    [{"question": "...", "expected_block_ids": ["ai-..."]}]

The ids are bare block ids without a leading `^`, matching retrieval.Chunk.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import tomllib
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from inference import InferenceClient, InferenceConfig
from retrieval import DuckDBStore, Retriever

from .metrics import (
    RetrievalEvalRow,
    precision_at_k,
    recall_at_k,
    summarise_retrieval,
)
from .reports import render_retrieval_json, render_retrieval_text


@dataclass(frozen=True)
class RetrievalEvalCase:
    question: str
    expected_block_ids: set[str]


@dataclass(frozen=True)
class RunnerConfig:
    duckdb_path: Path
    base_url: str
    api_key: str
    embedding_model: str
    embedding_dim: int
    synthesis_model: str = ""
    judge_model: str = ""


def load_retrieval_dataset(path: Path) -> list[RetrievalEvalCase]:
    raw = path.read_text(encoding="utf-8")
    records: list[Any]
    if path.suffix == ".jsonl":
        records = [json.loads(line) for line in raw.splitlines() if line.strip()]
    else:
        payload = json.loads(raw)
        if isinstance(payload, dict):
            records = payload.get("cases", [])
        else:
            records = payload
    cases: list[RetrievalEvalCase] = []
    for i, record in enumerate(records, 1):
        if not isinstance(record, dict):
            raise ValueError(f"dataset row {i} must be an object")
        question = str(record.get("question", "")).strip()
        expected = record.get("expected_block_ids", record.get("expected_ids", []))
        if not question:
            raise ValueError(f"dataset row {i} missing non-empty question")
        if not isinstance(expected, list) or not all(isinstance(x, str) for x in expected):
            raise ValueError(f"dataset row {i} expected_block_ids must be a list[str]")
        cases.append(
            RetrievalEvalCase(
                question=question,
                expected_block_ids={block_id.removeprefix("^") for block_id in expected},
            )
        )
    return cases


async def run_retrieval_eval(
    cases: list[RetrievalEvalCase],
    *,
    store: DuckDBStore,
    client: InferenceClient,
    k: int,
) -> list[RetrievalEvalRow]:
    retriever = Retriever(store, client)
    rows: list[RetrievalEvalRow] = []
    for case in cases:
        results = await retriever.retrieve(case.question, k=k)
        retrieved = [sc.chunk.block_id for sc in results]
        rows.append(
            RetrievalEvalRow(
                question=case.question,
                expected_block_ids=case.expected_block_ids,
                retrieved_block_ids=retrieved,
                precision=precision_at_k(retrieved, case.expected_block_ids, k),
                recall=recall_at_k(retrieved, case.expected_block_ids, k),
            )
        )
    return rows


def load_runner_config(path: Path | None) -> RunnerConfig:
    cfg_path = path or _default_config_path()
    with cfg_path.open("rb") as f:
        raw = tomllib.load(f)
    storage = raw["storage"]
    inference = raw["inference"]
    data_dir = _expand_path(storage["data_dir"])
    embedding_model = inference["embedding_model"]
    embedding_dim = int(inference["embedding_dim"]) if "embedding_dim" in inference else (
        _default_embedding_dim(embedding_model)
    )
    return RunnerConfig(
        duckdb_path=_expand_path(storage["duckdb_path"], data_dir=data_dir),
        base_url=inference["base_url"],
        api_key=inference.get("api_key", ""),
        embedding_model=embedding_model,
        embedding_dim=embedding_dim,
        synthesis_model=inference.get("synthesis_model", ""),
        judge_model=inference.get("judge_model", ""),
    )


def _default_config_path() -> Path:
    env = os.environ.get("AI_OS_CONFIG")
    if env:
        return Path(env).resolve()
    cwd = Path.cwd().resolve()
    for parent in (cwd, *cwd.parents):
        candidate = parent / "config.toml"
        if candidate.is_file():
            return candidate
    raise FileNotFoundError("config.toml not found; pass --config or set AI_OS_CONFIG")


def _expand_path(value: str, *, data_dir: Path | None = None) -> Path:
    s = value
    if data_dir is not None:
        s = s.replace("${data_dir}", str(data_dir))
    return Path(os.path.expanduser(s)).resolve()


def _default_embedding_dim(model: str) -> int:
    dims = {
        "nomic-embed-text": 768,
        "mxbai-embed-large": 1024,
        "bge-large": 1024,
    }
    try:
        return dims[model]
    except KeyError as e:
        raise ValueError(
            f"Unknown embedding dimension for {model!r}; pass --embedding-dim "
            "or set [inference].embedding_dim"
        ) from e


async def _run(args: argparse.Namespace) -> int:
    cfg = load_runner_config(args.config)
    duckdb_path = args.db or cfg.duckdb_path
    embedding_dim = args.embedding_dim or cfg.embedding_dim
    cases = load_retrieval_dataset(args.dataset)

    store = DuckDBStore(duckdb_path, embedding_dim, read_only=True)
    client = InferenceClient(
        InferenceConfig(
            base_url=args.base_url or cfg.base_url,
            api_key=args.api_key if args.api_key is not None else cfg.api_key,
            synthesis_model=cfg.synthesis_model or "unused",
            embedding_model=args.embedding_model or cfg.embedding_model,
            judge_model=cfg.judge_model or "unused",
        )
    )
    try:
        rows = await run_retrieval_eval(cases, store=store, client=client, k=args.k)
        summary = summarise_retrieval(rows, args.k)
        print(render_retrieval_json(summary) if args.json else render_retrieval_text(summary))
        return 0 if summary.mean_recall >= args.min_mean_recall else 1
    finally:
        await client.aclose()
        store.close()


def main() -> None:
    parser = argparse.ArgumentParser(prog="eval-run")
    parser.add_argument("dataset", type=Path, help="JSON/JSONL retrieval eval dataset.")
    parser.add_argument("-k", type=int, default=5, help="Top-k cutoff.")
    parser.add_argument("--config", type=Path, default=None, help="Path to config.toml.")
    parser.add_argument("--db", type=Path, default=None, help="Override DuckDB index path.")
    parser.add_argument("--base-url", default=None, help="Override OpenAI-compatible base URL.")
    parser.add_argument("--api-key", default=None, help="Override API key.")
    parser.add_argument("--embedding-model", default=None, help="Override embedding model.")
    parser.add_argument("--embedding-dim", type=int, default=None, help="Override embedding dim.")
    parser.add_argument(
        "--min-mean-recall",
        type=float,
        default=0.0,
        help="Exit non-zero if mean recall@k is below this threshold.",
    )
    parser.add_argument("--json", action="store_true", help="Print JSON instead of text.")
    args = parser.parse_args()
    raise SystemExit(asyncio.run(_run(args)))
