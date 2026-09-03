"""Backwards-compatible wrappers around the strict official-API clients.

The original dashboard imports ``RealDataFetcher`` and ``fetch_keyword_data``.
They now preserve source failures as failures instead of silently turning them
into zero-demand or zero-competition observations.
"""

from __future__ import annotations

import unicodedata
from typing import Any

try:
    from seo_sources import NaverClient, SourceError
except ImportError:  # pragma: no cover - package import path
    from .seo_sources import NaverClient, SourceError


def _normalise(value: str) -> str:
    return "".join(unicodedata.normalize("NFKC", value).split()).casefold()


class RealDataFetcher:
    """Legacy interface backed by :class:`NaverClient`."""

    def __init__(self, client: NaverClient | None = None):
        self.client = client or NaverClient()

    @staticmethod
    def _validate_keyword(keyword: str) -> str:
        cleaned = str(keyword).strip()
        if not cleaned:
            raise ValueError("keyword must not be empty")
        return cleaned

    def get_search_volume_details(self, keyword: str) -> dict[str, Any]:
        keyword = self._validate_keyword(keyword)
        rows = self.client.related_keywords(keyword, min_volume=0, limit=1000)
        target = _normalise(keyword)
        for row in rows:
            if _normalise(row["keyword"]) == target:
                return row
        raise SourceError(
            "naver_search_ads",
            f"no exact volume row was returned for keyword: {keyword}",
        )

    def get_search_volume(self, keyword: str) -> int:
        return int(self.get_search_volume_details(keyword)["monthly_search_estimate"])

    def get_doc_count(self, keyword: str) -> int:
        keyword = self._validate_keyword(keyword)
        return int(self.client.blog_search(keyword, display=1, sort="sim")["total"])

    def get_related_keywords(self, seed_keyword: str) -> list[dict[str, Any]]:
        seed_keyword = self._validate_keyword(seed_keyword)
        return [
            {
                "keyword": row["keyword"],
                "volume": row["monthly_search_estimate"],
                "volume_censored": row["volume_censored"],
                "pc_raw": row["pc_raw"],
                "mobile_raw": row["mobile_raw"],
            }
            for row in self.client.related_keywords(seed_keyword, min_volume=100, limit=1000)
        ]


def fetch_keyword_data(
    keyword: str,
    fetcher: RealDataFetcher | None = None,
) -> dict[str, Any]:
    """Fetch one complete measurement without hiding source failures.

    The legacy column names remain for CLI compatibility.  ``Total_Docs`` is
    specifically the Naver Blog Search result count, not all Naver documents.
    Callers must catch :class:`SourceError` and keep failed rows out of scores.
    """

    active_fetcher = fetcher or RealDataFetcher()
    keyword = active_fetcher._validate_keyword(keyword)
    volume = active_fetcher.get_search_volume_details(keyword)
    blog_doc_count = active_fetcher.get_doc_count(keyword)
    return {
        "Keyword": keyword,
        "Monthly_Search_Volume": int(volume["monthly_search_estimate"]),
        "Search_Volume_Censored": bool(volume["volume_censored"]),
        "Search_Volume_PC_Raw": volume["pc_raw"],
        "Search_Volume_Mobile_Raw": volume["mobile_raw"],
        "Total_Docs": blog_doc_count,
        "Blog_Doc_Count": blog_doc_count,
        "SmartBlock_Type": "공식 API로 확인 불가",
    }
