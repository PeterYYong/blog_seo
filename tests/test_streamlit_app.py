from pathlib import Path

import requests
import streamlit as st
from streamlit.testing.v1 import AppTest


APP_PATH = Path(__file__).resolve().parents[1] / "src" / "app.py"
FAKE_SECRETS = {
    "NAVER_AD_API_KEY": "ad-key",
    "NAVER_AD_SECRET_KEY": "ad-secret",
    "NAVER_CUSTOMER_ID": "123",
    "NAVER_CLIENT_ID": "search-id",
    "NAVER_CLIENT_SECRET": "search-secret",
}


class FakeResponse:
    def __init__(self, payload=None, *, content=None, status_code=200, text=""):
        self._payload = payload or {}
        self.content = content
        self.status_code = status_code
        self.ok = status_code < 400
        self.text = text
        self.reason = text
        self.headers = {}

    def json(self):
        return self._payload


def install_http_fakes(monkeypatch):
    def fake_session_get(_session, url, **kwargs):
        if "keywordstool" in url:
            hint = kwargs["params"]["hintKeywords"]
            if hint == "미국주식":
                rows = [
                    {
                        "relKeyword": f"미국주식{i}",
                        "monthlyPcQcCnt": 100 + i,
                        "monthlyMobileQcCnt": 200 + i,
                        "compIdx": "LOW",
                    }
                    for i in range(12)
                ]
            else:
                rows = [
                    {
                        "relKeyword": hint,
                        "monthlyPcQcCnt": 100,
                        "monthlyMobileQcCnt": 200,
                        "compIdx": "LOW",
                    }
                ]
            return FakeResponse({"keywordList": rows})
        if "blog" in url:
            return FakeResponse({"total": 120, "items": []})
        raise AssertionError(f"unexpected Naver URL: {url}")

    def fake_google_get(url, **_kwargs):
        assert "trends.google.com/trending/rss" in url
        items = "".join(
            f"<item><title>급상승{i}</title><ht:approx_traffic>{i + 1},000+</ht:approx_traffic>"
            "<pubDate>Thu, 3 Sep 2026 00:00:00 -0700</pubDate></item>"
            for i in range(5)
        )
        xml = (
            '<?xml version="1.0"?><rss xmlns:ht="https://trends.google.com/trending/rss">'
            f"<channel>{items}</channel></rss>"
        ).encode("utf-8")
        return FakeResponse(content=xml)

    monkeypatch.setattr(requests.Session, "get", fake_session_get)
    monkeypatch.setattr(requests, "get", fake_google_get)


def ready_app(monkeypatch):
    install_http_fakes(monkeypatch)
    st.cache_resource.clear()
    st.cache_data.clear()
    app = AppTest.from_file(APP_PATH, default_timeout=20)
    app.secrets = dict(FAKE_SECRETS)
    return app.run()


def test_streamlit_app_starts_and_disables_queries_without_credentials(monkeypatch):
    for key in FAKE_SECRETS:
        monkeypatch.delenv(key, raising=False)
    st.cache_resource.clear()
    st.cache_data.clear()
    app = AppTest.from_file(APP_PATH, default_timeout=20).run()

    assert not app.exception
    assert app.title[0].value == "🧭 네이버 블로그 주제 기회 탐색기"
    assert app.button[0].label == "키워드 분석 시작"
    assert app.button[0].disabled is True


def test_streamlit_modes_render_without_triggering_network_calls():
    app = AppTest.from_file(APP_PATH, default_timeout=20).run()

    app.selectbox[0].set_value("모드 B: 한국 급상승 주제").run()
    assert not app.exception
    assert app.header[0].value == "📈 한국 급상승 주제 분석"
    assert app.button[0].label == "급상승 주제 분석 시작"

    app.selectbox[0].set_value("모드 C: 니치 마켓 탐색").run()
    assert not app.exception
    assert app.header[0].value == "🎯 니치 마켓 탐색"
    assert app.button[0].label == "니치 마켓 탐색 시작"


def test_basic_mode_completes_with_verified_mock_data(monkeypatch):
    app = ready_app(monkeypatch)

    app.button[0].click().run(timeout=20)

    assert not app.exception
    assert app.status[0].state == "complete"
    assert app.metric[0].value == "13"
    assert app.download_button[0].label == "결과 CSV 다운로드"

    app.run()
    assert app.metric[0].value == "13"
    assert app.download_button[0].label == "결과 CSV 다운로드"


def test_expired_saved_result_is_not_rendered_as_current(monkeypatch):
    app = ready_app(monkeypatch)
    app.button[0].click().run(timeout=20)

    saved = app.session_state["analysis_results"]
    saved["모드 A: 기초 키워드 분석"]["saved_at"] = "2000-01-01T00:00:00+00:00"
    app.session_state["analysis_results"] = saved
    app.run()

    assert not app.exception
    assert not app.metric
    assert any("유효시간이 지났습니다" in item.value for item in app.warning)


def test_trending_mode_completes_with_google_and_naver_mock_data(monkeypatch):
    app = ready_app(monkeypatch)
    app.selectbox[0].set_value("모드 B: 한국 급상승 주제").run()

    app.button[0].click().run(timeout=20)

    assert not app.exception
    assert app.status[0].state == "complete"
    assert app.dataframe[0].value["급상승 주제"].tolist() == [
        "급상승0",
        "급상승1",
        "급상승2",
        "급상승3",
        "급상승4",
    ]
    assert app.metric[0].value == "15"

    app.run()
    assert app.dataframe[0].value["급상승 주제"].tolist() == [
        "급상승0",
        "급상승1",
        "급상승2",
        "급상승3",
        "급상승4",
    ]
    assert any("Google Trends RSS 조회 시각" in item.value for item in app.caption)


def test_niche_mode_limits_and_completes_with_mock_data(monkeypatch):
    app = ready_app(monkeypatch)
    app.selectbox[0].set_value("모드 C: 니치 마켓 탐색").run()

    app.button[0].click().run(timeout=20)

    assert not app.exception
    assert app.status[0].state == "complete"
    assert app.metric[0].value == "12"
    assert app.download_button[0].label == "결과 CSV 다운로드"


def test_row_specific_bad_request_does_not_abort_later_keywords(monkeypatch):
    calls = []

    def fake_session_get(_session, url, **kwargs):
        calls.append(url)
        if "keywordstool" in url:
            hint = kwargs["params"]["hintKeywords"]
            if hint == "광주맛집":
                return FakeResponse(status_code=400, text="bad keyword")
            return FakeResponse(
                {
                    "keywordList": [
                        {
                            "relKeyword": hint,
                            "monthlyPcQcCnt": 100,
                            "monthlyMobileQcCnt": 200,
                        }
                    ]
                }
            )
        if "blog" in url:
            return FakeResponse({"total": 120, "items": []})
        raise AssertionError(f"unexpected URL: {url}")

    monkeypatch.setattr(requests.Session, "get", fake_session_get)
    st.cache_data.clear()
    app = AppTest.from_file(APP_PATH, default_timeout=20)
    app.secrets = dict(FAKE_SECRETS)
    app.run().button[0].click().run(timeout=20)

    assert not app.exception
    assert app.status[0].state == "complete"
    assert app.metric[0].value == "12"
    assert sum("keywordstool" in url for url in calls) == 13


def test_authentication_failure_opens_circuit_after_one_keyword(monkeypatch):
    calls = []

    def fake_session_get(_session, url, **_kwargs):
        calls.append(url)
        return FakeResponse(status_code=401, text="invalid credential")

    monkeypatch.setattr(requests.Session, "get", fake_session_get)
    st.cache_data.clear()
    app = AppTest.from_file(APP_PATH, default_timeout=20)
    app.secrets = dict(FAKE_SECRETS)
    app.run().button[0].click().run(timeout=20)

    assert not app.exception
    assert app.status[0].state == "error"
    assert len(calls) == 1
    assert "네이버 데이터" in app.error[0].value


def test_two_consecutive_server_failures_open_circuit(monkeypatch):
    calls = []

    def fake_session_get(_session, url, **_kwargs):
        calls.append(url)
        return FakeResponse(status_code=503, text="temporarily unavailable")

    monkeypatch.setattr(requests.Session, "get", fake_session_get)
    st.cache_data.clear()
    app = AppTest.from_file(APP_PATH, default_timeout=20)
    app.secrets = dict(FAKE_SECRETS)
    app.run().button[0].click().run(timeout=20)

    assert not app.exception
    assert app.status[0].state == "error"
    assert len(calls) == 4  # one bounded retry for each of two keywords
