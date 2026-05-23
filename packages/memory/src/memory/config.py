"""MemoryConfig — boundary type, no mem0ai imports.

Plan §"Package surface". This shape is the contract `apps/orchestrator`
builds from `config.toml` and passes into `Memory(config)`. Keep it free
of mem0ai types so swapping the underlying SDK (or rolling our own later)
doesn't ripple through callers.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path


@dataclass(frozen=True)
class MemoryConfig:
    # Filesystem
    data_dir: Path                          # ~/Library/Application Support/ai_os/mem0/

    # LLM (Ollama OpenAI-compatible). Per ADR-0022 we accept that mem0ai's
    # internal calls bypass packages/inference; they still target the same
    # local endpoint, so ADR-0005 (local-only) is preserved.
    llm_base_url: str                       # e.g. "http://localhost:11434/v1"
    llm_model: str                          # synthesis-grade model
    llm_api_key: str = "ollama"             # Ollama ignores; placeholder for SDK

    # Embedder (same backend)
    embedder_model: str = "nomic-embed-text"
    embedding_dim: int = 768

    # Agent Mode identity (spec §"Storage Topologies and Autonomous Initialization")
    user_id: str = "default"

    # Behaviour knobs (sign-off #5, #6)
    recall_k: int = 8
    add_pass_rate_threshold: float = 0.5    # sign-off chose 0.5 (vs 0.8 default)

    # Hard-coded off; the env var in __init__.py is the primary disable.
    telemetry: bool = False

    # Additional metadata passed to mem0ai's per-fact `metadata` dict on
    # every add(). Useful for tagging the running orchestrator version etc.
    base_metadata: dict[str, str] = field(default_factory=dict)
