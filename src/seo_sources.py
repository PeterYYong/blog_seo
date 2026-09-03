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
import math
import os
import re
import time
from dataclasses import dataclass
from datetime import date, datetime, timezone
from numbers import Real
from pathlib import Path
from typing import Any, Callable, Iterable, Mapping

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


class SourceFailureCircuitBreaker:
    """Stop a batch after terminal or repeated source-wide failures.

    Authentication and quota failures cannot recover later in the same CLI
    run. Network and server errors get one more keyword-level chance after the
    request client's own bounded retry, then stop if the same source fails
    again consecutively.
    """

    terminal_status_codes = frozenset({401, 403, 404, 405, 429})
    terminal_markers = (
        "missing credentials",
        "invalid json response",
        "unexpected json response shape",
        "missing or invalid",
    )
    network_markers = (
        "request timed out",
        "connection failed",
        "request failed",
    )

    def __init__(self, transient_failure_limit: int = 2):
        if (
            isinstance(transient_failure_limit, bool)
            or not isinstance(transient_failure_limit, int)
            or transient_failure_limit < 1
        ):
            raise ValueError("transient_failure_limit must be a positive integer")
        self.transient_failure_limit = transient_failure_limit
        self._last_source: str | None = None
        self._consecutive_transient_failures = 0

    @staticmethod
    def _is_transient_source_failure(exc: SourceError) -> bool:
        if exc.status_code is not None and exc.status_code >= 500:
            return True
        detail = str(exc).casefold()
        return exc.status_code is None and any(
            marker in detail for marker in SourceFailureCircuitBreaker.network_markers
        )

    def record_success(self) -> None:
        self._last_source = None
        self._consecutive_transient_failures = 0

    def should_abort(self, exc: SourceError) -> bool:
        detail = str(exc).casefold()
        if exc.status_code in self.terminal_status_codes or any(
            marker in detail for marker in self.terminal_markers
        ):
            self.record_success()
            return True

        if not self._is_transient_source_failure(exc):
            self.record_success()
            return False

        if exc.source == self._last_source:
            self._consecutive_transient_failures += 1
        else:
            self._last_source = exc.source
            self._consecutive_transient_failures = 1
        return self._consecutive_transient_failures >= self.transient_failure_limit


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
    if isinstance(value, bool) or value is None:
        raise ValueError("count must be a nonnegative integer or '< N'")
    if isinstance(value, str):
        censored_match = re.fullmatch(r"\s*<\s*(\d+)\s*", value)
        if censored_match:
            upper_exclusive = int(censored_match.group(1))
            if upper_exclusive < 1:
                raise ValueError("censored upper bound must be positive")
            return max(0, (upper_exclusive - 1) // 2), True, raw
        if not re.fullmatch(r"\s*\d+\s*", value):
            raise ValueError("count must be a nonnegative integer or '< N'")
    try:
        parsed = int(value)
    except (TypeError, ValueError) as exc:
        raise ValueError("count must be a nonnegative integer or '< N'") from exc
    if parsed < 0:
        raise ValueError("count must be nonnegative")
    if isinstance(value, float) and value != parsed:
        raise ValueError("count must be an integer")
    return parsed, False, raw


def _required_mapping_list(
    payload: Mapping[str, Any],
    field: str,
    source: str,
) -> list[Mapping[str, Any]]:
    """Return a required list of objects or reject an unusable 200 response."""

    value = payload.get(field)
    if not isinstance(value, list) or any(not isinstance(item, Mapping) for item in value):
        raise SourceError(source, f"missing or invalid response field: {field}")
    return value


def _required_nonnegative_int(
    payload: Mapping[str, Any],
    field: str,
    source: str,
) -> int:
    """Parse a required count without treating a malformed response as zero."""

    value = payload.get(field)
    if isinstance(value, bool):
        raise SourceError(source, f"missing or invalid response field: {field}")
    try:
        parsed = int(value)
    except (TypeError, ValueError) as exc:
        raise SourceError(source, f"missing or invalid response field: {field}") from exc
    if parsed < 0 or (isinstance(value, float) and value != parsed):
        raise SourceError(source, f"missing or invalid response field: {field}")
    return parsed


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
        timeout: float | tuple[float, float] = (3.05, 10.0),
        max_retries: int = 1,
        backoff_seconds: float = 0.4,
        sleeper: Callable[[float], None] = time.sleep,
    ):
        raw_secrets = secrets or load_secrets()
        self.secrets = {
            key: text
            for key, value in raw_secrets.items()
            if (text := _nonempty(value)) is not None
        }
        self.session = session or requests.Session()
        self.timeout = timeout
        self.max_retries = max(0, int(max_retries))
        self.backoff_seconds = max(0.0, float(backoff_seconds))
        self.sleeper = sleeper

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

    def _request_json(
        self,
        method: str,
        source: str,
        url: str,
        **kwargs: Any,
    ) -> dict[str, Any]:
        """Request one JSON document with bounded transient retries.

        Authentication and other permanent 4xx responses fail immediately.
        Timeouts, connection failures, 429 responses, and common 5xx responses
        are retried once by default. A repeated 429 then remains explicit so a
        caller can stop the batch instead of amplifying rate or quota pressure.
        """

        kwargs.setdefault("timeout", self.timeout)
        transient_statuses = {429, 500, 502, 503, 504}
        attempts = self.max_retries + 1

        for attempt in range(attempts):
            try:
                request_method = getattr(self.session, method.lower())
                response = request_method(url, **kwargs)
            except (requests.Timeout, requests.ConnectionError) as exc:
                if attempt + 1 >= attempts:
                    message = "request timed out" if isinstance(exc, requests.Timeout) else "connection failed"
                    raise SourceError(source, message) from exc
                self.sleeper(self.backoff_seconds * (2**attempt))
                continue
            except requests.RequestException as exc:
                raise SourceError(source, "request failed") from exc

            if response.status_code in transient_statuses and attempt + 1 < attempts:
                retry_after = response.headers.get("Retry-After") if getattr(response, "headers", None) else None
                try:
                    if retry_after:
                        delay = min(float(retry_after), 3.0)
                    elif response.status_code == 429 and source != "naver_search_ads":
                        # NAVER API HUB documents recovery one second after its
                        # per-key RPS falls back below the limit.
                        delay = 1.0
                    else:
                        delay = self.backoff_seconds * (2**attempt)
                except (TypeError, ValueError):
                    delay = self.backoff_seconds * (2**attempt)
                self.sleeper(max(0.0, delay))
                continue

            self._raise_for_response(source, response)
            try:
                payload = response.json()
            except (TypeError, ValueError) as exc:
                raise SourceError(source, "invalid JSON response") from exc
            if not isinstance(payload, dict):
                raise SourceError(source, "unexpected JSON response shape")
            return payload

        raise SourceError(source, "request failed after retry")

    def related_keywords(self, seed: str, min_volume: int = 10, limit: int = 100) -> list[dict[str, Any]]:
        """Return Search Ads related keywords with transparent censoring flags."""

        uri = "/keywordstool"
        payload = self._request_json(
            "GET",
            "naver_search_ads",
            f"{self.ad_base_url}{uri}",
            params={"hintKeywords": "".join(seed.split()), "showDetail": 1},
            headers=self._ad_headers("GET", uri),
        )
        keyword_items = _required_mapping_list(
            payload,
            "keywordList",
            "naver_search_ads",
        )
        rows: list[dict[str, Any]] = []
        for item in keyword_items:
            keyword = item.get("relKeyword")
            if not isinstance(keyword, str) or not keyword.strip():
                raise SourceError(
                    "naver_search_ads",
                    "missing or invalid response field: relKeyword",
                )
            try:
                pc, pc_censored, pc_raw = _parse_censored_count(
                    item.get("monthlyPcQcCnt")
                )
                mobile, mobile_censored, mobile_raw = _parse_censored_count(
                    item.get("monthlyMobileQcCnt")
                )
            except ValueError as exc:
                raise SourceError(
                    "naver_search_ads",
                    "missing or invalid response field: monthly search count",
                ) from exc
            total = pc + mobile
            if total < min_volume:
                continue
            rows.append(
                {
                    "keyword": keyword.strip(),
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
            payload_response = self._request_json(
                "POST",
                "naver_datalab",
                self._datalab_url(),
                headers={**self._search_api_headers(), "Content-Type": "application/json"},
                json=payload,
            )
            results = _required_mapping_list(payload_response, "results", "naver_datalab")
            for result in results:
                title = result.get("title")
                data = result.get("data")
                if not isinstance(title, str) or not title.strip() or not isinstance(data, list):
                    raise SourceError(
                        "naver_datalab",
                        "missing or invalid response field: title/data",
                    )
                validated_points: list[dict[str, Any]] = []
                for point in data:
                    if not isinstance(point, Mapping):
                        raise SourceError(
                            "naver_datalab",
                            "missing or invalid response field: data point",
                        )
                    period = point.get("period")
                    ratio = point.get("ratio")
                    if (
                        not isinstance(period, str)
                        or not period.strip()
                        or isinstance(ratio, bool)
                        or not isinstance(ratio, Real)
                    ):
                        raise SourceError(
                            "naver_datalab",
                            "missing or invalid response field: period/ratio",
                        )
                    try:
                        numeric_ratio = float(ratio)
                    except (TypeError, ValueError) as exc:
                        raise SourceError(
                            "naver_datalab",
                            "missing or invalid response field: ratio",
                        ) from exc
                    if (
                        not math.isfinite(numeric_ratio)
                        or numeric_ratio < 0
                        or numeric_ratio > 100
                    ):
                        raise SourceError(
                            "naver_datalab",
                            "missing or invalid response field: ratio",
                        )
                    validated_point = dict(point)
                    validated_point["ratio"] = numeric_ratio
                    validated_points.append(validated_point)
                output[title.strip()] = validated_points
        return output

    def blog_search(self, query: str, display: int = 20, sort: str = "date") -> dict[str, Any]:
        if sort not in {"date", "sim"}:
            raise ValueError("sort must be date or sim")
        payload = self._request_json(
            "GET",
            "naver_blog_search",
            self._search_api_url("blog"),
            headers=self._search_api_headers(),
            params={"query": query, "display": max(1, min(display, 100)), "sort": sort},
        )
        total = _required_nonnegative_int(payload, "total", "naver_blog_search")
        items = _required_mapping_list(payload, "items", "naver_blog_search")
        return {
            "query": query,
            "total": total,
            "items": [
                {
                    "title": _strip_html(item.get("title", "")),
                    "description": _strip_html(item.get("description", "")),
                    "blogger_name": _strip_html(item.get("bloggername", "")),
                    "link": item.get("link"),
                    "post_date": item.get("postdate"),
                }
                for item in items
            ],
            "source": "Naver Blog Search API",
            "source_url": NAVER_BLOG_API_DOCS,
            "query_url": f"https://search.naver.com/search.naver?where=blog&query={requests.utils.quote(query)}",
        }

    def news_search(self, query: str, display: int = 20, sort: str = "date") -> dict[str, Any]:
        if sort not in {"date", "sim"}:
            raise ValueError("sort must be date or sim")
        payload = self._request_json(
            "GET",
            "naver_news_search",
            self._search_api_url("news"),
            headers=self._search_api_headers(),
            params={"query": query, "display": max(1, min(display, 100)), "sort": sort},
        )
        total = _required_nonnegative_int(payload, "total", "naver_news_search")
        items = _required_mapping_list(payload, "items", "naver_news_search")
        return {
            "query": query,
            "total": total,
            "items": [
                {
                    "title": _strip_html(item.get("title", "")),
                    "description": _strip_html(item.get("description", "")),
                    "link": item.get("originallink") or item.get("link"),
                    "published_at": item.get("pubDate"),
                }
                for item in items
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
        payload = self._request_json(
            "GET",
            "naver_cafe_search",
            self._search_api_url("cafearticle"),
            headers=self._search_api_headers(),
            params={"query": query, "display": max(1, min(display, 100)), "sort": sort},
        )
        total = _required_nonnegative_int(payload, "total", "naver_cafe_search")
        items = _required_mapping_list(payload, "items", "naver_cafe_search")
        return {
            "query": query,
            "total": total,
            "items": [
                {
                    "title": _strip_html(item.get("title", "")),
                    "description": _strip_html(item.get("description", "")),
                    "cafe_name": _strip_html(item.get("cafename", "")),
                    "cafe_url": item.get("cafeurl"),
                    "link": item.get("link"),
                }
                for item in items
            ],
            "source": "Naver Cafe Article Search API",
            "source_url": NAVER_CAFE_API_DOCS,
        }

    def kin_search(self, query: str, display: int = 20, sort: str = "date") -> dict[str, Any]:
        """Search public Naver Knowledge iN questions through the official API."""

        if sort not in {"date", "sim", "point"}:
            raise ValueError("sort must be date, sim, or point")
        payload = self._request_json(
            "GET",
            "naver_kin_search",
            self._search_api_url("kin"),
            headers=self._search_api_headers(),
            params={"query": query, "display": max(1, min(display, 100)), "sort": sort},
        )
        total = _required_nonnegative_int(payload, "total", "naver_kin_search")
        items = _required_mapping_list(payload, "items", "naver_kin_search")
        return {
            "query": query,
            "total": total,
            "items": [
                {
                    "title": _strip_html(item.get("title", "")),
                    "description": _strip_html(item.get("description", "")),
                    "link": item.get("link"),
                }
                for item in items
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
        timeout: float | tuple[float, float] = (3.05, 10.0),
        max_retries: int = 1,
        backoff_seconds: float = 0.4,
        sleeper: Callable[[float], None] = time.sleep,
    ):
        source_secrets = dict(secrets or load_secrets())
        self.api_key = api_key or source_secrets.get("YOUTUBE_API_KEY")
        self.session = session or requests.Session()
        self.timeout = timeout
        self.max_retries = max(0, int(max_retries))
        self.backoff_seconds = max(0.0, float(backoff_seconds))
        self.sleeper = sleeper

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

    def _request_json(self, url: str, **kwargs: Any) -> dict[str, Any]:
        """Fetch one YouTube JSON document with bounded transient retries."""

        kwargs.setdefault("timeout", self.timeout)
        transient_statuses = {408, 429, 500, 502, 503, 504}
        attempts = self.max_retries + 1

        for attempt in range(attempts):
            try:
                response = self.session.get(url, **kwargs)
            except (requests.Timeout, requests.ConnectionError) as exc:
                if attempt + 1 >= attempts:
                    message = (
                        "request timed out"
                        if isinstance(exc, requests.Timeout)
                        else "connection failed"
                    )
                    raise SourceError("youtube_data_api", message) from exc
                self.sleeper(self.backoff_seconds * (2**attempt))
                continue
            except requests.RequestException as exc:
                raise SourceError("youtube_data_api", "request failed") from exc

            if response.status_code in transient_statuses and attempt + 1 < attempts:
                retry_after = (
                    response.headers.get("Retry-After")
                    if getattr(response, "headers", None)
                    else None
                )
                try:
                    delay = (
                        min(float(retry_after), 3.0)
                        if retry_after
                        else self.backoff_seconds * (2**attempt)
                    )
                except (TypeError, ValueError):
                    delay = self.backoff_seconds * (2**attempt)
                self.sleeper(max(0.0, delay))
                continue

            self._raise_for_response(response)
            try:
                payload = response.json()
            except (TypeError, ValueError) as exc:
                raise SourceError("youtube_data_api", "invalid JSON response") from exc
            if not isinstance(payload, dict):
                raise SourceError("youtube_data_api", "unexpected JSON response shape")
            return payload

        raise SourceError("youtube_data_api", "request failed after retry")

    def _video_details(self, video_ids: list[str]) -> list[dict[str, Any]]:
        if not video_ids:
            return []
        payload = self._request_json(
            f"{self.base_url}/videos",
            params={
                "part": "snippet,statistics,contentDetails",
                "id": ",".join(video_ids[:50]),
                "key": self.api_key,
            },
        )
        items = _required_mapping_list(payload, "items", "youtube_data_api")
        now = datetime.now(timezone.utc)
        rows: list[dict[str, Any]] = []
        for item in items:
            snippet = item.get("snippet", {})
            statistics = item.get("statistics", {})
            if not isinstance(snippet, Mapping) or not isinstance(statistics, Mapping):
                raise SourceError(
                    "youtube_data_api",
                    "missing or invalid response fields: snippet/statistics",
                )
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
        payload = self._request_json(
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
        )
        items = _required_mapping_list(payload, "items", "youtube_data_api")
        ids = [
            identifier.get("videoId")
            for item in items
            if isinstance((identifier := item.get("id")), Mapping)
        ]
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
        payload = self._request_json(
            f"{self.base_url}/videos",
            params=params,
        )
        items = _required_mapping_list(payload, "items", "youtube_data_api")
        ids = [item.get("id") for item in items if item.get("id")]
        return self._video_details(ids)
