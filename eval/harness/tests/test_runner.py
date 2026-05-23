import json
from pathlib import Path

import pytest
from eval.runner import load_retrieval_dataset, load_runner_config


def test_load_retrieval_dataset_jsonl_strips_caret_ids(tmp_path: Path):
    dataset = tmp_path / "cases.jsonl"
    dataset.write_text(
        "\n".join(
            [
                json.dumps(
                    {
                        "question": "What mentions citations?",
                        "expected_block_ids": ["^ai-a", "ai-b"],
                    }
                ),
                "",
            ]
        ),
        encoding="utf-8",
    )

    cases = load_retrieval_dataset(dataset)

    assert len(cases) == 1
    assert cases[0].question == "What mentions citations?"
    assert cases[0].expected_block_ids == {"ai-a", "ai-b"}


def test_load_retrieval_dataset_json_cases_object(tmp_path: Path):
    dataset = tmp_path / "cases.json"
    dataset.write_text(
        json.dumps(
            {
                "cases": [
                    {
                        "question": "What mentions retrieval?",
                        "expected_ids": ["ai-r"],
                    }
                ]
            }
        ),
        encoding="utf-8",
    )

    cases = load_retrieval_dataset(dataset)

    assert len(cases) == 1
    assert cases[0].expected_block_ids == {"ai-r"}


def test_load_retrieval_dataset_validates_shape(tmp_path: Path):
    dataset = tmp_path / "bad.json"
    dataset.write_text(json.dumps([{"question": "", "expected_block_ids": []}]))

    with pytest.raises(ValueError, match="question"):
        load_retrieval_dataset(dataset)


def test_load_runner_config_uses_explicit_embedding_dim(tmp_path: Path):
    config = tmp_path / "config.toml"
    db = tmp_path / "custom.duckdb"
    config.write_text(
        f"""
[storage]
data_dir = "{tmp_path.as_posix()}"
duckdb_path = "{db.as_posix()}"
lightrag_dir = "${{data_dir}}/lightrag"

[inference]
base_url = "http://localhost:11434/v1"
api_key = "ollama"
synthesis_model = "synth"
embedding_model = "unknown-local-model"
embedding_dim = 42
judge_model = "judge"
""",
        encoding="utf-8",
    )

    loaded = load_runner_config(config)

    assert loaded.duckdb_path == db
    assert loaded.embedding_model == "unknown-local-model"
    assert loaded.embedding_dim == 42
