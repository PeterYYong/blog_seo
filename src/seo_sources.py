"""Official API clients used by the evidence-first SEO workflow.

The module intentionally raises source errors instead of converting failures to
zero.  A zero can mean "no demand", while an exception means "we do not know";
mixing the two produces dangerously confident topic recommendations.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import html
import json
import os
import re
import time
from dataclasses import dataclass
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any, Iterable, Mapping

import requests


NAVER_DATALAB_DOCS = "https://api.ncloud-docs.com/docs/naver-api-hub-search-trend"
NAVER_BLOG_API_DOCS = "https://api.ncloud-docs.com/docs/naver-api-hub-search-blog"
NAVER_CAFE_API_DOCS = "https://api.ncloud-docs.com/docs/naver-api-hub-search-cafearticle"
NAVER_KIN_API_DOCS = "https://api.ncloud-docs.com/docs/naver-api-hub-search-kin"
NAVER_AD_API_DOCS = "https://naver.github.io/searchad-apidoc/#/operations/GET/~2Fkeywordstool"
NAVER_API_HUB_DOCS = "https://api.ncloud-docs.com/docs/naver-api-hub-overview"
NAVER_API_MIGRATION_GUIDE = "https://guide.ncloud-docs.com/docs/apihub-migration"
NAVER_API_MIGRATION_NOTICE = "https://developers.naver.com/notice/article/32530"
YOUTUBE_SEARCH_DOCS = "https://developers.google.com/youtube/v3/docs/search/list"
YOUTUBE_VIDEO_DOCS = "https://developers.google.com/youtube/v3/docs/videos/list"


class SourceError(RuntimeError):
    """An external source could not provide trustworthy data."""

    def __init__(self, source: str, message: str, status_code: int | None = None):
        self.source = source
        self.status_code = status_code
        super().__init__(f"{source}: {message}")


def _nonempty(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def load_secrets() -> dict[str, str]:
    """Load credentials with environment variables taking precedence.

    Streamlit secrets and the legacy ``secrets.json`` remain supported so the
    existing dashboard does not need a credential migration.
    """

    keys = (
        "NAVER_AD_API_KEY",
        "NAVER_AD_SECRET_KEY",
        "NAVER_CUSTOMER_ID",
        "NAVER_API_HUB_CLIENT_ID",
        "NAVER_API_HUB_CLIENT_SECRET",
        "NAVER_CLIENT_ID",
        "NAVER_CLIENT_SECRET",
        "YOUTUBE_API_KEY",
        "KAKAO_REST_API_KEY",
        "REDDIT_CLIENT_ID",
        "REDDIT_CLIENT_SECRET",
        "REDDIT_USER_AGENT",
        "REDDIT_API_APPROVED",
        "X_BEARER_TOKEN",
        "THREADS_ACCESS_TOKEN",
        "THREADS_KEYWORD_SEARCH_ENABLED",
        "STACKEXCHANGE_KEY",
    )
    merged: dict[str, str] = {}

    candidates = [
        Path("secrets.json"),
        Path(__file__).resolve().parent.parent / "secrets.json",
    ]
    for path in candidates:
        if not path.exists():
            continue
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
            for key in keys:
                value = _nonempty(payload.get(key))
                if value:
                    merged[key] = value
            break
        except (OSError, ValueError, TypeError):
            continue

    try:
        import streamlit as st

        for key in keys:
            value = _nonempty(st.secrets.get(key))
            if value:
                merged[key] = value
    except Exception:
        # Streamlit raises when no secrets file exists outside a Streamlit run.
        pass

    for key in keys:
        value = _nonempty(os.getenv(key))
        if value:
            merged[key] = value
    return merged


def _strip_html(value: str) -> str:
    return html.unescape(re.sub(r"<[^>]+>", "", value or "")).strip()


def _parse_censored_count(value: Any) -> tuple[int, bool, str]:
    """Return a conservative midpoint estimate and retain censoring metadata."""

    raw = str(value)
    if isinstance(value, str) and "<" in value:
        match = re.search(r"(\d+)", value)
        upper_exclusive = int(match.group(1)) if match else 10
        return max(0, (upper_exclusive - 1) // 2), True, raw
    try:
        return max(0, int(value)), False, raw
    except (TypeError, ValueError):
        return 0, True, raw


@dataclass(frozen=True)
class SourceStatus:
    source: str
    available: bool
    detail: str
    docs_url: str


class NaverClient:
    """Read-only Naver Search Ads, Search, and DataLab client."""

    ad_base_url = "https://api.searchad.naver.com"
    api_hub_base_url = "https://naverapihub.apigw.ntruss.com"
    open_api_base_url = "https://openapi.naver.com"

    def __init__(
        self,
        secrets: Mapping[str, str] | None = None,
        session: requests.Session | None = None,
        timeout: float = 15.0,
    ):
        self.secrets = dict(secrets or load_secrets())
        self.session = session or requests.Session()
        self.timeout = timeout

    @property
    def api_mode(self) -> str | None:
        """Return the configured Naver Search/Trend authentication generation.

        NAVER API HUB credentials take precedence.  Legacy Naver Developers
        credentials remain usable during Naver's published migration window,
        which ends on 2027-06-30.
        """

        hub_ready = all(
            self.secrets.get(key)
            for key in ("NAVER_API_HUB_CLIENT_ID", "NAVER_API_HUB_CLIENT_SECRET")
        )
        if hub_ready:
            return "api_hub"
        legacy_ready = all(
            self.secrets.get(key) for key in ("NAVER_CLIENT_ID", "NAVER_CLIENT_SECRET")
        )
        return "developers_legacy" if legacy_ready else None

    @property
    def search_api_available(self) -> bool:
        return self.api_mode is not None

    def status(self) -> list[SourceStatus]:
        ad_ready = all(
            self.secrets.get(key)
            for key in ("NAVER_AD_API_KEY", "NAVER_AD_SECRET_KEY", "NAVER_CUSTOMER_ID")
        )
        api_mode = self.api_mode
        if api_mode == "api_hub":
            api_detail = "NAVER API HUB relative trend and Search APIs"
        elif api_mode == "developers_legacy":
            api_detail = (
                "legacy Naver Developers Search/Trend APIs; migrate before "
                "2027-06-30"
            )
        else:
            api_detail = (
                "NAVER API HUB client ID/secret are missing; legacy Developers "
                "credentials are also accepted during the migration window"
            )
        return [
            SourceStatus(
                source="naver_search_ads",
                available=ad_ready,
                detail="monthly volume and related keywords" if ad_ready else "three Search Ads keys are missing",
                docs_url=NAVER_AD_API_DOCS,
            ),
            SourceStatus(
                source="naver_datalab_and_search",
                available=bool(api_mode),
                detail=api_detail,
                docs_url=NAVER_API_HUB_DOCS,
            ),
        ]

    def _require(self, source: str, keys: Iterable[str]) -> None:
        missing = [key for key in keys if not self.secrets.get(key)]
        if missing:
            raise SourceError(source, f"missing credentials: {', '.join(missing)}")

    def _ad_headers(self, method: str, uri: str) -> dict[str, str]:
        self._require(
            "naver_search_ads",
            ("NAVER_AD_API_KEY", "NAVER_AD_SECRET_KEY", "NAVER_CUSTOMER_ID"),
        )
        timestamp = str(round(time.time() * 1000))
        message = f"{timestamp}.{method}.{uri}"
        digest = hmac.new(
            self.secrets["NAVER_AD_SECRET_KEY"].encode("utf-8"),
            message.encode("utf-8"),
            hashlib.sha256,
        ).digest()
        return {
            "Content-Type": "application/json; charset=UTF-8",
            "X-Timestamp": timestamp,
            "X-API-KEY": self.secrets["NAVER_AD_API_KEY"],
            "X-Customer": self.secrets["NAVER_CUSTOMER_ID"],
            "X-Signature": base64.b64encode(digest).decode("utf-8"),
        }

    def _search_api_headers(self) -> dict[str, str]:
        if self.api_mode == "api_hub":
            return {
                "X-NCP-APIGW-API-KEY-ID": self.secrets["NAVER_API_HUB_CLIENT_ID"],
                "X-NCP-APIGW-API-KEY": self.secrets["NAVER_API_HUB_CLIENT_SECRET"],
            }
        if self.api_mode == "developers_legacy":
            return {
                "X-Naver-Client-Id": self.secrets["NAVER_CLIENT_ID"],
                "X-Naver-Client-Secret": self.secrets["NAVER_CLIENT_SECRET"],
            }
        raise SourceError(
            "naver_search_and_trend",
            "missing credentials: set NAVER_API_HUB_CLIENT_ID and "
            "NAVER_API_HUB_CLIENT_SECRET (or legacy NAVER_CLIENT_ID and "
            "NAVER_CLIENT_SECRET during the migration window)",
        )

    def _search_api_url(self, resource: str) -> str:
        if self.api_mode == "api_hub":
            return f"{self.api_hub_base_url}/search/v1/{resource}"
        return f"{self.open_api_base_url}/v1/search/{resource}.json"

    def _datalab_url(self) -> str:
        if self.api_mode == "api_hub":
            return f"{self.api_hub_base_url}/search-trend/v1/search"
        return f"{self.open_api_base_url}/v1/datalab/search"

    @staticmethod
    def _raise_for_response(source: str, response: requests.Response) -> None:
        if response.ok:
            return
        detail = response.text[:300].strip() or response.reason
        raise SourceError(source, detail, response.status_code)

    def related_keywords(self, seed: str, min_volume: int = 10, limit: int = 100) -> list[dict[str, Any]]:
        """Return Search Ads related keywords with transparent censoring flags."""

        uri = "/keywordstool"
        response = self.session.get(
            f"{self.ad_base_url}{uri}",
            params={"hintKeywords": seed.replace(" ", ""), "showDetail": 1},
            headers=self._ad_headers("GET", uri),
            timeout=self.timeout,
        )
        self._raise_for_response("naver_search_ads", response)
        rows: list[dict[str, Any]] = []
        for item in response.json().get("keywordList", []):
            pc, pc_censored, pc_raw = _parse_censored_count(item.get("monthlyPcQcCnt", 0))
            mobile, mobile_censored, mobile_raw = _parse_censored_count(item.get("monthlyMobileQcCnt", 0))
            total = pc + mobile
            if total < min_volume and not (pc_censored or mobile_censored):
                continue
            rows.append(
                {
                    "keyword": str(item.get("relKeyword", "")).strip(),
                    "monthly_search_estimate": total,
                    "volume_censored": pc_censored or mobile_censored,
                    "pc_raw": pc_raw,
                    "mobile_raw": mobile_raw,
                    "competition_index": item.get("compIdx"),
                    "monthly_average_clicks": item.get("monthlyAvePcClkCnt"),
                    "source": "Naver Search Ads API",
                    "source_url": NAVER_AD_API_DOCS,
                }
            )
        rows = [row for row in rows if row["keyword"]]
        rows.sort(key=lambda row: row["monthly_search_estimate"], reverse=True)
        return rows[: max(1, min(limit, 1000))]

    def datalab_trends(
        self,
        keywords: list[str],
        start_date: date,
        end_date: date,
        time_unit: str = "date",
    ) -> dict[str, list[dict[str, Any]]]:
        """Return relative Naver search trend series, batching five groups per call."""

        if time_unit not in {"date", "week", "month"}:
            raise ValueError("time_unit must be date, week, or month")
        unique = list(dict.fromkeys(keyword.strip() for keyword in keywords if keyword.strip()))
        output: dict[str, list[dict[str, Any]]] = {}
        for offset in range(0, len(unique), 5):
            batch = unique[offset : offset + 5]
            payload = {
                "startDate": start_date.isoformat(),
                "endDate": end_date.isoformat(),
                "timeUnit": time_unit,
                "keywordGroups": [
                    {"groupName": keyword, "keywords": [keyword]} for keyword in batch
                ],
            }
            response = self.session.post(
                self._datalab_url(),
                headers={**self._search_api_headers(), "Content-Type": "application/json"},
                json=payload,
                timeout=self.timeout,
            )
            self._raise_for_response("naver_datalab", response)
            for result in response.json().get("results", []):
                output[result.get("title", "")] = list(result.get("data", []))
        return output

    def blog_search(self, query: str, display: int = 20, sort: str = "date") -> dict[str, Any]:
        if sort not in {"date", "sim"}:
            raise ValueError("sort must be date or sim")
        response = self.session.get(
            self._search_api_url("blog"),
            headers=self._search_api_headers(),
            params={"query": query, "display": max(1, min(display, 100)), "sort": sort},
            timeout=self.timeout,
        )
        self._raise_for_response("naver_blog_search", response)
        payload = response.json()
        return {
            "query": query,
            "total": int(payload.get("total", 0)),
            "items": [
                {
                    "title": _strip_html(item.get("title", "")),
                    "description": _strip_html(item.get("description", "")),
                    "blogger_name": _strip_html(item.get("bloggername", "")),
                    "link": item.get("link"),
                    "post_date": item.get("postdate"),
                }
                for item in payload.get("items", [])
            ],
            "source": "Naver Blog Search API",
            "source_url": NAVER_BLOG_API_DOCS,
            "query_url": f"https://search.naver.com/search.naver?where=blog&query={requests.utils.quote(query)}",
        }

    def news_search(self, query: str, display: int = 20, sort: str = "date") -> dict[str, Any]:
        if sort not in {"date", "sim"}:
            raise ValueError("sort must be date or sim")
        response = self.session.get(
            self._search_api_url("news"),
            headers=self._search_api_headers(),
            params={"query": query, "display": max(1, min(display, 100)), "sort": sort},
            timeout=self.timeout,
        )
        self._raise_for_response("naver_news_search", response)
        payload = response.json()
        return {
            "query": query,
            "total": int(payload.get("total", 0)),
            "items": [
                {
                    "title": _strip_html(item.get("title", "")),
                    "description": _strip_html(item.get("description", "")),
                    "link": item.get("originallink") or item.get("link"),
                    "published_at": item.get("pubDate"),
                }
                for item in payload.get("items", [])
            ],
            "source": "Naver News Search API",
            "source_url": "https://api.ncloud-docs.com/docs/naver-api-hub-search-news",
        }

    def cafe_search(self, query: str, display: int = 20, sort: str = "date") -> dict[str, Any]:
        """Search public Naver Cafe articles through the official Search API.

        The API does not return a publication timestamp or engagement metrics,
        so callers must not present these results as a real-time popularity
        chart.  They are useful as Korean community vocabulary and intent
        evidence only.
        """

        if sort not in {"date", "sim"}:
            raise ValueError("sort must be date or sim")
        response = self.session.get(
            self._search_api_url("cafearticle"),
            headers=self._search_api_headers(),
            params={"query": query, "display": max(1, min(display, 100)), "sort": sort},
            timeout=self.timeout,
        )
        self._raise_for_response("naver_cafe_search", response)
        payload = response.json()
        return {
            "query": query,
            "total": int(payload.get("total", 0)),
            "items": [
                {
                    "title": _strip_html(item.get("title", "")),
                    "description": _strip_html(item.get("description", "")),
                    "cafe_name": _strip_html(item.get("cafename", "")),
                    "cafe_url": item.get("cafeurl"),
                    "link": item.get("link"),
                }
                for item in payload.get("items", [])
            ],
            "source": "Naver Cafe Article Search API",
            "source_url": NAVER_CAFE_API_DOCS,
        }

    def kin_search(self, query: str, display: int = 20, sort: str = "date") -> dict[str, Any]:
        """Search public Naver Knowledge iN questions through the official API."""

        if sort not in {"date", "sim", "point"}:
            raise ValueError("sort must be date, sim, or point")
        response = self.session.get(
            self._search_api_url("kin"),
            headers=self._search_api_headers(),
            params={"query": query, "display": max(1, min(display, 100)), "sort": sort},
            timeout=self.timeout,
        )
        self._raise_for_response("naver_kin_search", response)
        payload = response.json()
        return {
            "query": query,
            "total": int(payload.get("total", 0)),
            "items": [
                {
                    "title": _strip_html(item.get("title", "")),
                    "description": _strip_html(item.get("description", "")),
                    "link": item.get("link"),
                }
                for item in payload.get("items", [])
            ],
            "source": "Naver Knowledge iN Search API",
            "source_url": NAVER_KIN_API_DOCS,
        }


class YouTubeClient:
    """Read-only YouTube Data API client for recent video demand signals."""

    base_url = "https://www.googleapis.com/youtube/v3"

    def __init__(
        self,
        api_key: str | None = None,
        secrets: Mapping[str, str] | None = None,
        session: requests.Session | None = None,
        timeout: float = 15.0,
    ):
        source_secrets = dict(secrets or load_secrets())
        self.api_key = api_key or source_secrets.get("YOUTUBE_API_KEY")
        self.session = session or requests.Session()
        self.timeout = timeout

    def status(self) -> SourceStatus:
        return SourceStatus(
            source="youtube_data_api",
            available=bool(self.api_key),
            detail="recent video view velocity" if self.api_key else "YOUTUBE_API_KEY is missing",
            docs_url=YOUTUBE_SEARCH_DOCS,
        )

    def _require(self) -> None:
        if not self.api_key:
            raise SourceError("youtube_data_api", "missing credential: YOUTUBE_API_KEY")

    @staticmethod
    def _raise_for_response(response: requests.Response) -> None:
        if response.ok:
            return
        detail = response.text[:300].strip() or response.reason
        raise SourceError("youtube_data_api", detail, response.status_code)

    def _video_details(self, video_ids: list[str]) -> list[dict[str, Any]]:
        if not video_ids:
            return []
        response = self.session.get(
            f"{self.base_url}/videos",
            params={
                "part": "snippet,statistics,contentDetails",
                "id": ",".join(video_ids[:50]),
                "key": self.api_key,
            },
            timeout=self.timeout,
        )
        self._raise_for_response(response)
        now = datetime.now(timezone.utc)
        rows: list[dict[str, Any]] = []
        for item in response.json().get("items", []):
            snippet = item.get("snippet", {})
            statistics = item.get("statistics", {})
            published_text = snippet.get("publishedAt")
            try:
                published_at = datetime.fromisoformat(published_text.replace("Z", "+00:00"))
                age_days = max((now - published_at).total_seconds() / 86400.0, 1.0)
            except (AttributeError, TypeError, ValueError):
                age_days = 1.0
            views = int(statistics.get("viewCount", 0))
            video_id = item.get("id", "")
            rows.append(
                {
                    "video_id": video_id,
                    "title": snippet.get("title", ""),
                    "channel_title": snippet.get("channelTitle", ""),
                    "published_at": published_text,
                    "view_count": views,
                    "views_per_day": round(views / age_days, 2),
                    "like_count": int(statistics.get("likeCount", 0)),
                    "comment_count": int(statistics.get("commentCount", 0)),
                    "url": f"https://www.youtube.com/watch?v={video_id}",
                }
            )
        return rows

    def recent_videos(
        self,
        query: str,
        published_after: datetime,
        max_results: int = 10,
        region_code: str = "KR",
        relevance_language: str = "ko",
    ) -> list[dict[str, Any]]:
        """Return the most-viewed recent videos matching one candidate topic."""

        self._require()
        if published_after.tzinfo is None:
            published_after = published_after.replace(tzinfo=timezone.utc)
        response = self.session.get(
            f"{self.base_url}/search",
            params={
                "part": "snippet",
                "q": query,
                "type": "video",
                "order": "viewCount",
                "publishedAfter": published_after.astimezone(timezone.utc).isoformat().replace("+00:00", "Z"),
                "maxResults": max(1, min(max_results, 50)),
                "regionCode": region_code,
                "relevanceLanguage": relevance_language,
                "safeSearch": "moderate",
                "key": self.api_key,
            },
            timeout=self.timeout,
        )
        self._raise_for_response(response)
        ids = [item.get("id", {}).get("videoId") for item in response.json().get("items", [])]
        return self._video_details([video_id for video_id in ids if video_id])

    def trending_snapshot(
        self,
        max_results: int = 25,
        region_code: str = "KR",
        video_category_id: str | None = None,
    ) -> list[dict[str, Any]]:
        """Return YouTube's official ``mostPopular`` regional chart snapshot."""

        self._require()
        params: dict[str, Any] = {
            "part": "snippet,statistics,contentDetails",
            "chart": "mostPopular",
            "regionCode": region_code,
            "maxResults": max(1, min(max_results, 50)),
            "key": self.api_key,
        }
        if video_category_id:
            params["videoCategoryId"] = video_category_id
        response = self.session.get(
            f"{self.base_url}/videos",
            params=params,
            timeout=self.timeout,
        )
        self._raise_for_response(response)
        ids = [item.get("id") for item in response.json().get("items", []) if item.get("id")]
        return self._video_details(ids)
