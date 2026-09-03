"""Collect verified Korean search trends and build the legacy CLI report.

The previous implementation scraped a JavaScript-only third-party page. A
plain HTTP client could not see its rendered rankings, so the function usually
returned a fixed example list. Google Trends publishes a server-rendered RSS
feed for South Korea, which is both machine-readable and attributable.
"""

from __future__ import annotations

import os
import sys
import argparse
import time
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any
from collections.abc import Callable

import pandas as pd
import requests


# --- Path Setup ---
current_dir = os.path.dirname(os.path.abspath(__file__))
if not __package__ and current_dir not in sys.path:
    sys.path.append(current_dir)

if __package__:
    from src.keyword_expander import expand_keyword
    from src.data_fetcher import RealDataFetcher, fetch_keyword_data
    from src.calculator import (
        calculate_efficiency,
        calculate_saturation,
        filter_keywords,
    )
    from src.seo_sources import SourceError, SourceFailureCircuitBreaker
else:  # Streamlit/direct-script imports keep the legacy top-level path.
    from keyword_expander import expand_keyword
    from data_fetcher import RealDataFetcher, fetch_keyword_data
    from calculator import calculate_saturation, calculate_efficiency, filter_keywords
    from seo_sources import SourceError, SourceFailureCircuitBreaker


GOOGLE_TRENDS_KR_RSS_URL = "https://trends.google.com/trending/rss?geo=KR"
GOOGLE_TRENDS_RSS_BASE_URL = "https://trends.google.com/trending/rss"
GOOGLE_TRENDS_SOURCE = "google_trends_rss"
REQUEST_TIMEOUT_SECONDS = 10
MAX_ATTEMPTS = 2  # initial request plus at most one transient retry
TRANSIENT_HTTP_STATUS = frozenset({408, 425, 429, 500, 502, 503, 504})


@dataclass(frozen=True)
class TrendTopic:
    """One Google Trends RSS item without pretending estimates are exact."""

    keyword: str
    approx_traffic: str | None
    published_at: str | None


@dataclass(frozen=True)
class TrendSnapshot:
    """A traceable point-in-time view of the Google Trends feed."""

    keywords: tuple[str, ...]
    source: str
    source_url: str
    retrieved_at: datetime
    topics: tuple[TrendTopic, ...] = ()
    geo: str = "KR"


def _response_detail(response: Any) -> str:
    text = str(getattr(response, "text", "") or "").strip()
    reason = str(getattr(response, "reason", "") or "").strip()
    return (text or reason or "request failed")[:300]


def _normalise_geo(geo: str) -> str:
    if not isinstance(geo, str):
        raise ValueError("geo must be a two-letter country code")
    normalised = geo.strip().upper()
    if len(normalised) != 2 or not normalised.isascii() or not normalised.isalpha():
        raise ValueError("geo must be a two-letter country code")
    return normalised


def _google_trends_url(geo: str) -> str:
    return f"{GOOGLE_TRENDS_RSS_BASE_URL}?geo={geo}"


def _request_google_trends_rss(
    geo: str = "KR",
    session: Any = requests,
    sleeper: Callable[[float], None] = time.sleep,
) -> bytes | str:
    """Download the feed, retrying a transient failure no more than once."""

    headers = {
        "Accept": "application/rss+xml, application/xml;q=0.9, text/xml;q=0.8",
        "User-Agent": "blog-seo-trend-reader/1.0",
    }

    for attempt in range(MAX_ATTEMPTS):
        try:
            response = session.get(
                _google_trends_url(geo),
                headers=headers,
                timeout=REQUEST_TIMEOUT_SECONDS,
            )
        except (requests.Timeout, requests.ConnectionError) as exc:
            if attempt + 1 < MAX_ATTEMPTS:
                sleeper(0.4 * (2**attempt))
                continue
            raise SourceError(
                GOOGLE_TRENDS_SOURCE,
                f"network request failed after {MAX_ATTEMPTS} attempts: {exc}",
            ) from exc
        except requests.RequestException as exc:
            raise SourceError(
                GOOGLE_TRENDS_SOURCE,
                f"network request failed: {exc}",
            ) from exc

        status_code = int(getattr(response, "status_code", 0) or 0)
        if 200 <= status_code < 300:
            content = getattr(response, "content", None)
            return content if content is not None else getattr(response, "text", "")

        if status_code in TRANSIENT_HTTP_STATUS and attempt + 1 < MAX_ATTEMPTS:
            headers = getattr(response, "headers", {}) or {}
            retry_after = headers.get("Retry-After")
            try:
                delay = min(float(retry_after), 3.0) if retry_after else 0.4 * (2**attempt)
            except (TypeError, ValueError):
                delay = 0.4 * (2**attempt)
            sleeper(max(0.0, delay))
            continue

        raise SourceError(
            GOOGLE_TRENDS_SOURCE,
            f"HTTP {status_code}: {_response_detail(response)}",
            status_code or None,
        )

    # The loop either returns or raises. Keep an explicit guard for safety if
    # retry settings are changed later.
    raise SourceError(GOOGLE_TRENDS_SOURCE, "request attempts exhausted")


def _local_name(tag: str) -> str:
    return tag.rsplit("}", 1)[-1]


def _item_text(item: ET.Element, name: str) -> str | None:
    element = next(
        (child for child in item if _local_name(child.tag) == name),
        None,
    )
    if element is None:
        return None
    text = " ".join("".join(element.itertext()).split())
    return text or None


def _parse_google_trends_rss(payload: bytes | str, limit: int) -> list[TrendTopic]:
    """Parse RSS items, preserving source order and first-seen spelling."""

    try:
        root = ET.fromstring(payload)
    except (ET.ParseError, TypeError, ValueError) as exc:
        raise SourceError(
            GOOGLE_TRENDS_SOURCE,
            f"invalid RSS XML: {exc}",
        ) from exc

    topics: list[TrendTopic] = []
    seen: set[str] = set()
    for item in root.iter():
        if _local_name(item.tag) != "item":
            continue
        keyword = _item_text(item, "title")
        if keyword is None:
            continue
        normalised = keyword.casefold()
        if normalised in seen:
            continue
        seen.add(normalised)
        topics.append(
            TrendTopic(
                keyword=keyword,
                approx_traffic=_item_text(item, "approx_traffic"),
                published_at=_item_text(item, "pubDate"),
            )
        )
        if len(topics) >= limit:
            break

    if not topics:
        raise SourceError(
            GOOGLE_TRENDS_SOURCE,
            "RSS feed contained no non-empty trend item titles",
        )
    return topics


def fetch_trending_snapshot(
    limit: int = 5,
    geo: str = "KR",
    *,
    session: Any = requests,
    retrieved_at: datetime | None = None,
    sleeper: Callable[[float], None] = time.sleep,
) -> TrendSnapshot:
    """Return verified Korean trends together with retrieval provenance."""

    if isinstance(limit, bool) or not isinstance(limit, int) or limit < 1:
        raise ValueError("limit must be a positive integer")
    normalised_geo = _normalise_geo(geo)

    payload = _request_google_trends_rss(
        geo=normalised_geo,
        session=session,
        sleeper=sleeper,
    )
    topics = _parse_google_trends_rss(payload, limit=limit)
    timestamp = retrieved_at or datetime.now(timezone.utc)
    if timestamp.tzinfo is None:
        timestamp = timestamp.replace(tzinfo=timezone.utc)
    return TrendSnapshot(
        keywords=tuple(topic.keyword for topic in topics),
        source=GOOGLE_TRENDS_SOURCE,
        source_url=_google_trends_url(normalised_geo),
        retrieved_at=timestamp,
        topics=tuple(topics),
        geo=normalised_geo,
    )


def fetch_trending_topics(limit: int = 5, geo: str = "KR") -> list[dict[str, Any]]:
    """Return structured Google Trends rows for the Streamlit dashboard."""

    snapshot = fetch_trending_snapshot(limit=limit, geo=geo)
    retrieved_at = snapshot.retrieved_at.isoformat()
    return [
        {
            "keyword": topic.keyword,
            "approx_traffic": topic.approx_traffic,
            "published_at": topic.published_at,
            "source": snapshot.source,
            "source_url": snapshot.source_url,
            "retrieved_at": retrieved_at,
        }
        for topic in snapshot.topics
    ]


def fetch_trending_keywords(limit: int = 5) -> list[str]:
    """Return Korean Google Trends terms using the legacy list interface.

    Existing callers continue to receive ``list[str]``. Unlike the old scraper,
    source failures raise :class:`SourceError`; they are never replaced with
    fabricated or stale example keywords.
    """

    return list(fetch_trending_snapshot(limit=limit).keywords)


def _ordered_unique_expansions(trends: tuple[str, ...]) -> list[str]:
    targets: list[str] = []
    seen: set[str] = set()
    for trend in trends:
        expanded_list, _ = expand_keyword(trend)
        for keyword in expanded_list:
            if keyword in seen:
                continue
            seen.add(keyword)
            targets.append(keyword)
    return targets


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Verify Google Trends Korea topics with Naver SEO metrics"
    )
    parser.add_argument(
        "--trend-limit",
        type=int,
        default=5,
        choices=range(1, 11),
        metavar="1-10",
        help="Google Trends topics to fetch (default: 5)",
    )
    parser.add_argument(
        "--keyword-limit",
        type=int,
        default=30,
        choices=range(1, 101),
        metavar="1-100",
        help="expanded keywords to verify (default: 30)",
    )
    args = parser.parse_args(argv)
    print("🌊 [Trend Deep Diver] Starting Analysis...")

    # 1. Fetch official Google Trends KR RSS
    print(f"   📡 Fetching Korean trends from {GOOGLE_TRENDS_KR_RSS_URL}...")
    try:
        snapshot = fetch_trending_snapshot(limit=args.trend_limit)
    except SourceError as exc:
        print(f"   ❌ Verified trend source unavailable: {exc}")
        return 1

    trends = snapshot.keywords
    print(f"   🔥 Identified Top {len(trends)} Google Trends terms: {list(trends)}")

    # 2. Expand (Deep Dive)
    print("   🧠 Expanding trends into sub-topics...")
    unique_targets = _ordered_unique_expansions(trends)[: args.keyword_limit]
    print(f"   🚀 Total Keywords to Analyze: {len(unique_targets)} (Duplicates removed)")

    # 3. Analyze (Real API)
    print("   📡 Connecting to Naver API...")
    data = []
    source_failures = 0
    skipped_after_source_abort = 0
    fetcher = RealDataFetcher()
    failure_guard = SourceFailureCircuitBreaker()

    for i, kw in enumerate(unique_targets):
        print(f"      [{i+1}/{len(unique_targets)}] Analyzing '{kw}'...", end="\r")
        try:
            data.append(fetch_keyword_data(kw, fetcher=fetcher))
            failure_guard.record_success()
        except SourceError as exc:
            source_failures += 1
            if failure_guard.should_abort(exc):
                skipped_after_source_abort = len(unique_targets) - i - 1
                print(
                    "\n   ⛔ 인증·할당량 또는 연속 출처 장애로 남은 "
                    f"{skipped_after_source_abort}개 키워드 조회를 중단합니다."
                )
                break

    print("\n   ✅ Data Collection Complete.")

    if not data:
        print("   ❌ No data available.")
        return 1

    df = pd.DataFrame(data)

    # 4. Calculation
    print("   🧮 Calculating Sk & Ek...")
    try:
        df["Saturation_Index"] = df.apply(
            lambda row: calculate_saturation(
                row["Total_Docs"], row["Monthly_Search_Volume"]
            ),
            axis=1,
        )
        df["Efficiency_Score"] = df.apply(
            lambda row: calculate_efficiency(
                row["Saturation_Index"], row["Monthly_Search_Volume"]
            ),
            axis=1,
        )
    except KeyError as exc:
        print(f"   ❌ Calculation Error (Keys): {exc}")
        return 1

    # 5. Filter and sort legacy low-supply-ratio candidates
    blue_ocean = filter_keywords(df)
    blue_ocean = blue_ocean.sort_values(by="Efficiency_Score", ascending=False)

    # 6. Reporting
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    os.makedirs("reports", exist_ok=True)
    report_file = f"reports/DEEP_DIVE_{timestamp}.md"

    if not blue_ocean.empty:
        blue_ocean["Saturation_Index"] = blue_ocean["Saturation_Index"].round(2)
        blue_ocean["Efficiency_Score"] = blue_ocean["Efficiency_Score"].round(2)

    try:
        table_md = blue_ocean[
            [
                "Keyword",
                "Monthly_Search_Volume",
                "Search_Volume_Censored",
                "Search_Volume_PC_Raw",
                "Search_Volume_Mobile_Raw",
                "Total_Docs",
                "Saturation_Index",
                "Efficiency_Score",
                "SmartBlock_Type",
            ]
        ].to_markdown(index=False)
    except ImportError:
        table_md = blue_ocean.to_string()
    except KeyError:
        table_md = blue_ocean.to_markdown()

    retrieved_at = snapshot.retrieved_at.isoformat()
    report_content = f"""# 🌊 실시간 트렌드 딥 다이브 리포트
**Timestamp:** {timestamp}
**Trend source:** Google Trends KR RSS ({snapshot.source_url})
**Trend retrieved at (UTC):** {retrieved_at}
**SEO metrics source:** Naver APIs

## 1. 🔍 Analysis Context
- **Base Trends:** {', '.join(trends)}
- **Total Keywords Scanned:** {len(unique_targets)}
- **Source failures excluded:** {source_failures}
- **Skipped after source circuit breaker:** {skipped_after_source_abort}
- **Legacy candidates found:** {len(blue_ocean)}

## 2. Legacy low-supply-ratio candidates ($S_k < 5.0$)
*Sorted by a local heuristic. This is not an official Naver score or ranking probability.*

*If `Search_Volume_Censored` is `True`, the monthly estimate includes a midpoint for a raw `<10` Search Ads value. Inspect the PC/mobile raw columns instead of treating it as exact.*

{table_md if not blue_ocean.empty else "No candidate met the legacy demand and supply-ratio thresholds."}

## 3. 💡 Strategy
- Re-check candidates with official Naver DataLab and YouTube evidence before calling them current opportunities.
- Inspect the actual reader intent and write only from verified facts.
- If the list is empty, the legacy ratio found no candidate; it does not prove the market is a red ocean.
"""

    with open(report_file, "w", encoding="utf-8") as f:
        f.write(report_content)

    print(f"   📝 Deep Dive Report generated: {report_file}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
