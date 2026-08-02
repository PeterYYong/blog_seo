"""Read-only community and social signals for blog-topic discovery.

The adapters in this module use documented APIs only.  They intentionally do
not scrape logged-in pages, and they do not persist post bodies or author
identities.  Community content is an idea/question signal, never a source for
verifying factual claims in a blog draft.
"""

from __future__ import annotations

import hashlib
import html
import re
import statistics
import time
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Any, Mapping

import requests

from .seo_sources import (
    NAVER_CAFE_API_DOCS,
    NAVER_KIN_API_DOCS,
    NaverClient,
    SourceError,
    SourceStatus,
    load_secrets,
)


KAKAO_CAFE_DOCS = "https://developers.kakao.com/docs/ko/daum-search/dev-guide#search-cafe"
KAKAO_QUOTA_DOCS = "https://developers.kakao.com/docs/ko/getting-started/quota"
REDDIT_POLICY_DOCS = (
    "https://support.reddithelp.com/hc/en-us/articles/42728983564564-Responsible-Builder-Policy"
)
REDDIT_API_DOCS = "https://www.reddit.com/dev/api/oauth/"
X_SEARCH_DOCS = "https://docs.x.com/x-api/posts/search/integrate/overview"
X_PRICING_DOCS = "https://docs.x.com/x-api/getting-started/pricing"
THREADS_SEARCH_DOCS = "https://developers.facebook.com/documentation/threads/keyword-search"
BLUESKY_SEARCH_DOCS = "https://docs.bsky.app/docs/api/app-bsky-feed-search-posts"
HACKER_NEWS_API_DOCS = "https://github.com/HackerNews/API"
STACKEXCHANGE_SEARCH_DOCS = "https://api.stackexchange.com/docs/advanced-search"

SUPPORTED_PLATFORMS = (
    "naver_cafe",
    "naver_kin",
    "daum_cafe",
    "bluesky",
    "reddit",
    "x",
    "threads",
    "hacker_news",
    "stackexchange",
)
DEFAULT_AUTO_PLATFORMS = (
    "naver_cafe",
    "naver_kin",
    "daum_cafe",
    "bluesky",
    "reddit",
    "x",
    "threads",
)

_CACHE_TTL_SECONDS = 60.0
_SEARCH_CACHE: dict[tuple[Any, ...], tuple[float, "CommunityBatch"]] = {}


@dataclass
class CommunityBatch:
    items: list[dict[str, Any]]
    metadata: dict[str, Any] = field(default_factory=dict)
    caveats: list[str] = field(default_factory=list)


def _truthy(value: Any) -> bool:
    return str(value or "").strip().lower() in {"1", "true", "yes", "y", "on"}


def _clean_text(value: Any) -> str:
    text = re.sub(r"<[^>]+>", " ", str(value or ""))
    return " ".join(html.unescape(text).split())


def _excerpt(value: Any, limit: int = 500) -> str:
    text = _clean_text(value)
    return text if len(text) <= limit else f"{text[: limit - 1].rstrip()}…"


def _safe_int(value: Any) -> int:
    try:
        return max(0, int(value or 0))
    except (TypeError, ValueError):
        return 0


def _parse_datetime(value: Any) -> datetime | None:
    if value is None or value == "":
        return None
    if isinstance(value, (int, float)):
        try:
            return datetime.fromtimestamp(float(value), tz=timezone.utc)
        except (OSError, OverflowError, ValueError):
            return None
    try:
        text = str(value).strip().replace("Z", "+00:00")
        parsed = datetime.fromisoformat(text)
        return parsed.replace(tzinfo=timezone.utc) if parsed.tzinfo is None else parsed
    except (TypeError, ValueError):
        return None


def _iso(value: datetime | None) -> str | None:
    return value.astimezone(timezone.utc).isoformat().replace("+00:00", "Z") if value else None


def _anonymous_author_key(platform: str, author: Any) -> str | None:
    text = str(author or "").strip()
    if not text:
        return None
    return hashlib.sha256(f"{platform}:{text}".encode("utf-8")).hexdigest()[:12]


def _text_cluster(text: str) -> str:
    normalised = re.sub(r"https?://\S+", " ", text.lower())
    normalised = re.sub(r"[^0-9a-z가-힣]+", "", normalised)
    if not normalised:
        return hashlib.sha256(text.encode("utf-8")).hexdigest()[:12]
    return hashlib.sha256(normalised.encode("utf-8")).hexdigest()[:12]


def _looks_like_question(text: str) -> bool:
    lowered = text.lower()
    patterns = (
        "?",
        "어디",
        "어떻게",
        "왜 ",
        "추천",
        "방법",
        "할까요",
        "인가요",
        "있나요",
        "되나요",
        "what ",
        "how ",
        "why ",
        "which ",
        "anyone ",
        "should ",
    )
    return any(pattern in lowered for pattern in patterns)


def _item(
    *,
    platform: str,
    item_id: Any,
    title: Any,
    text: Any,
    url: Any,
    published_at: Any = None,
    author: Any = None,
    community: Any = None,
    engagement_value: int | None = None,
    engagement_unit: str | None = None,
    engagement_metrics: Mapping[str, Any] | None = None,
    force_question: bool = False,
) -> dict[str, Any]:
    clean_title = _excerpt(title, 220)
    clean_text = _excerpt(text, 500)
    combined = " ".join(part for part in (clean_title, clean_text) if part).strip()
    published = _parse_datetime(published_at)
    stable_id = str(item_id or url or _text_cluster(combined))
    opaque_item_id = hashlib.sha256(f"{platform}:{stable_id}".encode("utf-8")).hexdigest()[:16]
    return {
        "platform": platform,
        "item_id": opaque_item_id,
        "title": clean_title or None,
        "text_excerpt": clean_text or clean_title or None,
        "community": _excerpt(community, 100) or None,
        "published_at": _iso(published),
        "engagement": {
            "value": engagement_value,
            "unit": engagement_unit,
            "metrics": {key: _safe_int(value) for key, value in (engagement_metrics or {}).items()},
        },
        "url": str(url or "").strip() or None,
        "author_key": _anonymous_author_key(platform, author),
        "is_question": force_question or _looks_like_question(combined),
        "text_cluster": _text_cluster(combined),
    }


def _raise_response(source: str, response: requests.Response) -> None:
    if response.ok:
        return
    detail = response.text[:300].strip() or response.reason
    raise SourceError(source, detail, response.status_code)


class NaverCafeAdapter:
    def __init__(self, naver: NaverClient | None = None):
        self.naver = naver or NaverClient()

    def status(self) -> SourceStatus:
        ready = self.naver.search_api_available
        return SourceStatus(
            "naver_cafe",
            ready,
            "public Cafe article search; timestamps/engagement are not returned"
            if ready
            else "NAVER API HUB or legacy Naver Developers credentials are missing",
            NAVER_CAFE_API_DOCS,
        )

    def search(self, query: str, limit: int, **_: Any) -> CommunityBatch:
        payload = self.naver.cafe_search(query, display=limit, sort="date")
        items = [
            _item(
                platform="naver_cafe",
                item_id=row.get("link"),
                title=row.get("title"),
                text=row.get("description"),
                url=row.get("link"),
                community=row.get("cafe_name"),
            )
            for row in payload.get("items", [])
        ]
        return CommunityBatch(
            items,
            {"reported_total_results": payload.get("total"), "timestamp_filter_applied": False},
            ["The official Naver Cafe Search API does not return post timestamps or engagement metrics."],
        )


class NaverKinAdapter:
    def __init__(self, naver: NaverClient | None = None):
        self.naver = naver or NaverClient()

    def status(self) -> SourceStatus:
        ready = self.naver.search_api_available
        return SourceStatus(
            "naver_kin",
            ready,
            "public question-intent search; timestamps/engagement are not returned"
            if ready
            else "NAVER API HUB or legacy Naver Developers credentials are missing",
            NAVER_KIN_API_DOCS,
        )

    def search(self, query: str, limit: int, **_: Any) -> CommunityBatch:
        payload = self.naver.kin_search(query, display=limit, sort="date")
        items = [
            _item(
                platform="naver_kin",
                item_id=row.get("link"),
                title=row.get("title"),
                text=row.get("description"),
                url=row.get("link"),
                force_question=True,
            )
            for row in payload.get("items", [])
        ]
        return CommunityBatch(
            items,
            {"reported_total_results": payload.get("total"), "timestamp_filter_applied": False},
            ["The official Knowledge iN Search API does not return publication timestamps or engagement metrics."],
        )


class DaumCafeAdapter:
    base_url = "https://dapi.kakao.com/v2/search/cafe"

    def __init__(
        self,
        secrets: Mapping[str, str] | None = None,
        session: requests.Session | None = None,
        timeout: float = 15.0,
    ):
        self.secrets = dict(secrets or load_secrets())
        self.session = session or requests.Session()
        self.timeout = timeout

    def status(self) -> SourceStatus:
        ready = bool(self.secrets.get("KAKAO_REST_API_KEY"))
        return SourceStatus(
            "daum_cafe",
            ready,
            "public Daum Cafe search with timestamps" if ready else "KAKAO_REST_API_KEY is missing",
            KAKAO_CAFE_DOCS,
        )

    def search(self, query: str, days: int, limit: int, **_: Any) -> CommunityBatch:
        key = self.secrets.get("KAKAO_REST_API_KEY")
        if not key:
            raise SourceError("daum_cafe", "missing credential: KAKAO_REST_API_KEY")
        response = self.session.get(
            self.base_url,
            headers={"Authorization": f"KakaoAK {key}"},
            params={"query": query, "sort": "recency", "page": 1, "size": min(limit, 50)},
            timeout=self.timeout,
        )
        _raise_response("daum_cafe", response)
        payload = response.json()
        cutoff = datetime.now(timezone.utc) - timedelta(days=days)
        items: list[dict[str, Any]] = []
        for row in payload.get("documents", []):
            published = _parse_datetime(row.get("datetime"))
            if published and published < cutoff:
                continue
            items.append(_item(
                platform="daum_cafe",
                item_id=row.get("url"),
                title=row.get("title"),
                text=row.get("contents"),
                url=row.get("url"),
                published_at=published,
                community=row.get("cafename"),
            ))
        meta = payload.get("meta", {})
        return CommunityBatch(
            items,
            {
                "reported_total_count": meta.get("total_count"),
                "pageable_count": meta.get("pageable_count"),
                "is_end": meta.get("is_end"),
                "timestamp_filter_applied": True,
                "server_side_timestamp_filter": False,
            },
            [
                "The API has no server-side date-window parameter; the first recency-sorted page is filtered locally, so recall is limited."
            ],
        )


class BlueskyAdapter:
    base_url = "https://public.api.bsky.app/xrpc/app.bsky.feed.searchPosts"

    def __init__(self, session: requests.Session | None = None, timeout: float = 15.0):
        self.session = session or requests.Session()
        self.timeout = timeout

    def status(self) -> SourceStatus:
        return SourceStatus(
            "bluesky",
            True,
            "public AppView search; no key required on the public service",
            BLUESKY_SEARCH_DOCS,
        )

    def search(self, query: str, days: int, limit: int, language: str | None = None, **_: Any) -> CommunityBatch:
        since = datetime.now(timezone.utc) - timedelta(days=days)
        params: dict[str, Any] = {
            "q": query,
            "sort": "latest",
            "since": _iso(since),
            "limit": min(limit, 100),
        }
        if language:
            params["lang"] = language
        response = self.session.get(self.base_url, params=params, timeout=self.timeout)
        _raise_response("bluesky", response)
        payload = response.json()
        items: list[dict[str, Any]] = []
        for post in payload.get("posts", []):
            record = post.get("record", {}) if isinstance(post.get("record"), dict) else {}
            author = post.get("author", {}) if isinstance(post.get("author"), dict) else {}
            uri = str(post.get("uri", ""))
            rkey = uri.rsplit("/", 1)[-1] if uri else ""
            handle = author.get("handle")
            url = f"https://bsky.app/profile/{handle}/post/{rkey}" if handle and rkey else None
            metrics = {
                "likes": post.get("likeCount"),
                "replies": post.get("replyCount"),
                "reposts": post.get("repostCount"),
                "quotes": post.get("quoteCount"),
            }
            items.append(
                _item(
                    platform="bluesky",
                    item_id=uri or post.get("cid"),
                    title=None,
                    text=record.get("text"),
                    url=url,
                    published_at=record.get("createdAt") or post.get("indexedAt"),
                    author=author.get("did") or handle,
                    engagement_value=sum(_safe_int(value) for value in metrics.values()),
                    engagement_unit="public interactions",
                    engagement_metrics=metrics,
                )
            )
        return CommunityBatch(
            items,
            {
                "hits_total": payload.get("hitsTotal"),
                "timestamp_filter_applied": True,
                "sort": "latest",
            },
        )


class RedditAdapter:
    oauth_base = "https://oauth.reddit.com"
    token_url = "https://www.reddit.com/api/v1/access_token"

    def __init__(
        self,
        secrets: Mapping[str, str] | None = None,
        session: requests.Session | None = None,
        timeout: float = 15.0,
    ):
        self.secrets = dict(secrets or load_secrets())
        self.session = session or requests.Session()
        self.timeout = timeout
        self._token: str | None = None
        self._token_expires_at = 0.0

    def status(self) -> SourceStatus:
        approved = _truthy(self.secrets.get("REDDIT_API_APPROVED"))
        credentials = all(
            self.secrets.get(key)
            for key in ("REDDIT_CLIENT_ID", "REDDIT_CLIENT_SECRET", "REDDIT_USER_AGENT")
        )
        available = approved and credentials
        if not approved:
            detail = "disabled until Reddit API access is explicitly approved"
        elif not credentials:
            detail = "Reddit client ID/secret/descriptive User-Agent are missing"
        else:
            detail = "approved OAuth read-only search"
        return SourceStatus("reddit", available, detail, REDDIT_POLICY_DOCS)

    def _access_token(self) -> str:
        status = self.status()
        if not status.available:
            raise SourceError("reddit", status.detail)
        if self._token and time.monotonic() < self._token_expires_at:
            return self._token
        response = self.session.post(
            self.token_url,
            auth=(self.secrets["REDDIT_CLIENT_ID"], self.secrets["REDDIT_CLIENT_SECRET"]),
            headers={"User-Agent": self.secrets["REDDIT_USER_AGENT"]},
            data={"grant_type": "client_credentials"},
            timeout=self.timeout,
        )
        _raise_response("reddit", response)
        payload = response.json()
        token = str(payload.get("access_token", "")).strip()
        if not token:
            raise SourceError("reddit", "OAuth response did not contain an access token")
        self._token = token
        self._token_expires_at = time.monotonic() + max(30, _safe_int(payload.get("expires_in")) - 60)
        return token

    @staticmethod
    def _time_filter(days: int) -> str:
        if days <= 1:
            return "day"
        if days <= 7:
            return "week"
        if days <= 31:
            return "month"
        if days <= 365:
            return "year"
        return "all"

    def search(
        self,
        query: str,
        days: int,
        limit: int,
        subreddits: list[str] | None = None,
        **_: Any,
    ) -> CommunityBatch:
        token = self._access_token()
        headers = {
            "Authorization": f"Bearer {token}",
            "User-Agent": self.secrets["REDDIT_USER_AGENT"],
        }
        clean_subreddits = [
            subreddit
            for subreddit in (subreddits or [])
            if re.fullmatch(r"[A-Za-z0-9_]{2,21}", subreddit or "")
        ][:10]
        targets = clean_subreddits or [None]
        per_target = max(1, min(100, (limit + len(targets) - 1) // len(targets)))
        rows: list[dict[str, Any]] = []
        cutoff = datetime.now(timezone.utc) - timedelta(days=days)
        for subreddit in targets:
            endpoint = f"/r/{subreddit}/search" if subreddit else "/search"
            response = self.session.get(
                f"{self.oauth_base}{endpoint}",
                headers=headers,
                params={
                    "q": query,
                    "sort": "new",
                    "t": self._time_filter(days),
                    "limit": per_target,
                    "restrict_sr": "true" if subreddit else "false",
                    "type": "link",
                    "raw_json": 1,
                },
                timeout=self.timeout,
            )
            _raise_response("reddit", response)
            for child in response.json().get("data", {}).get("children", []):
                row = child.get("data", {})
                if row.get("over_18") or row.get("removed_by_category"):
                    continue
                published = _parse_datetime(row.get("created_utc"))
                if published and published < cutoff:
                    continue
                permalink = row.get("permalink")
                url = f"https://www.reddit.com{permalink}" if permalink else None
                metrics = {"score": row.get("score"), "comments": row.get("num_comments")}
                body = row.get("selftext")
                if body in {"[removed]", "[deleted]"}:
                    body = ""
                rows.append(
                    _item(
                        platform="reddit",
                        item_id=row.get("name") or row.get("id"),
                        title=row.get("title"),
                        text=body,
                        url=url,
                        published_at=published,
                        author=row.get("author_fullname") or row.get("author"),
                        community=row.get("subreddit_name_prefixed") or row.get("subreddit"),
                        engagement_value=sum(_safe_int(value) for value in metrics.values()),
                        engagement_unit="score plus comments",
                        engagement_metrics=metrics,
                    )
                )
        return CommunityBatch(
            _deduplicate_items(rows)[:limit],
            {"timestamp_filter_applied": True, "subreddits": clean_subreddits},
            [
                "Reddit access is gated by explicit API approval and OAuth credentials.",
                "Deleted/removed and NSFW posts are excluded; returned excerpts are not persisted by this service.",
            ],
        )


class XAdapter:
    base_url = "https://api.x.com/2/tweets/search/recent"

    def __init__(
        self,
        secrets: Mapping[str, str] | None = None,
        session: requests.Session | None = None,
        timeout: float = 15.0,
    ):
        self.secrets = dict(secrets or load_secrets())
        self.session = session or requests.Session()
        self.timeout = timeout

    def status(self) -> SourceStatus:
        ready = bool(self.secrets.get("X_BEARER_TOKEN"))
        return SourceStatus(
            "x",
            ready,
            "pay-per-use recent public-post search" if ready else "X_BEARER_TOKEN is missing",
            X_SEARCH_DOCS,
        )

    def search(self, query: str, days: int, limit: int, language: str | None = None, **_: Any) -> CommunityBatch:
        token = self.secrets.get("X_BEARER_TOKEN")
        if not token:
            raise SourceError("x", "missing credential: X_BEARER_TOKEN")
        query_parts = [f"({query})", "-is:retweet"]
        if language:
            if not re.fullmatch(r"[A-Za-z]{2,3}", language):
                raise ValueError("language must be a two- or three-letter language code")
            query_parts.append(f"lang:{language.lower()}")
        final_query = " ".join(query_parts)
        if len(final_query) > 512:
            raise ValueError("X recent-search query exceeds the 512-character self-serve limit")
        effective_days = min(days, 7)
        response = self.session.get(
            self.base_url,
            headers={"Authorization": f"Bearer {token}"},
            params={
                "query": final_query,
                "max_results": max(10, min(limit, 100)),
                "start_time": _iso(datetime.now(timezone.utc) - timedelta(days=effective_days)),
                "tweet.fields": "created_at,lang,public_metrics,author_id,conversation_id",
            },
            timeout=self.timeout,
        )
        _raise_response("x", response)
        payload = response.json()
        items: list[dict[str, Any]] = []
        for row in payload.get("data", []):
            public = row.get("public_metrics", {})
            metrics = {
                "likes": public.get("like_count"),
                "replies": public.get("reply_count"),
                "reposts": public.get("retweet_count"),
                "quotes": public.get("quote_count"),
                "bookmarks": public.get("bookmark_count"),
                "impressions": public.get("impression_count"),
            }
            interactions = sum(_safe_int(metrics[key]) for key in ("likes", "replies", "reposts", "quotes", "bookmarks"))
            post_id = row.get("id")
            items.append(
                _item(
                    platform="x",
                    item_id=post_id,
                    title=None,
                    text=row.get("text"),
                    url=f"https://x.com/i/web/status/{post_id}" if post_id else None,
                    published_at=row.get("created_at"),
                    author=row.get("author_id"),
                    engagement_value=interactions,
                    engagement_unit="public interactions excluding impressions",
                    engagement_metrics=metrics,
                )
            )
        caveats = ["X API access is pay-per-use; verify live endpoint pricing in the developer console."]
        if days > 7:
            caveats.append("X recent search covers at most the last seven days; the requested window was clipped.")
        return CommunityBatch(
            items[:limit],
            {**payload.get("meta", {}), "timestamp_filter_applied": True, "effective_days": effective_days},
            caveats,
        )


class ThreadsAdapter:
    base_url = "https://graph.threads.net/v1.0/keyword_search"

    def __init__(
        self,
        secrets: Mapping[str, str] | None = None,
        session: requests.Session | None = None,
        timeout: float = 15.0,
    ):
        self.secrets = dict(secrets or load_secrets())
        self.session = session or requests.Session()
        self.timeout = timeout

    def status(self) -> SourceStatus:
        enabled = _truthy(self.secrets.get("THREADS_KEYWORD_SEARCH_ENABLED"))
        token = bool(self.secrets.get("THREADS_ACCESS_TOKEN"))
        available = enabled and token
        if not enabled:
            detail = "disabled until threads_keyword_search access is explicitly enabled"
        elif not token:
            detail = "THREADS_ACCESS_TOKEN is missing"
        else:
            detail = "official public keyword search with threads_keyword_search permission"
        return SourceStatus("threads", available, detail, THREADS_SEARCH_DOCS)

    def search(self, query: str, days: int, limit: int, **_: Any) -> CommunityBatch:
        status = self.status()
        if not status.available:
            raise SourceError("threads", status.detail)
        response = self.session.get(
            self.base_url,
            headers={"Authorization": f"Bearer {self.secrets['THREADS_ACCESS_TOKEN']}"},
            params={
                "q": query,
                "search_type": "RECENT",
                "limit": min(limit, 100),
                "fields": "id,text,media_type,permalink,timestamp,username,is_quote_post,is_reply",
            },
            timeout=self.timeout,
        )
        _raise_response("threads", response)
        payload = response.json()
        cutoff = datetime.now(timezone.utc) - timedelta(days=days)
        items: list[dict[str, Any]] = []
        for row in payload.get("data", []):
            published = _parse_datetime(row.get("timestamp"))
            if published and published < cutoff:
                continue
            items.append(
                _item(
                    platform="threads",
                    item_id=row.get("id"),
                    title=None,
                    text=row.get("text"),
                    url=row.get("permalink"),
                    published_at=published,
                    author=row.get("username"),
                    engagement_value=None,
                    engagement_unit=None,
                    engagement_metrics={},
                )
            )
        return CommunityBatch(
            items,
            {"timestamp_filter_applied": True, "search_type": "RECENT"},
            [
                "Public engagement totals are not supplied by keyword search and are not inferred.",
                "The access token must include approved threads_keyword_search permission.",
            ],
        )


class HackerNewsAdapter:
    base_url = "https://hacker-news.firebaseio.com/v0"
    allowed_feeds = {"newstories", "topstories", "beststories", "askstories", "showstories"}

    def __init__(self, session: requests.Session | None = None, timeout: float = 15.0):
        self.session = session or requests.Session()
        self.timeout = timeout

    def status(self) -> SourceStatus:
        return SourceStatus(
            "hacker_news",
            True,
            "public near-real-time Firebase feed; keyword filtering is local and low-recall",
            HACKER_NEWS_API_DOCS,
        )

    def search(
        self,
        query: str,
        days: int,
        limit: int,
        hacker_news_feeds: list[str] | None = None,
        **_: Any,
    ) -> CommunityBatch:
        feeds = [feed for feed in (hacker_news_feeds or ["newstories", "askstories"]) if feed in self.allowed_feeds]
        feeds = list(dict.fromkeys(feeds)) or ["newstories", "askstories"]
        scan_limit = max(20, min(40, limit * 3))
        ids: list[int] = []
        per_feed = max(1, scan_limit // len(feeds))
        for feed in feeds:
            response = self.session.get(f"{self.base_url}/{feed}.json", timeout=self.timeout)
            _raise_response("hacker_news", response)
            ids.extend(response.json()[:per_feed])
        ids = list(dict.fromkeys(ids))[:scan_limit]
        query_tokens = [token.lower() for token in re.findall(r"[0-9A-Za-z가-힣+#.-]{2,}", query)]
        cutoff = datetime.now(timezone.utc) - timedelta(days=days)
        rows: list[dict[str, Any]] = []
        for item_id in ids:
            response = self.session.get(f"{self.base_url}/item/{item_id}.json", timeout=self.timeout)
            _raise_response("hacker_news", response)
            row = response.json() or {}
            if row.get("dead") or row.get("deleted") or row.get("type") != "story":
                continue
            combined = _clean_text(f"{row.get('title', '')} {row.get('text', '')}").lower()
            published = _parse_datetime(row.get("time"))
            if query_tokens and not any(token in combined for token in query_tokens):
                continue
            if published and published < cutoff:
                continue
            metrics = {"points": row.get("score"), "comments": row.get("descendants")}
            rows.append(
                _item(
                    platform="hacker_news",
                    item_id=item_id,
                    title=row.get("title"),
                    text=row.get("text"),
                    url=f"https://news.ycombinator.com/item?id={item_id}",
                    published_at=published,
                    author=row.get("by"),
                    community="Hacker News",
                    engagement_value=sum(_safe_int(value) for value in metrics.values()),
                    engagement_unit="points plus comments",
                    engagement_metrics=metrics,
                    force_question=str(row.get("title", "")).lower().startswith("ask hn:"),
                )
            )
        rows.sort(key=_item_sort_key, reverse=True)
        return CommunityBatch(
            rows[:limit],
            {"feeds": feeds, "items_scanned": len(ids), "timestamp_filter_applied": True},
            [
                "The official Hacker News API has no search endpoint; only a small recent-feed sample is keyword-filtered locally.",
                "Use Hacker News only for technology, startup, and AI niches.",
            ],
        )


class StackExchangeAdapter:
    base_url = "https://api.stackexchange.com/2.3/search/advanced"

    def __init__(
        self,
        secrets: Mapping[str, str] | None = None,
        session: requests.Session | None = None,
        timeout: float = 15.0,
    ):
        self.secrets = dict(secrets or load_secrets())
        self.session = session or requests.Session()
        self.timeout = timeout

    def status(self) -> SourceStatus:
        return SourceStatus(
            "stackexchange",
            True,
            "anonymous public question search; optional key increases quota",
            STACKEXCHANGE_SEARCH_DOCS,
        )

    def search(
        self,
        query: str,
        days: int,
        limit: int,
        stackexchange_site: str = "stackoverflow",
        **_: Any,
    ) -> CommunityBatch:
        if not re.fullmatch(r"[A-Za-z0-9.-]{2,80}", stackexchange_site or ""):
            raise ValueError("stackexchange_site contains unsupported characters")
        params: dict[str, Any] = {
            "site": stackexchange_site,
            "q": query,
            "fromdate": int((datetime.now(timezone.utc) - timedelta(days=days)).timestamp()),
            "pagesize": min(limit, 100),
            "page": 1,
            "sort": "activity",
            "order": "desc",
        }
        if self.secrets.get("STACKEXCHANGE_KEY"):
            params["key"] = self.secrets["STACKEXCHANGE_KEY"]
        response = self.session.get(self.base_url, params=params, timeout=self.timeout)
        _raise_response("stackexchange", response)
        payload = response.json()
        if payload.get("error_message"):
            raise SourceError("stackexchange", str(payload["error_message"]), payload.get("error_id"))
        items: list[dict[str, Any]] = []
        for row in payload.get("items", []):
            owner = row.get("owner", {}) if isinstance(row.get("owner"), dict) else {}
            metrics = {
                "score": row.get("score"),
                "answers": row.get("answer_count"),
                "views": row.get("view_count"),
            }
            items.append(
                _item(
                    platform="stackexchange",
                    item_id=row.get("question_id"),
                    title=row.get("title"),
                    text=None,
                    url=row.get("link"),
                    published_at=row.get("creation_date"),
                    author=owner.get("user_id") or owner.get("display_name"),
                    community=stackexchange_site,
                    engagement_value=_safe_int(row.get("score")) + _safe_int(row.get("answer_count")),
                    engagement_unit="score plus answers",
                    engagement_metrics=metrics,
                    force_question=True,
                )
            )
        caveats = ["Stack Exchange is useful for technical/how-to niches, not general consumer popularity."]
        if payload.get("backoff"):
            caveats.append(f"The API requested a {payload['backoff']}-second backoff before another identical call.")
        return CommunityBatch(
            items,
            {
                "site": stackexchange_site,
                "quota_remaining": payload.get("quota_remaining"),
                "has_more": payload.get("has_more"),
                "timestamp_filter_applied": True,
            },
            caveats,
        )


def _deduplicate_items(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    seen: set[tuple[str, str]] = set()
    output: list[dict[str, Any]] = []
    for item in items:
        identifier = str(item.get("item_id") or item.get("url") or item.get("text_cluster"))
        key = (str(item.get("platform")), identifier)
        if key not in seen:
            seen.add(key)
            output.append(item)
    return output


def _item_sort_key(item: dict[str, Any]) -> tuple[int, float]:
    engagement = item.get("engagement", {}).get("value")
    published = _parse_datetime(item.get("published_at"))
    return (_safe_int(engagement), published.timestamp() if published else 0.0)


_STOPWORDS = {
    "그리고",
    "하지만",
    "그래서",
    "있는",
    "없는",
    "어떤",
    "이것",
    "저것",
    "정말",
    "관련",
    "대한",
    "에서",
    "으로",
    "입니다",
    "있나요",
    "추천",
    "후기",
    "the",
    "and",
    "for",
    "with",
    "that",
    "this",
    "from",
    "what",
    "how",
    "why",
    "anyone",
}


def _candidate_terms(items: list[dict[str, Any]], query: str, limit: int = 12) -> list[dict[str, Any]]:
    query_tokens = {token.lower() for token in re.findall(r"[0-9A-Za-z가-힣+#.-]{2,}", query)}
    evidence: dict[str, dict[str, Any]] = defaultdict(
        lambda: {"clusters": set(), "platforms": set(), "example_urls": []}
    )
    for item in items:
        text = f"{item.get('title') or ''} {item.get('text_excerpt') or ''}"
        tokens = [
            token.lower()
            for token in re.findall(r"[0-9A-Za-z가-힣+#.-]{2,}", text)
            if token.lower() not in _STOPWORDS and token.lower() not in query_tokens
        ][:24]
        candidates = list(dict.fromkeys(tokens + [f"{left} {right}" for left, right in zip(tokens, tokens[1:])]))
        for term in candidates:
            if not (2 <= len(term) <= 50):
                continue
            record = evidence[term]
            record["clusters"].add(item.get("text_cluster"))
            record["platforms"].add(item.get("platform"))
            if item.get("url") and item["url"] not in record["example_urls"]:
                record["example_urls"].append(item["url"])
    rows = [
        {
            "term": term,
            "unique_text_mentions": len(record["clusters"]),
            "platform_count": len(record["platforms"]),
            "platforms": sorted(record["platforms"]),
            "example_urls": record["example_urls"][:3],
            "basis": "exact token/adjacent-token recurrence in the retrieved sample",
        }
        for term, record in evidence.items()
        if len(record["clusters"]) >= 2 or len(record["platforms"]) >= 2
    ]
    rows.sort(
        key=lambda row: (row["platform_count"], row["unique_text_mentions"], len(row["term"])),
        reverse=True,
    )
    return rows[:limit]


def summarise_community_signals(items: list[dict[str, Any]], query: str) -> dict[str, Any]:
    items = _deduplicate_items(items)
    by_platform: dict[str, list[dict[str, Any]]] = defaultdict(list)
    clusters: dict[str, set[str]] = defaultdict(set)
    for item in items:
        by_platform[item["platform"]].append(item)
        clusters[item["text_cluster"]].add(item["platform"])

    platform_summary: dict[str, Any] = {}
    for platform, rows in by_platform.items():
        comparable = [row["engagement"]["value"] for row in rows if row["engagement"]["value"] is not None]
        platform_summary[platform] = {
            "sample_item_count": len(rows),
            "unique_author_count": len({row["author_key"] for row in rows if row.get("author_key")}),
            "question_count": sum(bool(row.get("is_question")) for row in rows),
            "median_platform_local_engagement": statistics.median(comparable) if comparable else None,
            "engagement_warning": "Do not compare this value across platforms; units and ranking systems differ.",
        }

    question_cards = [row for row in items if row.get("is_question")]
    question_cards.sort(key=_item_sort_key, reverse=True)
    top_items = sorted(items, key=_item_sort_key, reverse=True)
    platforms_with_hits = sorted(by_platform)
    duplicated_across_platforms = sum(len(platforms) > 1 for platforms in clusters.values())
    independent_clusters = len(clusters)
    multi_platform = len(platforms_with_hits) >= 2 and independent_clusters >= 2

    def public_card(row: dict[str, Any]) -> dict[str, Any]:
        return {
            "platform": row.get("platform"),
            "title": row.get("title"),
            "text_excerpt": row.get("text_excerpt"),
            "community": row.get("community"),
            "published_at": row.get("published_at"),
            "engagement": row.get("engagement"),
            "url": row.get("url"),
        }

    return {
        "sample_item_count": len(items),
        "unique_text_cluster_count": independent_clusters,
        "platforms_with_hits": platforms_with_hits,
        "platform_summary": platform_summary,
        "cross_platform_signal": {
            "status": "multi_platform" if multi_platform else ("single_platform" if platforms_with_hits else "no_signal"),
            "platform_count": len(platforms_with_hits),
            "exact_text_clusters_seen_on_multiple_platforms": duplicated_across_platforms,
            "interpretation": (
                "Useful for candidate generation only; repeated conversation does not verify factual claims or predict Naver ranking."
            ),
        },
        "candidate_terms": _candidate_terms(items, query),
        "question_cards": [public_card(row) for row in question_cards[:10]],
        "top_conversation_cards": [public_card(row) for row in top_items[:10]],
    }


class CommunitySignalEngine:
    """Query available adapters and return a privacy-minimised evidence pack."""

    def __init__(
        self,
        adapters: Mapping[str, Any] | None = None,
        secrets: Mapping[str, str] | None = None,
    ):
        if adapters is not None:
            self.adapters = dict(adapters)
            return
        merged_secrets = dict(secrets or load_secrets())
        shared_naver = NaverClient(secrets=merged_secrets)
        self.adapters = {
            "naver_cafe": NaverCafeAdapter(shared_naver),
            "naver_kin": NaverKinAdapter(shared_naver),
            "daum_cafe": DaumCafeAdapter(merged_secrets),
            "bluesky": BlueskyAdapter(),
            "reddit": RedditAdapter(merged_secrets),
            "x": XAdapter(merged_secrets),
            "threads": ThreadsAdapter(merged_secrets),
            "hacker_news": HackerNewsAdapter(),
            "stackexchange": StackExchangeAdapter(merged_secrets),
        }

    def status(self) -> list[SourceStatus]:
        return [self.adapters[name].status() for name in SUPPORTED_PLATFORMS if name in self.adapters]

    def discover(
        self,
        query: str,
        platforms: list[str] | None = None,
        days: int = 7,
        max_results_per_source: int = 20,
        language: str | None = "ko",
        reddit_subreddits: list[str] | None = None,
        hacker_news_feeds: list[str] | None = None,
        stackexchange_site: str = "stackoverflow",
    ) -> dict[str, Any]:
        query = " ".join(str(query).split())
        if not query:
            raise ValueError("query must not be empty")
        if len(query) > 256:
            raise ValueError("query must be 256 characters or fewer")
        days = max(1, min(days, 30))
        max_results_per_source = max(1, min(max_results_per_source, 50))
        statuses = {status.source: status for status in self.status()}
        if platforms is None:
            selected = [
                name
                for name in DEFAULT_AUTO_PLATFORMS
                if statuses.get(name) and statuses[name].available
            ]
        else:
            selected = list(dict.fromkeys(str(name).strip().lower() for name in platforms if str(name).strip()))
            unknown = [name for name in selected if name not in self.adapters]
            if unknown:
                raise ValueError(f"unsupported platforms: {', '.join(unknown)}")

        all_items: list[dict[str, Any]] = []
        source_results: dict[str, Any] = {}
        source_errors: list[dict[str, Any]] = []
        for platform in selected:
            status = statuses[platform]
            if not status.available:
                source_errors.append(
                    {"source": platform, "message": status.detail, "status_code": None, "kind": "not_configured"}
                )
                source_results[platform] = {"items": [], "metadata": {}, "caveats": [status.detail], "cache_hit": False}
                continue
            cache_key = (
                platform,
                query,
                days,
                max_results_per_source,
                language,
                tuple(reddit_subreddits or []),
                tuple(hacker_news_feeds or []),
                stackexchange_site,
            )
            cached = _SEARCH_CACHE.get(cache_key)
            if cached and time.monotonic() - cached[0] < _CACHE_TTL_SECONDS:
                batch = cached[1]
                cache_hit = True
            else:
                try:
                    batch = self.adapters[platform].search(
                        query=query,
                        days=days,
                        limit=max_results_per_source,
                        language=language,
                        subreddits=reddit_subreddits,
                        hacker_news_feeds=hacker_news_feeds,
                        stackexchange_site=stackexchange_site,
                    )
                    if not isinstance(batch, CommunityBatch):
                        raise TypeError(f"{platform} adapter returned an invalid batch")
                    _SEARCH_CACHE[cache_key] = (time.monotonic(), batch)
                    cache_hit = False
                except SourceError as exc:
                    source_errors.append(
                        {
                            "source": exc.source,
                            "message": str(exc),
                            "status_code": exc.status_code,
                            "kind": "source_error",
                        }
                    )
                    source_results[platform] = {"items": [], "metadata": {}, "caveats": [], "cache_hit": False}
                    continue
                except requests.RequestException as exc:
                    source_errors.append(
                        {
                            "source": platform,
                            "message": f"{platform}: {exc}",
                            "status_code": None,
                            "kind": "network_error",
                        }
                    )
                    source_results[platform] = {"items": [], "metadata": {}, "caveats": [], "cache_hit": False}
                    continue
            items = _deduplicate_items(batch.items)[:max_results_per_source]
            all_items.extend(items)
            source_results[platform] = {
                "items": items,
                "metadata": batch.metadata,
                "caveats": batch.caveats,
                "cache_hit": cache_hit,
            }

        summary = summarise_community_signals(all_items, query)
        return {
            "query": query,
            "retrieved_at": _iso(datetime.now(timezone.utc)),
            "requested_days": days,
            "selected_platforms": selected,
            "source_status": [status.__dict__ for status in statuses.values()],
            "source_results": source_results,
            "summary": summary,
            "source_errors": source_errors,
            "usage_contract": {
                "allowed": "discover questions, vocabulary, objections, comparisons, and candidate topic angles",
                "not_allowed": "treat community posts as verified facts, ranking guarantees, or representative population statistics",
                "next_step": (
                    "Synthesize at most five topic candidates from linked evidence, then validate them with "
                    "discover_topic_opportunities before drafting."
                ),
            },
            "privacy": (
                "Author and item identifiers are replaced with short one-way hashes; excerpts are capped at 500 "
                "characters and are held only in a 60-second in-process response cache, with no durable store. "
                "Canonical evidence links may still identify the author on the source platform."
            ),
            "method_source_urls": [
                NAVER_CAFE_API_DOCS,
                NAVER_KIN_API_DOCS,
                KAKAO_CAFE_DOCS,
                KAKAO_QUOTA_DOCS,
                REDDIT_POLICY_DOCS,
                REDDIT_API_DOCS,
                X_SEARCH_DOCS,
                X_PRICING_DOCS,
                THREADS_SEARCH_DOCS,
                BLUESKY_SEARCH_DOCS,
                HACKER_NEWS_API_DOCS,
                STACKEXCHANGE_SEARCH_DOCS,
            ],
        }
