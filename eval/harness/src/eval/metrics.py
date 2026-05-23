"""Metrics for v0.1 evals.

The first v0.1 hypothesis metric is retrieval precision@k against a small
hand-written dataset of expected `^id`s. Citation pass-rate can reuse the same
summary helpers once deep-research evals are added.
"""

from __future__ import annotations

from dataclasses import dataclass


def precision_at_k(retrieved: list[str], expected: set[str], k: int) -> float:
    """Fraction of the top-k retrieved ids that are expected ids."""
    if k <= 0:
        raise ValueError("k must be positive")
    if not retrieved:
        return 0.0
    top = retrieved[:k]
    return len([block_id for block_id in top if block_id in expected]) / k


def recall_at_k(retrieved: list[str], expected: set[str], k: int) -> float:
    """Fraction of expected ids found in the top-k retrieved ids."""
    if k <= 0:
        raise ValueError("k must be positive")
    if not expected:
        return 1.0
    top = set(retrieved[:k])
    return len(top & expected) / len(expected)


@dataclass(frozen=True)
class RetrievalEvalRow:
    question: str
    expected_block_ids: set[str]
    retrieved_block_ids: list[str]
    precision: float
    recall: float

    @property
    def hit(self) -> bool:
        return self.recall > 0.0


@dataclass(frozen=True)
class RetrievalEvalSummary:
    rows: list[RetrievalEvalRow]
    k: int

    @property
    def count(self) -> int:
        return len(self.rows)

    @property
    def mean_precision(self) -> float:
        return _mean([row.precision for row in self.rows])

    @property
    def mean_recall(self) -> float:
        return _mean([row.recall for row in self.rows])

    @property
    def hit_rate(self) -> float:
        return _mean([1.0 if row.hit else 0.0 for row in self.rows])


def summarise_retrieval(rows: list[RetrievalEvalRow], k: int) -> RetrievalEvalSummary:
    if k <= 0:
        raise ValueError("k must be positive")
    return RetrievalEvalSummary(rows=rows, k=k)


def _mean(values: list[float]) -> float:
    if not values:
        return 0.0
    return sum(values) / len(values)
