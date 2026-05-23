"""Tests for memory.adapter — _extract_results, _to_fact, and Memory helpers."""

from __future__ import annotations

from datetime import datetime
from pathlib import Path

from memory.adapter import _extract_results, _to_fact


# --- _extract_results --------------------------------------------------------


def test_extract_results_from_v1_dict():
    raw = {"results": [{"memory": "fact A"}, {"memory": "fact B"}]}
    out = _extract_results(raw)
    assert len(out) == 2
    assert out[0]["memory"] == "fact A"


def test_extract_results_from_bare_list():
    raw = [{"memory": "fact A"}, {"memory": "fact B"}]
    out = _extract_results(raw)
    assert len(out) == 2


def test_extract_results_empty_dict():
    assert _extract_results({}) == []
    assert _extract_results({"results": []}) == []


def test_extract_results_empty_list():
    assert _extract_results([]) == []


def test_extract_results_none_results_key():
    assert _extract_results({"results": None}) == []


def test_extract_results_unexpected_type_returns_empty():
    assert _extract_results(None) == []
    assert _extract_results(42) == []
    assert _extract_results("string") == []


# --- _to_fact ----------------------------------------------------------------


def test_to_fact_reads_memory_field():
    item = {"id": "abc", "memory": "some fact", "score": 0.9}
    fact = _to_fact(item)
    assert fact.id == "abc"
    assert fact.text == "some fact"
    assert fact.score == 0.9


def test_to_fact_falls_back_to_text_field():
    item = {"id": "xyz", "text": "older fact", "score": 0.5}
    fact = _to_fact(item)
    assert fact.text == "older fact"


def test_to_fact_memory_takes_priority_over_text():
    item = {"id": "x", "memory": "mem value", "text": "text value"}
    fact = _to_fact(item)
    assert fact.text == "mem value"


def test_to_fact_missing_text_fields_gives_empty_string():
    fact = _to_fact({})
    assert fact.text == ""


def test_to_fact_parses_iso_created_at():
    item = {"memory": "f", "created_at": "2024-03-15T12:00:00"}
    fact = _to_fact(item)
    assert isinstance(fact.created_at, datetime)
    assert fact.created_at.year == 2024
    assert fact.created_at.month == 3


def test_to_fact_parses_created_at_with_trailing_z():
    item = {"memory": "f", "created_at": "2024-06-01T00:00:00Z"}
    fact = _to_fact(item)
    assert isinstance(fact.created_at, datetime)
    assert fact.created_at.year == 2024


def test_to_fact_invalid_created_at_returns_none():
    item = {"memory": "f", "created_at": "not-a-date"}
    fact = _to_fact(item)
    assert fact.created_at is None


def test_to_fact_missing_created_at_returns_none():
    fact = _to_fact({"memory": "f"})
    assert fact.created_at is None


def test_to_fact_preserves_metadata():
    item = {"memory": "f", "metadata": {"source": "research", "run_id": "123"}}
    fact = _to_fact(item)
    assert fact.metadata == {"source": "research", "run_id": "123"}


def test_to_fact_empty_metadata_gives_empty_dict():
    item = {"memory": "f", "metadata": None}
    fact = _to_fact(item)
    assert fact.metadata == {}


def test_to_fact_score_defaults_to_zero():
    fact = _to_fact({"memory": "f"})
    assert fact.score == 0.0


def test_to_fact_id_stringified():
    fact = _to_fact({"memory": "f", "id": 42})
    assert fact.id == "42"
