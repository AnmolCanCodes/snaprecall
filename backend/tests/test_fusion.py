import pytest

from app.services.search import rrf_fuse

K = 60


def test_single_leg_keeps_order_and_math() -> None:
    fused = rrf_fuse([10, 20], [], K)
    assert [item.image_id for item in fused] == [10, 20]
    assert fused[0].score == pytest.approx(1 / 61)
    assert fused[1].score == pytest.approx(1 / 62)
    assert fused[0].matched_by == ("keyword",)


def test_overlap_sums_scores_and_reports_both_legs() -> None:
    fused = rrf_fuse([1, 2], [2, 3], K)
    top = fused[0]
    assert top.image_id == 2
    assert top.score == pytest.approx(1 / 62 + 1 / 61)
    assert top.matched_by == ("keyword", "semantic")
    assert {item.image_id for item in fused} == {1, 2, 3}


def test_tie_prefers_better_rank_then_newer_id() -> None:
    fused = rrf_fuse([1, 2], [2, 1], K)
    assert fused[0].score == pytest.approx(fused[1].score)
    assert [item.image_id for item in fused] == [2, 1]


def test_cross_leg_tie_goes_to_higher_id() -> None:
    fused = rrf_fuse([5], [9], K)
    assert [item.image_id for item in fused] == [9, 5]


def test_duplicates_within_a_leg_count_once() -> None:
    fused = rrf_fuse([4, 4, 7], [], K)
    assert [item.image_id for item in fused] == [4, 7]
    assert fused[1].score == pytest.approx(1 / 62)


def test_empty_inputs() -> None:
    assert rrf_fuse([], [], K) == []