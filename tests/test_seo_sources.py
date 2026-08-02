from datetime import date

from src.seo_sources import NaverClient


class FakeResponse:
    ok = True
    status_code = 200
    text = ""
    reason = ""

    def __init__(self, payload):
        self._payload = payload

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
