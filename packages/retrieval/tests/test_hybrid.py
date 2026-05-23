"""Tests for retrieval.hybrid — pure RRF fusion functions."""

from __future__ import annotations

from retrieval import Chunk, ScoredChunk
from retrieval.hybrid import _candidate_count, _filter_results, _rrf_fuse


def _sc(block_id: str, relpath: str = "a.md", kind: str = "para", score: float = 1.0) -> ScoredChunk:
    return ScoredChunk(
        chunk=Chunk(block_id, relpath, kind, "text", 0, 1, {}, None),
        score=score,
    )


# --- _candidate_count --------------------------------------------------------


def test_candidate_count_always_at_least_k_plus_10():
    assert _candidate_count(1) >= 11
    assert _candidate_count(5) >= 15
    assert _candidate_count(10) >= 20


def test_candidate_count_scales_with_large_k():
    assert _candidate_count(100) == 300


# --- _filter_results ---------------------------------------------------------


def test_filter_results_no_filters_returns_all():
    items = [_sc("a", "notes/a.md"), _sc("b", "archive/b.md")]
    assert _filter_results(items, relpath_prefix=None, kinds=None) == items


def test_filter_results_by_relpath_prefix():
    items = [_sc("a", "notes/a.md"), _sc("b", "archive/b.md"), _sc("c", "notes/c.md")]
    out = _filter_results(items, relpath_prefix="notes/", kinds=None)
    assert [s.chunk.block_id for s in out] == ["a", "c"]


def test_filter_results_by_kind():
    items = [_sc("a", kind="para"), _sc("b", kind="heading"), _sc("c", kind="para")]
    out = _filter_results(items, relpath_prefix=None, kinds=["para"])
    assert [s.chunk.block_id for s in out] == ["a", "c"]


def test_filter_results_by_prefix_and_kind():
    items = [
        _sc("a", "notes/a.md", "para"),
        _sc("b", "notes/b.md", "heading"),
        _sc("c", "archive/c.md", "para"),
    ]
    out = _filter_results(items, relpath_prefix="notes/", kinds=["para"])
    assert [s.chunk.block_id for s in out] == ["a"]


def test_filter_results_empty_kinds_list_returns_nothing():
    items = [_sc("a"), _sc("b")]
    out = _filter_results(items, relpath_prefix=None, kinds=[])
    assert out == []


# --- _rrf_fuse ---------------------------------------------------------------


def test_rrf_fuse_single_list_returns_items_in_order():
    results = [_sc("a"), _sc("b"), _sc("c")]
    out = _rrf_fuse(result_sets=[results], k=3, rank_constant=60)
    assert [s.chunk.block_id for s in out] == ["a", "b", "c"]


def test_rrf_fuse_deduplicates_by_block_id():
    list1 = [_sc("a"), _sc("b")]
    list2 = [_sc("b"), _sc("c")]
    out = _rrf_fuse(result_sets=[list1, list2], k=10, rank_constant=60)
    ids = [s.chunk.block_id for s in out]
    assert len(set(ids)) == len(ids)  # no duplicates
    assert set(ids) == {"a", "b", "c"}


def test_rrf_fuse_promotes_item_appearing_in_multiple_lists():
    # "shared" appears rank-1 in both lists → should outscore items in only one.
    list1 = [_sc("shared"), _sc("only-in-1")]
    list2 = [_sc("shared"), _sc("only-in-2")]
    out = _rrf_fuse(result_sets=[list1, list2], k=3, rank_constant=60)
    assert out[0].chunk.block_id == "shared"


def test_rrf_fuse_respects_k_limit():
    results = [_sc(f"item-{i}") for i in range(20)]
    out = _rrf_fuse(result_sets=[results], k=5, rank_constant=60)
    assert len(out) == 5


def test_rrf_fuse_scores_are_positive():
    results = [_sc("a"), _sc("b")]
    out = _rrf_fuse(result_sets=[results], k=2, rank_constant=60)
    assert all(s.score > 0 for s in out)


def test_rrf_fuse_empty_lists_returns_empty():
    out = _rrf_fuse(result_sets=[[], []], k=10, rank_constant=60)
    assert out == []


def test_rrf_fuse_output_sorted_descending_by_score():
    list1 = [_sc("a"), _sc("b"), _sc("c"), _sc("d"), _sc("e")]
    list2 = [_sc("e"), _sc("d"), _sc("c"), _sc("b"), _sc("a")]
    out = _rrf_fuse(result_sets=[list1, list2], k=5, rank_constant=60)
    scores = [s.score for s in out]
    assert scores == sorted(scores, reverse=True)


def test_rrf_fuse_rank_constant_affects_score_magnitude():
    results = [_sc("a")]
    low_k = _rrf_fuse(result_sets=[results], k=1, rank_constant=1)
    high_k = _rrf_fuse(result_sets=[results], k=1, rank_constant=1000)
    # Lower rank_constant → larger score for rank 1.
    assert low_k[0].score > high_k[0].score


def test_rrf_fuse_uses_first_occurrence_chunk_for_deduplication():
    # When a block_id appears in list1 and list2, the chunk from list1 should be kept.
    sc1 = ScoredChunk(
        chunk=Chunk("same-id", "list1.md", "para", "from list1", 0, 1, {}, None),
        score=1.0,
    )
    sc2 = ScoredChunk(
        chunk=Chunk("same-id", "list2.md", "para", "from list2", 0, 1, {}, None),
        score=0.5,
    )
    out = _rrf_fuse(result_sets=[[sc1], [sc2]], k=1, rank_constant=60)
    assert out[0].chunk.relpath == "list1.md"
