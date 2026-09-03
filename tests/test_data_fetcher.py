import pytest

from src.data_fetcher import RealDataFetcher, fetch_keyword_data
from src.seo_sources import SourceError


class FakeNaverClient:
    def __init__(self, rows=None, blog_total=123):
        self.rows = rows or []
        self.blog_total = blog_total
        self.related_calls = []
        self.blog_calls = []

    def related_keywords(self, seed, min_volume=10, limit=100):
        self.related_calls.append((seed, min_volume, limit))
        return self.rows

    def blog_search(self, query, display=20, sort="date"):
        self.blog_calls.append((query, display, sort))
        return {"total": self.blog_total, "items": []}


def volume_row(keyword="광주맛집", volume=1200, censored=False):
    return {
        "keyword": keyword,
        "monthly_search_estimate": volume,
        "volume_censored": censored,
        "pc_raw": "400",
        "mobile_raw": "800",
    }


def test_exact_keyword_match_does_not_use_first_unrelated_row():
    client = FakeNaverClient(
        rows=[volume_row("광주여행", 9000), volume_row("광주맛집", 1200)]
    )
    fetcher = RealDataFetcher(client=client)

    assert fetcher.get_search_volume("광주 맛집") == 1200


def test_missing_exact_keyword_is_unknown_not_zero_or_first_row():
    client = FakeNaverClient(rows=[volume_row("광주여행", 9000)])
    fetcher = RealDataFetcher(client=client)

    with pytest.raises(SourceError, match="no exact volume row"):
        fetcher.get_search_volume("광주 맛집")


def test_fetch_keyword_data_reuses_client_and_retains_censoring_metadata():
    client = FakeNaverClient(rows=[volume_row(volume=8, censored=True)], blog_total=456)
    fetcher = RealDataFetcher(client=client)

    result = fetch_keyword_data("광주 맛집", fetcher=fetcher)

    assert result["Monthly_Search_Volume"] == 8
    assert result["Search_Volume_Censored"] is True
    assert result["Search_Volume_PC_Raw"] == "400"
    assert result["Search_Volume_Mobile_Raw"] == "800"
    assert result["Blog_Doc_Count"] == 456
    assert result["Total_Docs"] == 456
    assert len(client.related_calls) == 1
    assert len(client.blog_calls) == 1


def test_empty_keyword_is_rejected_before_any_api_call():
    client = FakeNaverClient(rows=[volume_row()])
    fetcher = RealDataFetcher(client=client)

    with pytest.raises(ValueError, match="must not be empty"):
        fetcher.get_doc_count("   ")

    assert client.blog_calls == []
