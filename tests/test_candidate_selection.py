from copy import deepcopy

import pytest

from src.candidate_selection import (
    VOLUME_TIERS,
    build_reader_topic_angle,
    canonical_keyword_key,
    select_related_keyword_candidates,
)


def search_ads_row(keyword, volume, *, parent="미국 주식", marker=None):
    return {
        "keyword": keyword,
        "monthly_search_estimate": volume,
        "volume_censored": False,
        "pc_raw": str(volume // 3),
        "mobile_raw": str(volume - volume // 3),
        "parent_keyword": parent,
        "source": "Naver Search Ads API",
        "source_url": "https://example.test/search-ads",
        "marker": marker or keyword,
    }


def test_selection_round_robins_across_ordered_volume_tiers():
    rows = [search_ads_row(f"키워드{i}", 900 - i * 50) for i in range(9)]

    selected = select_related_keyword_candidates(rows, 6)

    assert [row["keyword"] for row in selected] == [
        "키워드0",
        "키워드3",
        "키워드6",
        "키워드1",
        "키워드4",
        "키워드7",
    ]
    assert [row["volume_tier"] for row in selected] == [
        "high",
        "mid",
        "long_tail",
        "high",
        "mid",
        "long_tail",
    ]
    assert VOLUME_TIERS == ("high", "mid", "long_tail")


def test_selection_preserves_all_metadata_without_mutating_input_rows():
    rows = [
        search_ads_row("높은 수요", 900, marker="keep-high"),
        search_ads_row("중간 수요", 500, marker="keep-mid"),
        search_ads_row("긴 꼬리", 100, marker="keep-tail"),
    ]
    original = deepcopy(rows)

    selected = select_related_keyword_candidates(rows, 3)

    assert rows == original
    assert [row["marker"] for row in selected] == [
        "keep-high",
        "keep-mid",
        "keep-tail",
    ]
    assert all(row["parent_keyword"] == "미국 주식" for row in selected)
    assert all(row["source"] == "Naver Search Ads API" for row in selected)
    assert all(row["source_url"] == "https://example.test/search-ads" for row in selected)


def test_exact_seed_is_included_once_and_no_unreturned_seed_is_fabricated():
    rows = [
        search_ads_row("상위1", 900),
        search_ads_row("상위2", 800),
        search_ads_row("중간1", 500),
        search_ads_row("중간2", 400),
        search_ads_row("롱테일1", 100),
        search_ads_row("미국주식", 90, marker="exact-seed"),
        search_ads_row("미국 주식", 80, marker="format-duplicate"),
    ]

    selected = select_related_keyword_candidates(
        rows,
        4,
        seed_keyword="  미국   주식 ",
    )

    assert selected[0]["marker"] == "exact-seed"
    assert sum(row["keyword"].replace(" ", "") == "미국주식" for row in selected) == 1
    assert len(selected) == 4

    without_match = select_related_keyword_candidates(
        rows[:-2],
        2,
        seed_keyword="미국 주식",
    )
    assert [row["keyword"] for row in without_match] == ["상위1", "중간1"]


def test_invalid_rows_are_skipped_and_limit_is_an_upper_bound():
    rows = [
        search_ads_row("유효1", 100),
        {"keyword": "볼륨 없음"},
        {"keyword": "음수", "monthly_search_estimate": -1},
        {"keyword": "무한", "monthly_search_estimate": float("inf")},
        {"keyword": "   ", "monthly_search_estimate": 20},
        "not-a-row",
        search_ads_row("유효2", 10),
    ]

    selected = select_related_keyword_candidates(rows, 20)

    assert {row["keyword"] for row in selected} == {"유효1", "유효2"}
    assert len(selected) == 2


@pytest.mark.parametrize("limit", [-1, -20])
def test_negative_limit_is_rejected(limit):
    with pytest.raises(ValueError, match="non-negative"):
        select_related_keyword_candidates([], limit)


@pytest.mark.parametrize("limit", [1.5, "3", True])
def test_non_integer_limit_is_rejected(limit):
    with pytest.raises(TypeError, match="integer"):
        select_related_keyword_candidates([], limit)


def test_zero_limit_does_not_consume_rows():
    def fail_if_consumed():
        raise AssertionError("rows were consumed")
        yield  # pragma: no cover

    assert select_related_keyword_candidates(fail_if_consumed(), 0) == []


def test_reader_topic_angle_is_normalised_conservative_and_deterministic():
    first = build_reader_topic_angle("  성수   카페  ")
    second = build_reader_topic_angle("성수 카페")

    assert first == second == {
        "reader_question": "성수 카페에 대해 알아볼 때 먼저 확인해야 할 정보는 무엇일까?",
        "topic_angle": (
            "성수 카페에 관심 있는 독자가 배경, 확인할 정보, 주의점을 "
            "차례로 이해할 수 있도록 정리한다."
        ),
    }
    combined = " ".join(first.values())
    for unsupported_claim in ("SEO", "상위", "노출", "랭킹", "인기", "추천"):
        assert unsupported_claim not in combined


@pytest.mark.parametrize("keyword", ["", "   ", "\n\t"])
def test_reader_topic_angle_rejects_empty_keyword(keyword):
    with pytest.raises(ValueError, match="must not be empty"):
        build_reader_topic_angle(keyword)


def test_canonical_keyword_key_normalizes_nfkc_whitespace_and_case():
    assert canonical_keyword_key(" ＡI  맛집 ") == canonical_keyword_key("ai맛집")


def test_canonical_keyword_key_rejects_non_string():
    with pytest.raises(TypeError):
        canonical_keyword_key(123)
