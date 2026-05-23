from pathlib import Path

import pytest
from orchestrator.config import load_config


def _write_config(path: Path, inference: str) -> None:
    path.write_text(
        f"""
[vault]
path = "{path.parent.as_posix()}/vault"
inbox_dirs = []

[storage]
data_dir = "{path.parent.as_posix()}/data"
duckdb_path = "${{data_dir}}/index.duckdb"
lightrag_dir = "${{data_dir}}/lightrag"

[inference]
base_url = "http://localhost:11434/v1"
api_key = "ollama"
synthesis_model = "synth"
{inference}
judge_model = "judge"
timeout_s = 123
""",
        encoding="utf-8",
    )


def test_load_config_accepts_unknown_embedding_model_with_explicit_dim(tmp_path: Path):
    config_path = tmp_path / "config.toml"
    _write_config(
        config_path,
        'embedding_model = "unknown-local-model"\nembedding_dim = 42',
    )

    config = load_config(config_path)

    assert config.inference.embedding_model == "unknown-local-model"
    assert config.inference.embedding_dim == 42
    assert config.inference.timeout_s == 123


def test_load_config_rejects_unknown_embedding_model_without_dim(tmp_path: Path):
    config_path = tmp_path / "config.toml"
    _write_config(config_path, 'embedding_model = "unknown-local-model"')

    with pytest.raises(ValueError, match="Unknown embedding_dim"):
        load_config(config_path)
