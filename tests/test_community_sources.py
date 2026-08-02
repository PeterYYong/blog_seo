from datetime import datetime, timedelta, timezone

from src.community_sources import (
    CommunityBatch,
    CommunitySignalEngine,
    DaumCafeAdapter,
    RedditAdapter,
    SourceStatus,
    ThreadsAdapter,
    XAdapter,
    _item,
    summarise_community_signals,
)
from src.seo_sources import NaverClient


class FakeResponse:
    def __init__(self, payload, ok=True, status_code=200, text=""):
        self._payload = payload
        self.ok = ok
        self.status_code = status_code
        self.text = text
        self.reason = text

    def json(self):
        return self._payload


class FakeSession:
    def __init__(self, responses):
        self.responses = list(responses)
        self.calls = []

    def get(self, url, **kwargs):
        self.calls.append(("GET", url, kwargs))
        return self.responses.pop(0)

    def post(self, url, **kwargs):
        self.calls.append(("POST", url, kwargs))
        return self.responses.pop(0)


def test_naver_community_search_preserves_unknown_timestamp():
    session = FakeSession(
        [
            FakeResponse(
                {
                    "total": 3,
                    "items": [
                        {
                            "title": "<b>성수</b> 새 카페",
                            "description": "좌석이 궁금해요",
                            "link": "https://cafe.naver.com/example/1",
                            "cafename": "서울 카페 모임",
                            "cafeurl": "https://cafe.naver.com/example",
                        }
                    ],
                }
            )
        ]
    )
    client = NaverClient(
        secrets={"NAVER_CLIENT_ID": "id", "NAVER_CLIENT_SECRET": "secret"},
        session=session,
    )

    result = client.cafe_search("성수 카페")

    assert result["total"] == 3
    assert result["items"][0]["title"] == "성수 새 카페"
    assert "post_date" not in result["items"][0]


def test_daum_cafe_applies_local_date_cutoff_to_recency_page():
    now = datetime.now(timezone.utc)
    session = FakeSession(
        [
            FakeResponse(
                {
                    "meta": {"total_count": 2, "pageable_count": 2, "is_end": True},
                    "documents": [
                        {
                            "title": "최근 질문",
                            "contents": "성수 카페 좌석",
                            "url": "https://cafe.daum.net/recent",
                            "cafename": "카페 모임",
                            "datetime": (now - timedelta(days=1)).isoformat(),
                        },
                        {
                            "title": "오래된 질문",
                            "contents": "성수 카페 좌석",
                            "url": "https://cafe.daum.net/old",
                            "cafename": "카페 모임",
                            "datetime": (now - timedelta(days=20)).isoformat(),
                        },
                    ],
                }
            )
        ]
    )
    adapter = DaumCafeAdapter(secrets={"KAKAO_REST_API_KEY": "key"}, session=session)

    result = adapter.search("성수 카페", days=7, limit=10)

    assert len(result.items) == 1
    assert result.items[0]["title"] == "최근 질문"
    assert result.metadata["server_side_timestamp_filter"] is False


def test_summary_keeps_platform_engagement_local_and_links_evidence():
    items = [
        _item(
            platform="bluesky",
            item_id="b1",
            title=None,
            text="성수 카페 노트북 좌석 추천 있나요?",
            url="https://bsky.app/example",
            author="one",
            engagement_value=10,
            engagement_unit="public interactions",
        ),
        _item(
            platform="naver_kin",
            item_id="n1",
            title="성수 카페 노트북 좌석 추천",
            text="콘센트 있는 곳을 찾습니다",
            url="https://kin.naver.com/example",
            author="two",
            force_question=True,
        ),
    ]

    summary = summarise_community_signals(items, "성수 카페")

    assert summary["cross_platform_signal"]["status"] == "multi_platform"
    assert summary["platform_summary"]["bluesky"]["median_platform_local_engagement"] == 10
    assert summary["platform_summary"]["naver_kin"]["median_platform_local_engagement"] is None
    assert "Do not compare" in summary["platform_summary"]["bluesky"]["engagement_warning"]
    assert len(summary["question_cards"]) == 2


class FakeAvailableAdapter:
    def status(self):
        return SourceStatus("bluesky", True, "ready", "https://example.com/docs")

    def search(self, **kwargs):
        return CommunityBatch(
            [
                _item(
                    platform="bluesky",
                    item_id="1",
                    title=None,
                    text="요즘 가장 궁금한 성수 카페 좌석은?",
                    url="https://bsky.app/1",
                )
            ],
            {"query": kwargs["query"]},
        )


class FakeUnavailableAdapter:
    def status(self):
        return SourceStatus("reddit", False, "approval missing", "https://example.com/policy")


def test_engine_reports_unavailable_requested_source_instead_of_zero():
    engine = CommunitySignalEngine(
        adapters={"bluesky": FakeAvailableAdapter(), "reddit": FakeUnavailableAdapter()}
    )

    report = engine.discover(
        "unique-community-test-query",
        platforms=["bluesky", "reddit"],
        max_results_per_source=5,
    )

    assert report["source_results"]["bluesky"]["items"]
    assert report["source_results"]["reddit"]["items"] == []
    assert report["source_errors"][0]["source"] == "reddit"
    assert report["source_errors"][0]["kind"] == "not_configured"
    assert report["usage_contract"]["not_allowed"].startswith("treat community posts")


def test_reddit_requires_explicit_policy_approval_even_with_credentials():
    adapter = RedditAdapter(
        secrets={
            "REDDIT_CLIENT_ID": "id",
            "REDDIT_CLIENT_SECRET": "secret",
            "REDDIT_USER_AGENT": "blog-seo-agent/1.0 by owner",
            "REDDIT_API_APPROVED": "false",
        }
    )

    status = adapter.status()

    assert status.available is False
    assert "approved" in status.detail


def test_x_recent_search_clips_window_and_keeps_impressions_out_of_interactions():
    session = FakeSession(
        [
            FakeResponse(
                {
                    "data": [
                        {
                            "id": "123",
                            "text": "성수 카페 어디가 좋나요?",
                            "created_at": "2026-08-01T00:00:00Z",
                            "author_id": "42",
                            "public_metrics": {
                                "like_count": 2,
                                "reply_count": 3,
                                "retweet_count": 4,
                                "quote_count": 1,
                                "bookmark_count": 2,
                                "impression_count": 9999,
                            },
                        }
                    ],
                    "meta": {"result_count": 1},
                }
            )
        ]
    )
    adapter = XAdapter(secrets={"X_BEARER_TOKEN": "token"}, session=session)

    result = adapter.search("성수 카페", days=30, limit=5, language="ko")

    assert result.items[0]["engagement"]["value"] == 12
    assert result.metadata["effective_days"] == 7
    assert any("clipped" in caveat for caveat in result.caveats)
    assert session.calls[0][2]["headers"]["Authorization"] == "Bearer token"


def test_threads_requires_explicit_enable_flag():
    adapter = ThreadsAdapter(secrets={"THREADS_ACCESS_TOKEN": "token"})

    status = adapter.status()

    assert status.available is False
    assert "explicitly enabled" in status.detail
