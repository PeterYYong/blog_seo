from datetime import date

from src.opportunity import OpportunityEngine, score_evidence, trend_summary
from src.seo_sources import SourceError


def test_trend_summary_compares_recent_to_prior_period():
    points = [{"ratio": 10}] * 21 + [{"ratio": 20}] * 7

    summary = trend_summary(points)

    assert summary["recent_average"] == 20
    assert summary["prior_average"] == 10
    assert summary["momentum_ratio"] == 2


def test_scoring_keeps_evidence_and_does_not_claim_probability():
    rows = [
        {
            "keyword": "rising",
            "monthly_search_estimate": 1000,
            "volume_censored": False,
            "trend": {"momentum_ratio": 1.8},
            "blog": {"total_results": 200},
            "youtube": {"median_views_per_day": 5000},
            "available_sources": [
                "naver_search_ads",
                "naver_datalab",
                "naver_blog_search",
                "youtube_data_api",
            ],
        },
        {
            "keyword": "flat",
            "monthly_search_estimate": 100,
            "volume_censored": False,
            "trend": {"momentum_ratio": 0.8},
            "blog": {"total_results": 10000},
            "youtube": {"median_views_per_day": 20},
            "available_sources": ["naver_search_ads", "naver_blog_search"],
        },
    ]

    scored = score_evidence(rows)

    assert scored[0]["keyword"] == "rising"
    assert scored[0]["opportunity"]["confidence"] in {"high", "medium"}
    assert scored[0]["opportunity"]["score"] <= 100
    assert scored[0]["source_families"] == ["naver", "youtube"]
    assert scored[0]["opportunity"]["popular_topic_eligible"] is True
    assert all("probability" not in reason.lower() for reason in scored[0]["why_now"])


class FakeNaver:
    def related_keywords(self, seed, min_volume, limit):
        return [
            {
                "keyword": seed,
                "monthly_search_estimate": 500,
                "volume_censored": False,
            }
        ]

    def datalab_trends(self, keywords, start_date, end_date, time_unit):
        return {keywords[0]: [{"period": str(date.today()), "ratio": 10}] * 28}

    def blog_search(self, query, display, sort):
        return {
            "total": 100,
            "items": [{"post_date": date.today().strftime("%Y%m%d")}],
            "query_url": "https://search.naver.com/example",
        }


class FailingYouTube:
    def recent_videos(self, *args, **kwargs):
        raise SourceError("youtube_data_api", "quota unavailable")


def test_source_failure_is_reported_instead_of_becoming_zero():
    report = OpportunityEngine(naver=FakeNaver(), youtube=FailingYouTube()).discover(
        "성수 맛집", max_candidates=1
    )

    recommendation = report["recommendations"][0]
    assert recommendation["youtube"] == {}
    assert "youtube_data_api" not in recommendation["available_sources"]
    assert recommendation["opportunity"]["label"] == "verification_pending"
    assert recommendation["opportunity"]["popular_topic_eligible"] is False
    assert report["source_errors"][0]["source"] == "youtube_data_api"
    assert "relative ranking" in report["score_scope"]
