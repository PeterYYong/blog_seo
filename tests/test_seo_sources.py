from datetime import date

import pytest
import requests

from src.seo_sources import NaverClient, SourceError


class FakeResponse:
    def __init__(self, payload, status_code=200, text="", headers=None):
        self._payload = payload
        self.status_code = status_code
        self.ok = status_code < 400
        self.text = text
        self.reason = text
        self.headers = headers or {}

    def json(self):
        return self._payload


class FakeSession:
    def __init__(self, responses):
        self.responses = list(responses)
        self.calls = []

    def get(self, url, **kwargs):
        self.calls.append(("GET", url, kwargs))
        response = self.responses.pop(0)
        if isinstance(response, Exception):
            raise response
        return response

    def post(self, url, **kwargs):
        self.calls.append(("POST", url, kwargs))
        response = self.responses.pop(0)
        if isinstance(response, Exception):
            raise response
        return response


def test_api_hub_credentials_use_current_search_endpoint_and_headers():
    session = FakeSession([FakeResponse({"total": 0, "items": []})])
    client = NaverClient(
        secrets={
            "NAVER_API_HUB_CLIENT_ID": "hub-id",
            "NAVER_API_HUB_CLIENT_SECRET": "hub-secret",
        },
        session=session,
    )

    client.blog_search("성수 카페")

    method, url, kwargs = session.calls[0]
    assert method == "GET"
    assert url == "https://naverapihub.apigw.ntruss.com/search/v1/blog"
    assert kwargs["headers"] == {
        "X-NCP-APIGW-API-KEY-ID": "hub-id",
        "X-NCP-APIGW-API-KEY": "hub-secret",
    }
    assert client.api_mode == "api_hub"


def test_api_hub_credentials_use_current_search_trend_endpoint():
    session = FakeSession([FakeResponse({"results": []})])
    client = NaverClient(
        secrets={
            "NAVER_API_HUB_CLIENT_ID": "hub-id",
            "NAVER_API_HUB_CLIENT_SECRET": "hub-secret",
        },
        session=session,
    )

    client.datalab_trends(["성수 카페"], date(2026, 7, 1), date(2026, 8, 1))

    method, url, kwargs = session.calls[0]
    assert method == "POST"
    assert url == "https://naverapihub.apigw.ntruss.com/search-trend/v1/search"
    assert kwargs["headers"]["X-NCP-APIGW-API-KEY-ID"] == "hub-id"


def test_legacy_developers_credentials_remain_supported_during_migration():
    session = FakeSession([FakeResponse({"total": 0, "items": []})])
    client = NaverClient(
        secrets={"NAVER_CLIENT_ID": "legacy-id", "NAVER_CLIENT_SECRET": "legacy-secret"},
        session=session,
    )

    client.cafe_search("성수 카페")

    _, url, kwargs = session.calls[0]
    assert url == "https://openapi.naver.com/v1/search/cafearticle.json"
    assert kwargs["headers"] == {
        "X-Naver-Client-Id": "legacy-id",
        "X-Naver-Client-Secret": "legacy-secret",
    }
    assert "migrate before 2027-06-30" in client.status()[1].detail


def test_search_ads_uses_current_official_service_url():
    session = FakeSession([FakeResponse({"keywordList": []})])
    client = NaverClient(
        secrets={
            "NAVER_AD_API_KEY": "license",
            "NAVER_AD_SECRET_KEY": "secret",
            "NAVER_CUSTOMER_ID": "customer",
        },
        session=session,
    )

    client.related_keywords("성수 카페")

    _, url, _ = session.calls[0]
    assert url == "https://api.searchad.naver.com/keywordstool"


def test_customer_id_is_coerced_to_a_valid_header_string():
    session = FakeSession([FakeResponse({"keywordList": []})])
    client = NaverClient(
        secrets={
            "NAVER_AD_API_KEY": "license",
            "NAVER_AD_SECRET_KEY": "secret",
            "NAVER_CUSTOMER_ID": 123456,
        },
        session=session,
    )

    client.related_keywords("성수 카페")

    assert session.calls[0][2]["headers"]["X-Customer"] == "123456"


def test_timeout_is_retried_once_and_never_converted_to_zero():
    session = FakeSession(
        [
            requests.Timeout("slow"),
            FakeResponse({"total": 0, "items": []}),
        ]
    )
    client = NaverClient(
        secrets={"NAVER_CLIENT_ID": "id", "NAVER_CLIENT_SECRET": "secret"},
        session=session,
        sleeper=lambda _: None,
    )

    result = client.blog_search("성수 카페")

    assert result["total"] == 0
    assert len(session.calls) == 2


def test_authentication_error_fails_without_retry():
    session = FakeSession([FakeResponse({}, status_code=401, text="invalid credential")])
    client = NaverClient(
        secrets={"NAVER_CLIENT_ID": "id", "NAVER_CLIENT_SECRET": "secret"},
        session=session,
        sleeper=lambda _: None,
    )

    with pytest.raises(SourceError) as caught:
        client.blog_search("성수 카페")

    assert caught.value.status_code == 401
    assert len(session.calls) == 1


def test_api_hub_rate_limit_waits_and_retries_once():
    sleeps = []
    session = FakeSession(
        [
            FakeResponse({}, status_code=429, text="rate limited"),
            FakeResponse({"total": 7, "items": []}),
        ]
    )
    client = NaverClient(
        secrets={"NAVER_CLIENT_ID": "id", "NAVER_CLIENT_SECRET": "secret"},
        session=session,
        sleeper=sleeps.append,
    )

    result = client.blog_search("성수 카페")

    assert result["total"] == 7
    assert len(session.calls) == 2
    assert sleeps == [1.0]


def test_api_hub_repeated_rate_or_quota_limit_stays_explicit():
    session = FakeSession(
        [
            FakeResponse({}, status_code=429, text="rate limited"),
            FakeResponse({}, status_code=429, text="still limited"),
        ]
    )
    client = NaverClient(
        secrets={"NAVER_CLIENT_ID": "id", "NAVER_CLIENT_SECRET": "secret"},
        session=session,
        sleeper=lambda _: None,
    )

    with pytest.raises(SourceError) as caught:
        client.blog_search("성수 카페")

    assert caught.value.status_code == 429
    assert len(session.calls) == 2


def test_search_ads_rate_limit_honours_one_bounded_retry():
    session = FakeSession(
        [
            FakeResponse({}, status_code=429, text="rate limited", headers={"Retry-After": "0"}),
            FakeResponse({"keywordList": []}),
        ]
    )
    client = NaverClient(
        secrets={
            "NAVER_AD_API_KEY": "license",
            "NAVER_AD_SECRET_KEY": "secret",
            "NAVER_CUSTOMER_ID": "customer",
        },
        session=session,
        sleeper=lambda _: None,
    )

    assert client.related_keywords("성수 카페") == []
    assert len(session.calls) == 2


@pytest.mark.parametrize(
    "payload",
    [
        {},
        {"total": 0},
        {"total": "not-a-count", "items": []},
        {"total": 1.9, "items": []},
        {"total": 0, "items": ["not-an-object"]},
    ],
)
def test_blog_search_rejects_malformed_success_payload_instead_of_returning_zero(payload):
    session = FakeSession([FakeResponse(payload)])
    client = NaverClient(
        secrets={"NAVER_CLIENT_ID": "id", "NAVER_CLIENT_SECRET": "secret"},
        session=session,
    )

    with pytest.raises(SourceError, match="response field"):
        client.blog_search("성수 카페")


@pytest.mark.parametrize("payload", [{}, {"keywordList": {}}, {"keywordList": ["bad"]}])
def test_search_ads_rejects_malformed_success_payload(payload):
    session = FakeSession([FakeResponse(payload)])
    client = NaverClient(
        secrets={
            "NAVER_AD_API_KEY": "license",
            "NAVER_AD_SECRET_KEY": "secret",
            "NAVER_CUSTOMER_ID": "customer",
        },
        session=session,
    )

    with pytest.raises(SourceError, match="keywordList"):
        client.related_keywords("성수 카페")


@pytest.mark.parametrize(
    "row",
    [
        {"relKeyword": "성수카페", "monthlyMobileQcCnt": 20},
        {
            "relKeyword": "성수카페",
            "monthlyPcQcCnt": "unknown",
            "monthlyMobileQcCnt": 20,
        },
        {
            "relKeyword": "성수카페",
            "monthlyPcQcCnt": 10,
            "monthlyMobileQcCnt": None,
        },
    ],
)
def test_search_ads_rejects_missing_or_invalid_volume_counts(row):
    session = FakeSession([FakeResponse({"keywordList": [row]})])
    client = NaverClient(
        secrets={
            "NAVER_AD_API_KEY": "license",
            "NAVER_AD_SECRET_KEY": "secret",
            "NAVER_CUSTOMER_ID": "customer",
        },
        session=session,
    )

    with pytest.raises(SourceError, match="monthly search count"):
        client.related_keywords("성수 카페", min_volume=0)


def test_datalab_rejects_missing_results_in_success_payload():
    session = FakeSession([FakeResponse({})])
    client = NaverClient(
        secrets={"NAVER_CLIENT_ID": "id", "NAVER_CLIENT_SECRET": "secret"},
        session=session,
    )

    with pytest.raises(SourceError, match="results"):
        client.datalab_trends(
            ["성수 카페"],
            date(2026, 7, 1),
            date(2026, 8, 1),
        )


def test_datalab_normalizes_valid_ratio_to_float():
    session = FakeSession(
        [
            FakeResponse(
                {
                    "results": [
                        {
                            "title": "성수 카페",
                            "data": [{"period": "2026-09-01", "ratio": 10}],
                        }
                    ]
                }
            )
        ]
    )
    client = NaverClient(
        secrets={"NAVER_CLIENT_ID": "id", "NAVER_CLIENT_SECRET": "secret"},
        session=session,
    )

    result = client.datalab_trends(
        ["성수 카페"],
        date(2026, 7, 1),
        date(2026, 9, 1),
    )

    assert result["성수 카페"][0]["ratio"] == 10.0
    assert isinstance(result["성수 카페"][0]["ratio"], float)


@pytest.mark.parametrize(
    "data",
    [
        ["bad"],
        [{"period": "2026-09-01"}],
        [{"period": "2026-09-01", "ratio": None}],
        [{"period": "2026-09-01", "ratio": float("nan")}],
        [{"period": "2026-09-01", "ratio": -1}],
        [{"period": "2026-09-01", "ratio": 100.01}],
        [{"period": "2026-09-01", "ratio": "10"}],
    ],
)
def test_datalab_rejects_malformed_series_points(data):
    session = FakeSession(
        [FakeResponse({"results": [{"title": "성수 카페", "data": data}]})]
    )
    client = NaverClient(
        secrets={"NAVER_CLIENT_ID": "id", "NAVER_CLIENT_SECRET": "secret"},
        session=session,
    )

    with pytest.raises(SourceError, match="response field"):
        client.datalab_trends(
            ["성수 카페"],
            date(2026, 7, 1),
            date(2026, 8, 1),
        )


def test_censored_low_volume_row_does_not_bypass_minimum_volume():
    payload = {
        "keywordList": [
            {
                "relKeyword": "희귀키워드",
                "monthlyPcQcCnt": "< 10",
                "monthlyMobileQcCnt": "< 10",
                "compIdx": "LOW",
            }
        ]
    }
    session = FakeSession([FakeResponse(payload), FakeResponse(payload)])
    client = NaverClient(
        secrets={
            "NAVER_AD_API_KEY": "license",
            "NAVER_AD_SECRET_KEY": "secret",
            "NAVER_CUSTOMER_ID": "customer",
        },
        session=session,
    )

    assert client.related_keywords("희귀 키워드", min_volume=100) == []
    included = client.related_keywords("희귀 키워드", min_volume=0)
    assert included[0]["monthly_search_estimate"] < 20
    assert included[0]["volume_censored"] is True
