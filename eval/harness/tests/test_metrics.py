import pytest
from eval.metrics import (
    RetrievalEvalRow,
    precision_at_k,
    recall_at_k,
    summarise_retrieval,
)
from eval.reports import render_retrieval_json, render_retrieval_text


def test_precision_and_recall_at_k():
    retrieved = ["a", "b", "c", "d"]
    expected = {"b", "d", "x"}

    assert precision_at_k(retrieved, expected, 2) == 0.5
    assert recall_at_k(retrieved, expected, 2) == pytest.approx(1 / 3)
    assert precision_at_k(retrieved, expected, 4) == 0.5
    assert recall_at_k(retrieved, expected, 4) == pytest.approx(2 / 3)


def test_metrics_reject_non_positive_k():
    with pytest.raises(ValueError):
        precision_at_k(["a"], {"a"}, 0)
    with pytest.raises(ValueError):
        recall_at_k(["a"], {"a"}, 0)


def test_summary_and_renderers():
    summary = summarise_retrieval(
        [
            RetrievalEvalRow(
                question="q1",
                expected_block_ids={"a"},
                retrieved_block_ids=["a", "b"],
                precision=0.5,
                recall=1.0,
            ),
            RetrievalEvalRow(
                question="q2",
                expected_block_ids={"x"},
                retrieved_block_ids=["a", "b"],
                precision=0.0,
                recall=0.0,
            ),
        ],
        k=2,
    )

    assert summary.count == 2
    assert summary.mean_precision == 0.25
    assert summary.mean_recall == 0.5
    assert summary.hit_rate == 0.5
    assert "mean_precision@2: 0.250" in render_retrieval_text(summary)
    assert '"mean_recall": 0.5' in render_retrieval_json(summary)
