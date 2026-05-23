"""Memory adapter — wraps mem0ai with our `Memory` class.

Per ADR-0022 (v0.2.3): mem0ai is configured with the `openai` provider for
both LLM and embedder, pointed at our local Ollama OpenAI-compatible
endpoint. This deviates from ADR-0009 (single chokepoint) — mem0ai's
internal calls do not pass through `packages/inference.client` — but it
preserves ADR-0005 (local-only) because the endpoint is the same Ollama
URL our `InferenceClient` already targets. Swapping to a llama-swap URL in
Phase 7 is therefore two URL flips, not one.

The vector store is mem0ai's embedded qdrant (file-backed, no Docker), with
storage under `<data_dir>/qdrant/`. `history.db` is mem0ai's SQLite history
sidecar.
"""

from __future__ import annotations

import logging
from datetime import datetime
from typing import Any

from mem0 import AsyncMemory

from .config import MemoryConfig
from .types import Fact

log = logging.getLogger(__name__)


def _build_mem0_config(cfg: MemoryConfig) -> dict[str, Any]:
    """Translate our boundary `MemoryConfig` into mem0ai's nested config dict.

    Pulling this into a free function — and never letting it touch a default
    "use openai.com" path — is the configuration regression guard. The unit
    tests assert the produced dict NEVER contains an api.openai.com URL.
    """
    data_dir = cfg.data_dir
    return {
        "llm": {
            "provider": "openai",
            "config": {
                "model": cfg.llm_model,
                "openai_base_url": cfg.llm_base_url,
                "api_key": cfg.llm_api_key,
            },
        },
        "embedder": {
            "provider": "openai",
            "config": {
                "model": cfg.embedder_model,
                "openai_base_url": cfg.llm_base_url,
                "api_key": cfg.llm_api_key,
                "embedding_dims": cfg.embedding_dim,
            },
        },
        "vector_store": {
            "provider": "qdrant",
            "config": {
                "collection_name": "ai_os",
                "embedding_model_dims": cfg.embedding_dim,
                # `on_disk=True` + `path=` keeps qdrant fully embedded; no
                # network port, no Docker. The path is created on first use.
                "on_disk": True,
                "path": str(data_dir / "qdrant"),
            },
        },
        "history_db_path": str(data_dir / "history.db"),
        "version": "v1.1",
    }


class Memory:
    """Async wrapper around mem0ai. Public API: `recall`, `add`, `aclose`.

    Lazy-initialises the underlying `AsyncMemory` on first use so importing
    the orchestrator doesn't blow up on a missing or unwritable data_dir
    until somebody actually tries to read or write a fact.
    """

    def __init__(self, config: MemoryConfig) -> None:
        self.config = config
        self._client: AsyncMemory | None = None

    def _ensure_client(self) -> AsyncMemory:
        if self._client is None:
            # mem0ai's AsyncMemory.from_config builds + validates the inner
            # store config. Directory creation happens lazily inside qdrant
            # on first add/search; the data_dir parent must already exist.
            self.config.data_dir.mkdir(parents=True, exist_ok=True)
            mem0_cfg = _build_mem0_config(self.config)
            self._client = AsyncMemory.from_config(mem0_cfg)
            log.info("memory: mem0ai initialised at %s", self.config.data_dir)
        return self._client

    async def recall(self, query: str, *, k: int | None = None) -> list[Fact]:
        """Tri-signal search via mem0ai. Returns up to `k` facts (default cfg.recall_k).

        mem0ai's `search()` does the semantic + (configurable) lexical fusion
        internally; we just unwrap its result list into our `Fact` shape so
        consumers never see SDK-specific types.
        """
        k = k if k is not None else self.config.recall_k
        client = self._ensure_client()
        raw = await client.search(
            query,
            user_id=self.config.user_id,
            top_k=k,
        )
        return [_to_fact(item) for item in _extract_results(raw)]

    async def add(
        self,
        text: str,
        *,
        metadata: dict[str, Any] | None = None,
    ) -> None:
        """Add one fact to memory.

        Per sign-off #4 we call this once per successful research run, with
        the merged summary as `text` and run metadata in `metadata`. mem0ai's
        ADD pipeline (with `infer=True`) extracts atomic facts from the
        summary so the store doesn't accumulate paragraph-long records.
        """
        client = self._ensure_client()
        merged_metadata = {**self.config.base_metadata, **(metadata or {})}
        await client.add(
            text,
            user_id=self.config.user_id,
            metadata=merged_metadata or None,
            infer=True,
        )
        log.info(
            "memory: added fact user_id=%s len=%d metadata_keys=%s",
            self.config.user_id,
            len(text),
            sorted(merged_metadata.keys()),
        )

    async def list_recent(self, *, limit: int = 20) -> list[Fact]:
        """Dump up to `limit` recent facts. Used by `orchestrator-memory list`."""
        client = self._ensure_client()
        raw = await client.get_all(
            filters={"user_id": self.config.user_id},
            top_k=limit,
        )
        return [_to_fact(item) for item in _extract_results(raw)]

    async def wipe(self) -> None:
        """Delete every fact for this user_id. Used by `orchestrator-memory wipe`."""
        client = self._ensure_client()
        await client.delete_all(user_id=self.config.user_id)
        log.warning("memory: wiped all facts for user_id=%s", self.config.user_id)

    async def aclose(self) -> None:
        # mem0ai's AsyncMemory doesn't expose an async close today; placeholder
        # for the future SDK shape and for parity with InferenceClient.aclose.
        self._client = None


def _extract_results(raw: Any) -> list[dict[str, Any]]:
    """mem0ai's search/get_all return either a `{"results": [...]}` dict
    (v1.1+) or a bare list (older). Normalise to a list of dicts."""
    if isinstance(raw, dict):
        return list(raw.get("results", []) or [])
    if isinstance(raw, list):
        return list(raw)
    return []


def _to_fact(item: dict[str, Any]) -> Fact:
    """Project mem0ai's result dict into our `Fact` boundary type.

    mem0ai shapes vary across versions; we read defensively rather than
    assert. The text field is `memory` in current versions and `text` in
    older ones — try both.
    """
    text = item.get("memory") or item.get("text") or ""
    created_at_raw = item.get("created_at")
    created_at: datetime | None = None
    if isinstance(created_at_raw, str):
        try:
            created_at = datetime.fromisoformat(created_at_raw.rstrip("Z"))
        except ValueError:
            created_at = None
    return Fact(
        id=str(item.get("id", "")),
        text=text,
        score=float(item.get("score", 0.0)),
        created_at=created_at,
        metadata=dict(item.get("metadata") or {}),
    )
