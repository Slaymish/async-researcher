"""Configuration regression guards (v0.2.3 step 3).

These tests pin the two invariants we care most about in the mem0ai
integration:

1. **No cloud LLM endpoint.** ADR-0005 forbids vault content reaching cloud
   LLMs from this codebase. mem0ai bypasses our `InferenceClient` chokepoint
   (ADR-0009 trade-off accepted at sign-off), so the only enforcement we
   have on its behalf is "the URL it talks to is local". This test
   asserts the produced config dict never contains an api.openai.com URL.

2. **Telemetry disabled.** mem0ai brings posthog as a transitive. The env
   kill-switch lives in `packages/memory/__init__.py`; this test asserts
   it survives.
"""

from __future__ import annotations

import json
import os
from pathlib import Path

import memory  # ensures __init__.py side effects (env setdefault) run
from memory import MemoryConfig
from memory.adapter import _build_mem0_config


def _cfg(tmp_path: Path) -> MemoryConfig:
    return MemoryConfig(
        data_dir=tmp_path / "mem0",
        llm_base_url="http://localhost:11434/v1",
        llm_model="qwen2.5:14b-instruct",
        embedder_model="nomic-embed-text",
        embedding_dim=768,
        user_id="hamish",
    )


def test_telemetry_env_set_after_package_import():
    # The packages/memory/__init__.py module runs `os.environ.setdefault` at
    # import time. If anyone reorders the import below the mem0 import, this
    # test fails. The `memory` import above is what triggers the setdefault.
    assert memory  # noqa: B015 — kept so the import isn't lint-dropped
    assert os.environ.get("MEM0_TELEMETRY") == "False"


def test_mem0_config_never_targets_openai_dot_com(tmp_path: Path):
    cfg = _cfg(tmp_path)
    raw = json.dumps(_build_mem0_config(cfg))
    # ADR-0005: vault content must not reach cloud LLMs through this system.
    # mem0ai's openai provider defaults to api.openai.com when base_url is
    # omitted. We must always set base_url.
    assert "api.openai.com" not in raw
    assert "openai.com" not in raw


def test_mem0_config_uses_local_endpoint_for_both_llm_and_embedder(tmp_path: Path):
    cfg = _cfg(tmp_path)
    out = _build_mem0_config(cfg)
    assert out["llm"]["config"]["openai_base_url"] == cfg.llm_base_url
    assert out["embedder"]["config"]["openai_base_url"] == cfg.llm_base_url
    assert out["llm"]["config"]["model"] == cfg.llm_model
    assert out["embedder"]["config"]["model"] == cfg.embedder_model


def test_mem0_config_vector_store_is_embedded_qdrant_under_data_dir(tmp_path: Path):
    cfg = _cfg(tmp_path)
    out = _build_mem0_config(cfg)
    vs = out["vector_store"]
    assert vs["provider"] == "qdrant"
    # `on_disk=True` + local path = embedded mode (no network port, no Docker).
    assert vs["config"]["on_disk"] is True
    assert vs["config"]["path"].endswith("/qdrant")
    # dim must match the embedder's reported dim — mismatch will burn a real
    # ingestion run silently otherwise.
    assert vs["config"]["embedding_model_dims"] == cfg.embedding_dim


def test_mem0_config_history_db_under_data_dir(tmp_path: Path):
    cfg = _cfg(tmp_path)
    out = _build_mem0_config(cfg)
    assert out["history_db_path"].endswith("/history.db")
    assert str(cfg.data_dir) in out["history_db_path"]


def test_memory_config_threshold_default_is_signoff_value():
    """Sign-off #5 chose 0.5 (overrode the 0.8 recommendation). If somebody
    quietly bumps the default back to 0.8 in a refactor, this fails."""
    cfg = MemoryConfig(
        data_dir=Path("/tmp/x"),
        llm_base_url="http://localhost:11434/v1",
        llm_model="m",
    )
    assert cfg.add_pass_rate_threshold == 0.5
    assert cfg.recall_k == 8  # sign-off #6
    assert cfg.telemetry is False
