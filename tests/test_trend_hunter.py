from datetime import datetime, timezone

import pytest
import requests

from src import trend_hunter
from src.seo_sources import SourceError


RSS = """<?xml version="1.0" encoding="UTF-8"?>
<rss version="2.0" xmlns:ht="https://trends.google.com/trending/rss">
  <channel>
    <title>Daily Search Trends</title>
    <item>
      <title>아이폰17</title>
      <ht:approx_traffic>2,000+</ht:approx_traffic>
      <pubDate>Thu, 03 Sep 2026 00:00:00 -0700</pubDate>
    </item>
    <item>
      <title>  Korea   Open  </title>
      <ht:approx_traffic>500+</ht:approx_traffic>
      <pubDate>Wed, 02 Sep 2026 22:00:00 -0700</pubDate>
    </item>
    <item><title>korea open</title><ht:approx_traffic>20,000+</ht:approx_traffic></item>
    <item><title>10월 3일 행사</title></item>
  </channel>
</rss>
"""


class FakeResponse:
    def __init__(
        self,
        status_code=200,
        content=RSS,
        *,
        text="",
        reason="",
    ):
        self.status_code = status_code
        self.content = content
        self.text = text
        self.reason = reason
        self.headers = {}


class FakeSession:
    def __init__(self, outcomes):
        self.outcomes = list(outcomes)
        self.calls = []

    def get(self, url, **kwargs):
        self.calls.append((url, kwargs))
        outcome = self.outcomes.pop(0)
        if isinstance(outcome, BaseException):
            raise outcome
        return outcome


def test_snapshot_parses_rss_deduplicates_deterministically_and_keeps_digits():
    retrieved_at = datetime(2026, 9, 3, 8, 30, tzinfo=timezone.utc)
    session = FakeSession([FakeResponse()])

    snapshot = trend_hunter.fetch_trending_snapshot(
        limit=10,
        session=session,
        retrieved_at=retrieved_at,
    )

    assert snapshot.keywords == ("아이폰17", "Korea Open", "10월 3일 행사")
    assert snapshot.topics == (
        trend_hunter.TrendTopic(
            keyword="아이폰17",
            approx_traffic="2,000+",
            published_at="Thu, 03 Sep 2026 00:00:00 -0700",
        ),
        trend_hunter.TrendTopic(
            keyword="Korea Open",
            approx_traffic="500+",
            published_at="Wed, 02 Sep 2026 22:00:00 -0700",
        ),
        trend_hunter.TrendTopic(
            keyword="10월 3일 행사",
            approx_traffic=None,
            published_at=None,
        ),
    )
    assert snapshot.source == trend_hunter.GOOGLE_TRENDS_SOURCE
    assert snapshot.source_url == trend_hunter.GOOGLE_TRENDS_KR_RSS_URL
    assert snapshot.retrieved_at == retrieved_at
    assert session.calls == [
        (
            trend_hunter.GOOGLE_TRENDS_KR_RSS_URL,
            {
                "headers": {
                    "Accept": (
                        "application/rss+xml, application/xml;q=0.9, "
                        "text/xml;q=0.8"
                    ),
                    "User-Agent": "blog-seo-trend-reader/1.0",
                },
                "timeout": trend_hunter.REQUEST_TIMEOUT_SECONDS,
            },
        )
    ]


def test_snapshot_honours_limit_in_source_order():
    snapshot = trend_hunter.fetch_trending_snapshot(
        limit=2,
        session=FakeSession([FakeResponse()]),
    )

    assert snapshot.keywords == ("아이폰17", "Korea Open")


def test_snapshot_normalises_geo_and_uses_it_in_source_url():
    session = FakeSession([FakeResponse()])

    snapshot = trend_hunter.fetch_trending_snapshot(
        limit=1,
        geo=" us ",
        session=session,
    )

    assert snapshot.geo == "US"
    assert snapshot.source_url == "https://trends.google.com/trending/rss?geo=US"
    assert session.calls[0][0] == snapshot.source_url


def test_legacy_fetch_trending_keywords_returns_list(monkeypatch):
    snapshot = trend_hunter.TrendSnapshot(
        keywords=("첫째", "둘째"),
        source=trend_hunter.GOOGLE_TRENDS_SOURCE,
        source_url=trend_hunter.GOOGLE_TRENDS_KR_RSS_URL,
        retrieved_at=datetime.now(timezone.utc),
    )
    monkeypatch.setattr(
        trend_hunter,
        "fetch_trending_snapshot",
        lambda limit: snapshot,
    )

    result = trend_hunter.fetch_trending_keywords(limit=2)

    assert result == ["첫째", "둘째"]
    assert isinstance(result, list)


def test_fetch_trending_topics_returns_dashboard_contract_and_metadata(monkeypatch):
    retrieved_at = datetime(2026, 9, 3, 8, 30, tzinfo=timezone.utc)
    snapshot = trend_hunter.TrendSnapshot(
        keywords=("아이폰17",),
        source=trend_hunter.GOOGLE_TRENDS_SOURCE,
        source_url=trend_hunter.GOOGLE_TRENDS_KR_RSS_URL,
        retrieved_at=retrieved_at,
        topics=(
            trend_hunter.TrendTopic(
                keyword="아이폰17",
                approx_traffic="2,000+",
                published_at="Thu, 03 Sep 2026 00:00:00 -0700",
            ),
        ),
    )
    calls = []

    def fake_snapshot(limit, geo):
        calls.append((limit, geo))
        return snapshot

    monkeypatch.setattr(trend_hunter, "fetch_trending_snapshot", fake_snapshot)

    assert trend_hunter.fetch_trending_topics(limit=1, geo="kr") == [
        {
            "keyword": "아이폰17",
            "approx_traffic": "2,000+",
            "published_at": "Thu, 03 Sep 2026 00:00:00 -0700",
            "source": trend_hunter.GOOGLE_TRENDS_SOURCE,
            "source_url": trend_hunter.GOOGLE_TRENDS_KR_RSS_URL,
            "retrieved_at": retrieved_at.isoformat(),
        }
    ]
    assert calls == [(1, "kr")]


def test_transient_http_error_is_retried_once_then_succeeds():
    sleeps = []
    session = FakeSession(
        [
            FakeResponse(503, b"", text="temporarily unavailable"),
            FakeResponse(200, RSS),
        ]
    )

    snapshot = trend_hunter.fetch_trending_snapshot(
        limit=1,
        session=session,
        sleeper=sleeps.append,
    )

    assert snapshot.keywords == ("아이폰17",)
    assert len(session.calls) == 2
    assert sleeps == [0.4]


def test_transient_http_error_is_never_attempted_more_than_twice():
    session = FakeSession(
        [
            FakeResponse(429, b"", text="rate limited"),
            FakeResponse(503, b"", text="still unavailable"),
        ]
    )

    with pytest.raises(SourceError, match=r"HTTP 503") as caught:
        trend_hunter.fetch_trending_snapshot(
            limit=1,
            session=session,
            sleeper=lambda _: None,
        )

    assert caught.value.source == trend_hunter.GOOGLE_TRENDS_SOURCE
    assert caught.value.status_code == 503
    assert len(session.calls) == 2


def test_non_transient_http_error_is_not_retried():
    session = FakeSession([FakeResponse(404, b"", text="not found")])

    with pytest.raises(SourceError, match=r"HTTP 404") as caught:
        trend_hunter.fetch_trending_snapshot(limit=1, session=session)

    assert caught.value.status_code == 404
    assert len(session.calls) == 1


def test_timeout_is_retried_once_and_raised_as_source_error():
    session = FakeSession(
        [requests.Timeout("first timeout"), requests.Timeout("second timeout")]
    )

    with pytest.raises(SourceError, match="after 2 attempts") as caught:
        trend_hunter.fetch_trending_snapshot(
            limit=1,
            session=session,
            sleeper=lambda _: None,
        )

    assert caught.value.source == trend_hunter.GOOGLE_TRENDS_SOURCE
    assert caught.value.status_code is None
    assert len(session.calls) == 2


def test_non_transient_request_error_is_not_retried():
    session = FakeSession([requests.RequestException("bad request setup")])

    with pytest.raises(SourceError, match="network request failed"):
        trend_hunter.fetch_trending_snapshot(limit=1, session=session)

    assert len(session.calls) == 1


def test_malformed_xml_raises_source_error():
    session = FakeSession([FakeResponse(200, b"<rss><channel>")])

    with pytest.raises(SourceError, match="invalid RSS XML"):
        trend_hunter.fetch_trending_snapshot(limit=5, session=session)


def test_empty_feed_raises_source_error_instead_of_fixed_fallback():
    empty_rss = b"<rss><channel><title>Daily Search Trends</title></channel></rss>"
    session = FakeSession([FakeResponse(200, empty_rss)])

    with pytest.raises(SourceError, match="no non-empty trend item titles"):
        trend_hunter.fetch_trending_snapshot(limit=5, session=session)


@pytest.mark.parametrize("limit", [0, -1, 1.5, True, "5"])
def test_limit_must_be_a_positive_integer(limit):
    session = FakeSession([FakeResponse()])

    with pytest.raises(ValueError, match="positive integer"):
        trend_hunter.fetch_trending_snapshot(limit=limit, session=session)

    assert session.calls == []
