import pytest

from src.keyword_expander import BROAD_TOPIC_MAP, expand_keyword


def test_expansion_is_normalised_ordered_and_unique():
    keywords, sub_topics = expand_keyword("  주식   투자  ")

    assert keywords[0] == "주식 투자"
    assert sub_topics == []
    assert keywords[1:6] == [
        "주식 투자 주가",
        "주식 투자 전망",
        "주식 투자 관련주",
        "주식 투자 배당금",
        "주식 투자 시세",
    ]
    assert len(keywords) == len(set(keywords))
    assert expand_keyword("주식 투자") == (keywords, sub_topics)


def test_broad_topic_returns_a_copy_of_its_ordered_subtopics():
    _, sub_topics = expand_keyword("주식")

    assert sub_topics == BROAD_TOPIC_MAP["주식"]
    assert sub_topics is not BROAD_TOPIC_MAP["주식"]


def test_unknown_topic_uses_a_stable_suffix_order():
    keywords, sub_topics = expand_keyword("새 주제")

    assert sub_topics == []
    assert keywords[:4] == ["새 주제", "새 주제 추천", "새 주제 비교", "새 주제 후기"]


@pytest.mark.parametrize("seed", ["", "   ", "\n\t"])
def test_empty_seed_is_rejected(seed):
    with pytest.raises(ValueError):
        expand_keyword(seed)


@pytest.mark.parametrize("seed", [None, 123, True])
def test_non_string_seed_is_rejected(seed):
    with pytest.raises(TypeError):
        expand_keyword(seed)
