"""Evidence collection and relative topic-opportunity ranking.

The score is a prioritisation aid across the candidates in one run.  It is not
a probability of ranking, and none of its thresholds are claimed to be Naver's
internal ranking formula.
"""

from __future__ import annotations

import math
import statistics
from datetime import date, datetime, time, timedelta, timezone
from typing import Any, Iterable
from zoneinfo import ZoneInfo

try:
    from seo_sources import (
        NAVER_AD_API_DOCS,
        NAVER_API_HUB_DOCS,
        NAVER_API_MIGRATION_NOTICE,
        NAVER_BLOG_API_DOCS,
        NAVER_DATALAB_DOCS,
        YOUTUBE_SEARCH_DOCS,
        YOUTUBE_VIDEO_DOCS,
        NaverClient,
        SourceError,
        YouTubeClient,
    )
except ImportError:  # pragma: no cover - package import path
    from .seo_sources import (
        NAVER_AD_API_DOCS,
        NAVER_API_HUB_DOCS,
        NAVER_API_MIGRATION_NOTICE,
        NAVER_BLOG_API_DOCS,
        NAVER_DATALAB_DOCS,
        YOUTUBE_SEARCH_DOCS,
        YOUTUBE_VIDEO_DOCS,
        NaverClient,
        SourceError,
        YouTubeClient,
    )


KST = ZoneInfo("Asia/Seoul")


def _mean(values: Iterable[float]) -> float | None:
    clean = [float(value) for value in values if value is not None]
    return statistics.fmean(clean) if clean else None


def _median(values: Iterable[float]) -> float | None:
    clean = [float(value) for value in values if value is not None]
    return statistics.median(clean) if clean else None


def trend_summary(points: list[dict[str, Any]], recent_days: int = 7, prior_days: int = 21) -> dict[str, Any]:
    """Summarise within-series DataLab momentum without comparing raw levels."""

    values = [float(point.get("ratio", 0.0)) for point in points]
    needed = recent_days + prior_days
    if len(values) < max(2, recent_days):
        return {
            "recent_average": None,
            "prior_average": None,
            "momentum_ratio": None,
            "observation_count": len(values),
        }
    recent = values[-recent_days:]
    prior = values[-needed:-recent_days] if len(values) >= needed else values[:-recent_days]
    recent_average = _mean(recent)
    prior_average = _mean(prior)
    if recent_average is None or prior_average is None:
        momentum = None
    elif prior_average == 0:
        momentum = None if recent_average == 0 else 3.0
    else:
        momentum = min(3.0, recent_average / prior_average)
    return {
        "recent_average": round(recent_average, 3) if recent_average is not None else None,
        "prior_average": round(prior_average, 3) if prior_average is not None else None,
        "momentum_ratio": round(momentum, 3) if momentum is not None else None,
        "observation_count": len(values),
    }


def _post_age_days(post_date: str | None, today: date) -> int | None:
    if not post_date:
        return None
    try:
        parsed = datetime.strptime(post_date, "%Y%m%d").date()
        return max(0, (today - parsed).days)
    except ValueError:
        return None


def blog_summary(snapshot: dict[str, Any], today: date) -> dict[str, Any]:
    ages = [
        age
        for age in (_post_age_days(item.get("post_date"), today) for item in snapshot.get("items", []))
        if age is not None
    ]
    return {
        "total_results": int(snapshot.get("total", 0)),
        "sample_size": len(ages),
        "posts_within_30d": sum(age <= 30 for age in ages),
        "posts_within_90d": sum(age <= 90 for age in ages),
        "median_sample_age_days": round(_median(ages), 1) if ages else None,
        "query_url": snapshot.get("query_url"),
    }


def youtube_summary(videos: list[dict[str, Any]]) -> dict[str, Any]:
    velocities = [float(video.get("views_per_day", 0.0)) for video in videos]
    return {
        "video_count": len(videos),
        "median_views_per_day": round(_median(velocities), 2) if velocities else None,
        "total_views": sum(int(video.get("view_count", 0)) for video in videos),
        "top_videos": [
            {
                "title": video.get("title"),
                "views_per_day": video.get("views_per_day"),
                "view_count": video.get("view_count"),
                "published_at": video.get("published_at"),
                "url": video.get("url"),
            }
            for video in sorted(videos, key=lambda row: row.get("views_per_day", 0), reverse=True)[:3]
        ],
    }


def _percentile_scores(values: list[float | None], higher_is_better: bool = True) -> list[float]:
    """Return tie-aware 0-100 ranks; missing observations remain neutral."""

    observed = [float(value) for value in values if value is not None and math.isfinite(float(value))]
    if not observed or len(set(observed)) == 1:
        return [50.0 for _ in values]
    output: list[float] = []
    for value in values:
        if value is None or not math.isfinite(float(value)):
            output.append(50.0)
            continue
        numeric = float(value)
        below = sum(other < numeric for other in observed)
        equal = sum(other == numeric for other in observed)
        percentile = (below + 0.5 * equal) / len(observed) * 100.0
        output.append(percentile if higher_is_better else 100.0 - percentile)
    return output


def score_evidence(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Add a transparent relative score and confidence label to evidence rows."""

    if not rows:
        return rows
    demand = _percentile_scores([row.get("monthly_search_estimate") for row in rows])
    momentum = _percentile_scores([row.get("trend", {}).get("momentum_ratio") for row in rows])
    youtube = _percentile_scores([row.get("youtube", {}).get("median_views_per_day") for row in rows])
    pressure_values: list[float | None] = []
    for row in rows:
        total = row.get("blog", {}).get("total_results")
        volume = row.get("monthly_search_estimate")
        pressure_values.append(
            math.log1p(float(total)) / max(math.log1p(float(volume)), 1.0)
            if total is not None and volume not in (None, 0)
            else None
        )
    content_gap = _percentile_scores(pressure_values, higher_is_better=False)
    youtube_reference = _median(
        row.get("youtube", {}).get("median_views_per_day")
        for row in rows
        if row.get("youtube", {}).get("median_views_per_day") is not None
    )

    for index, row in enumerate(rows):
        available = row.get("available_sources", [])
        completeness = min(1.0, len(set(available)) / 4.0)
        source_families: list[str] = []
        if any(source.startswith("naver_") for source in available):
            source_families.append("naver")
        if "youtube_data_api" in available:
            source_families.append("youtube")
        cross_source_validated = len(source_families) >= 2
        row["source_families"] = source_families
        support_signals: list[str] = []
        volume = row.get("monthly_search_estimate")
        trend_ratio = row.get("trend", {}).get("momentum_ratio")
        yt_velocity = row.get("youtube", {}).get("median_views_per_day")
        if volume is not None and volume >= 100:
            support_signals.append("naver_absolute_demand")
        if trend_ratio is not None and trend_ratio >= 1.15:
            support_signals.append("naver_recent_momentum")
        if yt_velocity is not None and youtube_reference is not None and yt_velocity >= youtube_reference:
            support_signals.append("youtube_cross_source_interest")
        agreement_score = min(100.0, len(support_signals) / 3.0 * 100.0)
        raw_score = (
            0.30 * demand[index]
            + 0.30 * momentum[index]
            + 0.20 * youtube[index]
            + 0.15 * content_gap[index]
            + 0.05 * agreement_score
        )
        final_score = round(raw_score * (0.60 + 0.40 * completeness), 1)

        if completeness < 0.5:
            label = "insufficient_evidence"
            confidence = "low"
        elif not cross_source_validated:
            label = "verification_pending"
            confidence = "low"
        elif final_score >= 70:
            label = "strong_candidate"
            confidence = "high" if completeness == 1.0 and len(support_signals) >= 2 else "medium"
        elif final_score >= 55:
            label = "watch"
            confidence = "medium" if completeness >= 0.75 else "low"
        else:
            label = "low_priority"
            confidence = "medium" if completeness == 1.0 else "low"

        if trend_ratio is not None and trend_ratio >= 1.8:
            validity = "recheck within 24 hours"
        elif trend_ratio is not None and trend_ratio >= 1.15:
            validity = "recheck within 7 days"
        else:
            validity = "recheck within 30 days"

        row["opportunity"] = {
            "score": final_score,
            "label": label,
            "confidence": confidence,
            "popular_topic_eligible": cross_source_validated,
            "independent_source_family_count": len(source_families),
            "evidence_completeness": round(completeness, 2),
            "support_signals": support_signals,
            "validity": validity,
            "components": {
                "naver_demand_rank": round(demand[index], 1),
                "naver_momentum_rank": round(momentum[index], 1),
                "youtube_interest_rank": round(youtube[index], 1),
                "content_gap_rank": round(content_gap[index], 1),
                "source_agreement": round(agreement_score, 1),
            },
        }
        row["why_now"] = _why_now(row)
    return sorted(rows, key=lambda row: row["opportunity"]["score"], reverse=True)


def _why_now(row: dict[str, Any]) -> list[str]:
    reasons: list[str] = []
    volume = row.get("monthly_search_estimate")
    if volume is not None:
        qualifier = "censored estimate" if row.get("volume_censored") else "reported estimate"
        reasons.append(f"Naver monthly search demand: {volume:,} ({qualifier})")
    momentum = row.get("trend", {}).get("momentum_ratio")
    if momentum is not None:
        reasons.append(f"Naver recent 7-day level vs prior period: {momentum:.2f}x")
    youtube_velocity = row.get("youtube", {}).get("median_views_per_day")
    if youtube_velocity is not None:
        reasons.append(f"YouTube recent-video median velocity: {youtube_velocity:,.0f} views/day")
    blog_total = row.get("blog", {}).get("total_results")
    if blog_total is not None:
        reasons.append(f"Naver Blog API result count: {blog_total:,} (weak supply proxy only)")
    return reasons or ["No independent demand signal was available; do not present as a current trend."]


class OpportunityEngine:
    """Collect evidence from official APIs and rank current topic candidates."""

    def __init__(self, naver: NaverClient | None = None, youtube: YouTubeClient | None = None):
        self.naver = naver or NaverClient()
        self.youtube = youtube or YouTubeClient()

    def discover(
        self,
        seed: str,
        candidate_keywords: list[str] | None = None,
        max_candidates: int = 8,
        trend_days: int = 56,
        youtube_days: int = 30,
        region_code: str = "KR",
    ) -> dict[str, Any]:
        if not seed.strip():
            raise ValueError("seed must not be empty")
        max_candidates = max(1, min(max_candidates, 15))
        trend_days = max(28, min(trend_days, 365))
        youtube_days = max(7, min(youtube_days, 180))
        retrieved_at = datetime.now(KST)
        today = retrieved_at.date()
        source_errors: list[dict[str, Any]] = []
        related: list[dict[str, Any]] = []

        try:
            related = self.naver.related_keywords(seed, min_volume=10, limit=300)
        except SourceError as exc:
            source_errors.append(_source_error(exc))

        related_map = {
            _normalise_keyword(row["keyword"]): row for row in related if row.get("keyword")
        }
        if candidate_keywords:
            candidates = [seed, *candidate_keywords]
        else:
            candidates = [seed, *(row["keyword"] for row in related)]
        candidates = list(dict.fromkeys(keyword.strip() for keyword in candidates if keyword.strip()))[:max_candidates]

        trend_series: dict[str, list[dict[str, Any]]] = {}
        try:
            trend_series = self.naver.datalab_trends(
                candidates,
                start_date=today - timedelta(days=trend_days - 1),
                end_date=today,
                time_unit="date",
            )
        except SourceError as exc:
            source_errors.append(_source_error(exc))

        rows: list[dict[str, Any]] = []
        youtube_after = datetime.combine(
            today - timedelta(days=youtube_days), time.min, tzinfo=KST
        ).astimezone(timezone.utc)
        for keyword in candidates:
            related_row = related_map.get(_normalise_keyword(keyword), {})
            row: dict[str, Any] = {
                "keyword": keyword,
                "monthly_search_estimate": related_row.get("monthly_search_estimate"),
                "volume_censored": related_row.get("volume_censored"),
                "trend": trend_summary(trend_series.get(keyword, [])),
                "blog": {},
                "youtube": {},
                "available_sources": [],
                "source_urls": [],
                "caveats": [],
            }
            if related_row:
                row["available_sources"].append("naver_search_ads")
                row["source_urls"].append(NAVER_AD_API_DOCS)
                if related_row.get("volume_censored"):
                    row["caveats"].append("Search Ads volume contains '<10' censored values and uses a midpoint estimate.")
            if trend_series.get(keyword):
                row["available_sources"].append("naver_datalab")
                row["source_urls"].append(NAVER_DATALAB_DOCS)

            try:
                snapshot = self.naver.blog_search(keyword, display=20, sort="date")
                row["blog"] = blog_summary(snapshot, today)
                row["available_sources"].append("naver_blog_search")
                row["source_urls"].extend([NAVER_BLOG_API_DOCS, snapshot.get("query_url")])
            except SourceError as exc:
                source_errors.append({"keyword": keyword, **_source_error(exc)})

            try:
                videos = self.youtube.recent_videos(
                    keyword,
                    published_after=youtube_after,
                    max_results=10,
                    region_code=region_code,
                )
                row["youtube"] = youtube_summary(videos)
                row["available_sources"].append("youtube_data_api")
                row["source_urls"].append(YOUTUBE_SEARCH_DOCS)
                row["source_urls"].extend(video.get("url") for video in videos[:3])
            except SourceError as exc:
                source_errors.append({"keyword": keyword, **_source_error(exc)})

            row["source_urls"] = list(dict.fromkeys(url for url in row["source_urls"] if url))
            row["caveats"].extend(
                [
                    "DataLab values are relative, not absolute search counts.",
                    "Blog total is an all-time result-count proxy, not ranking difficulty or probability.",
                    "YouTube interest may not match Naver Blog search intent.",
                    "Naver APIs count as one source family; YouTube is the second family for cross-source validation.",
                ]
            )
            rows.append(row)

        scored = score_evidence(rows)
        return {
            "seed": seed,
            "retrieved_at": retrieved_at.isoformat(),
            "score_scope": "relative ranking within this candidate set; not a Naver ranking probability",
            "recommendations": scored,
            "source_errors": _deduplicate_errors(source_errors),
            "method_limits": [
                "Naver has no official API that enumerates all real-time trending search terms.",
                "Candidates come from the supplied seed, Search Ads related terms, or user-supplied terms.",
                "Re-run fast-moving topics at the validity interval shown on each evidence card.",
            ],
            "method_source_urls": [
                NAVER_API_HUB_DOCS,
                NAVER_API_MIGRATION_NOTICE,
                NAVER_AD_API_DOCS,
                NAVER_DATALAB_DOCS,
                NAVER_BLOG_API_DOCS,
                YOUTUBE_SEARCH_DOCS,
                YOUTUBE_VIDEO_DOCS,
            ],
        }


def _normalise_keyword(keyword: str) -> str:
    return re_sub_spaces(keyword).replace(" ", "").lower()


def re_sub_spaces(value: str) -> str:
    return " ".join(str(value).split())


def _source_error(exc: SourceError) -> dict[str, Any]:
    return {
        "source": exc.source,
        "message": str(exc),
        "status_code": exc.status_code,
    }


def _deduplicate_errors(errors: list[dict[str, Any]]) -> list[dict[str, Any]]:
    seen: set[tuple[Any, ...]] = set()
    unique: list[dict[str, Any]] = []
    for error in errors:
        key = (error.get("keyword"), error.get("source"), error.get("message"))
        if key not in seen:
            seen.add(key)
            unique.append(error)
    return unique
