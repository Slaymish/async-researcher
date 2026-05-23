"""Eval result rendering."""

from __future__ import annotations

import json
from typing import Any

from .metrics import RetrievalEvalSummary


def retrieval_summary_dict(summary: RetrievalEvalSummary) -> dict[str, Any]:
    return {
        "k": summary.k,
        "count": summary.count,
        "mean_precision": summary.mean_precision,
        "mean_recall": summary.mean_recall,
        "hit_rate": summary.hit_rate,
        "rows": [
            {
                "question": row.question,
                "expected_block_ids": sorted(row.expected_block_ids),
                "retrieved_block_ids": row.retrieved_block_ids,
                "precision": row.precision,
                "recall": row.recall,
                "hit": row.hit,
            }
            for row in summary.rows
        ],
    }


def render_retrieval_text(summary: RetrievalEvalSummary) -> str:
    lines = [
        f"retrieval eval: n={summary.count} k={summary.k}",
        f"mean_precision@{summary.k}: {summary.mean_precision:.3f}",
        f"mean_recall@{summary.k}:    {summary.mean_recall:.3f}",
        f"hit_rate@{summary.k}:       {summary.hit_rate:.3f}",
    ]
    if not summary.rows:
        return "\n".join(lines)

    lines.extend(["", "per-question:"])
    for row in summary.rows:
        expected = ", ".join(sorted(row.expected_block_ids)) or "(none)"
        retrieved = ", ".join(row.retrieved_block_ids[: summary.k]) or "(none)"
        lines.append(
            f"- p={row.precision:.3f} r={row.recall:.3f} "
            f"question={row.question!r}"
        )
        lines.append(f"  expected:  {expected}")
        lines.append(f"  retrieved: {retrieved}")
    return "\n".join(lines)


def render_retrieval_json(summary: RetrievalEvalSummary) -> str:
    return json.dumps(retrieval_summary_dict(summary), indent=2, sort_keys=True)
