"""Backwards-compatible wrappers around the strict official-API clients.

The original dashboard imports ``RealDataFetcher`` and ``fetch_keyword_data``.
They now preserve source failures as failures instead of silently turning them
into zero-demand or zero-competition observations.
"""

from __future__ import annotations

from typing import Any

try:
    from seo_sources import NaverClient, SourceError
except ImportError:  # pragma: no cover - package import path
    from .seo_sources import NaverClient, SourceError


def _normalise(value: str) -> str:
    return "".join(value.split()).lower()


class RealDataFetcher:
    """Legacy interface backed by :class:`NaverClient`."""

    def __init__(self, client: NaverClient | None = None):
        self.client = client or NaverClient()

    def get_search_volume(self, keyword: str) -> int:
        rows = self.client.related_keywords(keyword, min_volume=0, limit=1000)
        target = _normalise(keyword)
        for row in rows:
            if _normalise(row["keyword"]) == target:
                return int(row["monthly_search_estimate"])
        raise SourceError(
            "naver_search_ads",
            f"no exact volume row was returned for keyword: {keyword}",
        )

    def get_doc_count(self, keyword: str) -> int:
        return int(self.client.blog_search(keyword, display=1, sort="sim")["total"])

    def get_related_keywords(self, seed_keyword: str) -> list[dict[str, Any]]:
        return [
            {"keyword": row["keyword"], "volume": row["monthly_search_estimate"]}
            for row in self.client.related_keywords(seed_keyword, min_volume=100, limit=1000)
        ]


def fetch_keyword_data(keyword: str) -> dict[str, Any] | None:
    """Return legacy column names, or ``None`` when evidence is unavailable."""

    try:
        fetcher = RealDataFetcher()
        return {
            "Keyword": keyword,
            "Monthly_Search_Volume": fetcher.get_search_volume(keyword),
            "Total_Docs": fetcher.get_doc_count(keyword),
            "SmartBlock_Type": "Not available through an official API",
        }
    except SourceError as exc:
        print(f"Data source unavailable for '{keyword}': {exc}")
        return None
