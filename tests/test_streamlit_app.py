from datetime import date, timedelta
from pathlib import Path

import requests
import streamlit as st
from streamlit.testing.v1 import AppTest


APP_PATH = Path(__file__).resolve().parents[1] / "src" / "app.py"
TEST_APP_PASSWORD = "test-only-password-at-least-20-chars"
FOUR_DIGIT_PIN = "0123"
FAKE_SECRETS = {
    "APP_PASSWORD": TEST_APP_PASSWORD,
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


def datalab_points(
    payload,
    *,
    previous_ratio=10,
    recent_ratio=20,
    lag_days=0,
):
    """Build exactly one complete 28-day + 7-day DataLab window."""

    latest = date.fromisoformat(payload["endDate"]) - timedelta(days=lag_days)
    start = latest - timedelta(days=34)
    ratios = [previous_ratio] * 28 + [recent_ratio] * 7
    return [
        {
            "period": (start + timedelta(days=index)).isoformat(),
            "ratio": ratio,
        }
        for index, ratio in enumerate(ratios)
    ]


def successful_datalab_response(payload, **point_options):
    points = datalab_points(payload, **point_options)
    return FakeResponse(
        {
            "results": [
                {"title": group["groupName"], "data": points}
                for group in payload["keywordGroups"]
            ]
        }
    )


def install_http_fakes(
    monkeypatch,
    *,
    failed_search_ads_hints=None,
    empty_search_ads_hints=None,
):
    failed_search_ads_hints = set(failed_search_ads_hints or ())
    empty_search_ads_hints = set(empty_search_ads_hints or ())

    def fake_session_get(_session, url, **kwargs):
        if "keywordstool" in url:
            hint = kwargs["params"]["hintKeywords"]
            if hint in failed_search_ads_hints:
                return FakeResponse(status_code=400, text="bad keyword")
            if hint in empty_search_ads_hints:
                return FakeResponse({"keywordList": []})
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
                        "relKeyword": keyword,
                        "monthlyPcQcCnt": pc,
                        "monthlyMobileQcCnt": mobile,
                        "compIdx": "LOW",
                    }
                    for keyword, pc, mobile in [
                        (hint, 100, 200),
                        (f"{hint}예약", 80, 160),
                        (f"{hint}후기", 60, 120),
                        (f"{hint}추천", 50, 100),
                        (f"{hint}가격", 40, 80),
                        (f"{hint}근처", 30, 60),
                        (f"{hint}당일", 20, 40),
                        (f"{hint}비교", 10, 20),
                        (f"{hint}초보", "<10", 50),
                    ]
                ]
            return FakeResponse({"keywordList": rows})
        if "blog" in url:
            return FakeResponse({"total": 120, "items": []})
        raise AssertionError(f"unexpected Naver URL: {url}")

    def fake_session_post(_session, url, **kwargs):
        assert "datalab" in url or "search-trend" in url
        payload = kwargs["json"]
        start = date.fromisoformat(payload["startDate"])
        points = [
            {
                "period": (start + timedelta(days=index)).isoformat(),
                "ratio": 10 if index < 49 else 20,
            }
            for index in range(56)
        ]
        return FakeResponse(
            {
                "results": [
                    {"title": group["groupName"], "data": points}
                    for group in payload["keywordGroups"]
                ]
            }
        )

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
    monkeypatch.setattr(requests.Session, "post", fake_session_post)
    monkeypatch.setattr(requests, "get", fake_google_get)


def button_with_label(app, label):
    return next(button for button in app.button if button.label == label)


def login(app):
    app.text_input[0].input(TEST_APP_PASSWORD)
    button_with_label(app, "로그인").click()
    return app.run()


def ready_app(monkeypatch):
    install_http_fakes(monkeypatch)
    st.cache_resource.clear()
    st.cache_data.clear()
    app = AppTest.from_file(APP_PATH, default_timeout=20)
    app.secrets = dict(FAKE_SECRETS)
    return login(app.run())


def test_streamlit_app_fails_closed_without_app_password(monkeypatch):
    monkeypatch.delenv("APP_PASSWORD", raising=False)
    st.cache_resource.clear()
    st.cache_data.clear()
    app = AppTest.from_file(APP_PATH, default_timeout=20).run()

    assert not app.exception
    assert app.title[0].value == "🔒 네이버 블로그 주제 기회 탐색기"
    assert any("잠겨 있습니다" in item.value for item in app.error)
    assert not any(button.label == "키워드 분석 시작" for button in app.button)


def test_streamlit_app_fails_closed_with_an_invalid_short_password():
    app = AppTest.from_file(APP_PATH, default_timeout=20)
    app.secrets = {"APP_PASSWORD": "too-short"}
    app.run()

    assert not app.exception
    assert any("숫자 4자리 PIN 또는 20~256자" in item.value for item in app.error)
    assert not any(button.label == "로그인" for button in app.button)


def test_streamlit_app_fails_closed_with_an_overlong_configured_password():
    app = AppTest.from_file(APP_PATH, default_timeout=20)
    app.secrets = {"APP_PASSWORD": "x" * 257}
    app.run()

    assert not app.exception
    assert any("숫자 4자리 PIN 또는 20~256자" in item.value for item in app.error)
    assert not any(button.label == "로그인" for button in app.button)


def test_streamlit_app_fails_closed_with_four_non_digit_characters():
    app = AppTest.from_file(APP_PATH, default_timeout=20)
    app.secrets = {"APP_PASSWORD": "abcd"}
    app.run()

    assert not app.exception
    assert any("숫자 4자리 PIN 또는 20~256자" in item.value for item in app.error)
    assert not any(button.label == "로그인" for button in app.button)


def test_four_digit_pin_rejects_wrong_value_then_unlocks():
    app = AppTest.from_file(APP_PATH, default_timeout=20)
    app.secrets = {**FAKE_SECRETS, "APP_PASSWORD": FOUR_DIGIT_PIN}
    app.run()

    app.text_input[0].input("9999")
    button_with_label(app, "로그인").click()
    app.run()
    assert any("올바르지 않습니다" in item.value for item in app.error)

    app.text_input[0].input(FOUR_DIGIT_PIN)
    button_with_label(app, "로그인").click()
    app.run()

    assert app.title[0].value == "🧭 네이버 블로그 주제 기회 탐색기"
    assert any("4자리 PIN 보호 사용 중" in item.value for item in app.warning)


def test_streamlit_password_login_rejects_wrong_value_then_unlocks():
    app = AppTest.from_file(APP_PATH, default_timeout=20)
    app.secrets = dict(FAKE_SECRETS)
    app.run()

    app.text_input[0].input("wrong-password")
    button_with_label(app, "로그인").click()
    app.run()
    assert any("올바르지 않습니다" in item.value for item in app.error)

    app.text_input[0].input(TEST_APP_PASSWORD)
    button_with_label(app, "로그인").click()
    app.run()
    assert app.title[0].value == "🧭 네이버 블로그 주제 기회 탐색기"
    assert any(button.label == "로그아웃" for button in app.button)


def test_password_rotation_invalidates_an_existing_authenticated_session():
    app = AppTest.from_file(APP_PATH, default_timeout=20)
    app.secrets = dict(FAKE_SECRETS)
    app = login(app.run())
    assert app.title[0].value == "🧭 네이버 블로그 주제 기회 탐색기"

    rotated_password = FOUR_DIGIT_PIN
    app.secrets = {**FAKE_SECRETS, "APP_PASSWORD": rotated_password}
    app.run()

    assert not app.exception
    assert app.title[0].value == "🔒 네이버 블로그 주제 기회 탐색기"
    assert any(button.label == "로그인" for button in app.button)


def test_authenticated_session_expires_after_twelve_hours():
    st.cache_resource.clear()
    st.cache_data.clear()
    app = AppTest.from_file(APP_PATH, default_timeout=20)
    app.secrets = {"APP_PASSWORD": TEST_APP_PASSWORD}
    app = login(app.run())

    authentication = dict(app.session_state["_app_authenticated"])
    authentication["authenticated_at"] -= 12 * 60 * 60 + 1
    app.session_state["_app_authenticated"] = authentication
    app.run()

    assert not app.exception
    assert app.title[0].value == "🔒 네이버 블로그 주제 기회 탐색기"
    assert any(button.label == "로그인" for button in app.button)
    assert not any(button.label == "로그아웃" for button in app.button)


def test_streamlit_app_starts_and_disables_queries_without_credentials(monkeypatch):
    for key in FAKE_SECRETS:
        monkeypatch.delenv(key, raising=False)
    st.cache_resource.clear()
    st.cache_data.clear()
    app = AppTest.from_file(APP_PATH, default_timeout=20)
    app.secrets = {"APP_PASSWORD": TEST_APP_PASSWORD}
    app = login(app.run())

    assert not app.exception
    assert app.title[0].value == "🧭 네이버 블로그 주제 기회 탐색기"
    analysis_button = button_with_label(app, "키워드 분석 시작")
    assert analysis_button.disabled is True


def test_streamlit_modes_render_without_triggering_network_calls():
    app = AppTest.from_file(APP_PATH, default_timeout=20)
    app.secrets = {"APP_PASSWORD": TEST_APP_PASSWORD}
    app = login(app.run())

    app.selectbox[0].set_value("모드 B: 한국 급상승 주제").run()
    assert not app.exception
    assert app.header[0].value == "📈 한국 급상승 주제 분석"
    assert button_with_label(app, "급상승 주제 분석 시작")

    app.selectbox[0].set_value("모드 C: 니치 마켓 탐색").run()
    assert not app.exception
    assert app.header[0].value == "🎯 니치 마켓 탐색"
    assert button_with_label(app, "니치 마켓 탐색 시작")


def test_basic_mode_completes_with_verified_mock_data(monkeypatch):
    app = ready_app(monkeypatch)

    button_with_label(app, "키워드 분석 시작").click().run(timeout=20)

    assert not app.exception
    assert app.status[0].state == "complete"
    assert app.metric[0].value == "9"
    assert app.metric[3].value == "8"
    assert len(app.get("link_button")) == 5
    assert all(
        item.label == "네이버 블로그 검색 결과 직접 확인"
        for item in app.get("link_button")
    )
    assert any("YouTube 관심 신호 미확인" in item.value for item in app.caption)
    assert {
        "월간 검색량 가능 범위",
        "PC 제공값",
        "모바일 제공값",
        "수요 대비 글 수 범위",
        "최근 검색 관심 변화",
    }.issubset(app.dataframe[0].value.columns)
    assert "효율 점수" not in app.dataframe[0].value.columns
    assert app.download_button[0].label == "결과 CSV 다운로드"
    assert any("‘수요 대비 글 수’가 1이면" in item.value for item in app.info)

    app.run()
    assert app.metric[0].value == "9"
    assert app.download_button[0].label == "결과 CSV 다운로드"


def test_basic_mode_explains_a_successful_empty_related_response(monkeypatch):
    install_http_fakes(monkeypatch, empty_search_ads_hints={"광주맛집"})
    st.cache_resource.clear()
    st.cache_data.clear()
    app = AppTest.from_file(APP_PATH, default_timeout=20)
    app.secrets = dict(FAKE_SECRETS)
    app = login(app.run())

    button_with_label(app, "키워드 분석 시작").click().run(timeout=20)

    assert not app.exception
    assert app.status[0].state == "error"
    assert any("연관어가 반환되지 않았습니다" in item.value for item in app.error)


def test_expired_saved_result_is_not_rendered_as_current(monkeypatch):
    app = ready_app(monkeypatch)
    button_with_label(app, "키워드 분석 시작").click().run(timeout=20)

    saved = app.session_state["analysis_results"]
    saved["모드 A: 기초 키워드 분석"]["saved_at"] = "2000-01-01T00:00:00+00:00"
    app.session_state["analysis_results"] = saved
    app.run()

    assert not app.exception
    assert not app.metric
    assert any("유효시간이 지났습니다" in item.value for item in app.warning)


def test_logout_clears_authentication_and_saved_analysis(monkeypatch):
    app = ready_app(monkeypatch)
    button_with_label(app, "키워드 분석 시작").click().run(timeout=20)
    assert app.metric

    button_with_label(app, "로그아웃").click().run()
    assert app.title[0].value == "🔒 네이버 블로그 주제 기회 탐색기"
    assert not app.metric

    app = login(app)
    assert app.title[0].value == "🧭 네이버 블로그 주제 기회 탐색기"
    assert not app.metric


def test_trending_mode_completes_with_google_and_naver_mock_data(monkeypatch):
    app = ready_app(monkeypatch)
    app.selectbox[0].set_value("모드 B: 한국 급상승 주제").run()

    button_with_label(app, "급상승 주제 분석 시작").click().run(timeout=20)

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
    assert len(app.get("link_button")) == 5

    app.run()
    assert app.dataframe[0].value["급상승 주제"].tolist() == [
        "급상승0",
        "급상승1",
        "급상승2",
        "급상승3",
        "급상승4",
    ]
    assert any("Google Trends RSS 조회 시각" in item.value for item in app.caption)


def test_trending_mode_marks_one_failed_topic_as_partial(monkeypatch):
    install_http_fakes(monkeypatch, failed_search_ads_hints={"급상승0"})
    st.cache_resource.clear()
    st.cache_data.clear()
    app = AppTest.from_file(APP_PATH, default_timeout=20)
    app.secrets = dict(FAKE_SECRETS)
    app = login(app.run())
    app.selectbox[0].set_value("모드 B: 한국 급상승 주제").run()

    button_with_label(app, "급상승 주제 분석 시작").click().run(timeout=20)

    assert not app.exception
    assert app.status[0].state == "error"
    assert app.metric[0].value == "12"
    stored = app.session_state["analysis_results"]["모드 B: 한국 급상승 주제"]
    assert stored["naver_evidence_complete"] is False
    assert any("임시 순서" in item.value for item in app.warning)


def test_trending_mode_deduplicates_nfkc_equivalent_keywords_across_topics(
    monkeypatch,
):
    variants = ["ＡＩ 주식", "ai주식", "AI\u3000주식", "Ai 주 식", "ａｉ주식"]
    search_ads_hints = []
    blog_queries = []

    def fake_session_get(_session, url, **kwargs):
        if "keywordstool" in url:
            hint = kwargs["params"]["hintKeywords"]
            search_ads_hints.append(hint)
            return FakeResponse(
                {
                    "keywordList": [
                        {
                            "relKeyword": variants[int(hint[-1])],
                            "monthlyPcQcCnt": 100,
                            "monthlyMobileQcCnt": 200,
                        }
                    ]
                }
            )
        if "blog" in url:
            blog_queries.append(kwargs["params"]["query"])
            return FakeResponse({"total": 120, "items": []})
        raise AssertionError(f"unexpected URL: {url}")

    def fake_session_post(_session, _url, **kwargs):
        return successful_datalab_response(kwargs["json"])

    def fake_google_get(url, **_kwargs):
        assert "trends.google.com/trending/rss" in url
        items = "".join(
            f"<item><title>급상승{i}</title><ht:approx_traffic>{i + 1},000+</ht:approx_traffic>"
            "<pubDate>Thu, 3 Sep 2026 00:00:00 -0700</pubDate></item>"
            for i in range(5)
        )
        return FakeResponse(
            content=(
                '<?xml version="1.0"?><rss xmlns:ht="https://trends.google.com/trending/rss">'
                f"<channel>{items}</channel></rss>"
            ).encode("utf-8")
        )

    monkeypatch.setattr(requests.Session, "get", fake_session_get)
    monkeypatch.setattr(requests.Session, "post", fake_session_post)
    monkeypatch.setattr(requests, "get", fake_google_get)
    st.cache_resource.clear()
    st.cache_data.clear()
    app = AppTest.from_file(APP_PATH, default_timeout=20)
    app.secrets = dict(FAKE_SECRETS)
    app = login(app.run())
    app.selectbox[0].set_value("모드 B: 한국 급상승 주제").run()

    button_with_label(app, "급상승 주제 분석 시작").click().run(timeout=20)

    assert not app.exception
    assert app.status[0].state == "complete"
    assert search_ads_hints == [f"급상승{i}" for i in range(5)]
    assert blog_queries == [variants[0]]
    assert app.metric[0].value == "1"
    stored = app.session_state["analysis_results"]["모드 B: 한국 급상승 주제"]
    assert stored["naver_evidence_complete"] is True
    assert stored["frame"]["Keyword"].tolist() == [variants[0]]
    assert stored["frame"]["Parent_Topic"].tolist() == ["급상승0"]


def test_niche_mode_limits_and_completes_with_mock_data(monkeypatch):
    app = ready_app(monkeypatch)
    app.selectbox[0].set_value("모드 C: 니치 마켓 탐색").run()

    button_with_label(app, "니치 마켓 탐색 시작").click().run(timeout=20)

    assert not app.exception
    assert app.status[0].state == "complete"
    assert app.metric[0].value == "12"
    assert app.download_button[0].label == "결과 CSV 다운로드"


def test_niche_mode_retains_double_censored_row_as_insufficient_data(monkeypatch):
    datalab_calls = []

    def fake_session_get(_session, url, **kwargs):
        if "keywordstool" in url:
            return FakeResponse(
                {
                    "keywordList": [
                        {
                            "relKeyword": "미국주식초소형",
                            "monthlyPcQcCnt": "<10",
                            "monthlyMobileQcCnt": "<10",
                        },
                        {
                            "relKeyword": "미국주식경계",
                            "monthlyPcQcCnt": "<10",
                            "monthlyMobileQcCnt": 45,
                        },
                    ]
                }
            )
        if "blog" in url:
            return FakeResponse({"total": 1, "items": []})
        raise AssertionError(f"unexpected URL: {url}")

    def fake_session_post(_session, _url, **kwargs):
        datalab_calls.append(kwargs["json"])
        return successful_datalab_response(kwargs["json"])

    monkeypatch.setattr(requests.Session, "get", fake_session_get)
    monkeypatch.setattr(requests.Session, "post", fake_session_post)
    st.cache_resource.clear()
    st.cache_data.clear()
    app = AppTest.from_file(APP_PATH, default_timeout=20)
    app.secrets = dict(FAKE_SECRETS)
    app = login(app.run())
    app.selectbox[0].set_value("모드 C: 니치 마켓 탐색").run()

    button_with_label(app, "니치 마켓 탐색 시작").click().run(timeout=20)

    assert not app.exception
    assert app.status[0].state == "complete"
    assert len(datalab_calls) == 1
    assert app.metric[0].value == "2"
    assert app.metric[1].value == "2"
    assert app.metric[3].value == "0"
    stored = app.session_state["analysis_results"]["모드 C: 니치 마켓 탐색"]
    rows = stored["frame"].set_index("Keyword")
    row = rows.loc["미국주식초소형"]
    assert row["Search_Volume_PC_Raw"] == "<10"
    assert row["Search_Volume_Mobile_Raw"] == "<10"
    assert row["Search_Volume_Range"] == "0~18"
    assert row["Assessment"] == "판단 자료 부족"
    assert not bool(row["_Candidate_Eligible"])
    assert row["Boundary_Sensitive_Label"] == "안정"
    boundary_row = rows.loc["미국주식경계"]
    assert bool(boundary_row["Boundary_Sensitive"])
    assert boundary_row["Boundary_Sensitive_Label"] == "범위에 따라 달라짐"


def test_later_datalab_batch_failure_preserves_earlier_batch_evidence(
    monkeypatch,
):
    datalab_batches = []

    def fake_session_get(_session, url, **_kwargs):
        if "keywordstool" in url:
            return FakeResponse(
                {
                    "keywordList": [
                        {
                            "relKeyword": f"배치후보{index}",
                            "monthlyPcQcCnt": 400 - index * 10,
                            "monthlyMobileQcCnt": 400 - index * 10,
                        }
                        for index in range(8)
                    ]
                }
            )
        if "blog" in url:
            return FakeResponse({"total": 120, "items": []})
        raise AssertionError(f"unexpected URL: {url}")

    def fake_session_post(_session, _url, **kwargs):
        payload = kwargs["json"]
        datalab_batches.append(
            tuple(group["groupName"] for group in payload["keywordGroups"])
        )
        if len(datalab_batches) == 2:
            return FakeResponse(status_code=400, text="bad second batch")
        return successful_datalab_response(payload)

    monkeypatch.setattr(requests.Session, "get", fake_session_get)
    monkeypatch.setattr(requests.Session, "post", fake_session_post)
    st.cache_resource.clear()
    st.cache_data.clear()
    app = AppTest.from_file(APP_PATH, default_timeout=20)
    app.secrets = dict(FAKE_SECRETS)
    app = login(app.run())

    button_with_label(app, "키워드 분석 시작").click().run(timeout=20)

    assert not app.exception
    assert app.status[0].state == "error"
    assert [len(batch) for batch in datalab_batches] == [5, 3]
    stored = app.session_state["analysis_results"]["모드 A: 기초 키워드 분석"]
    assert stored["naver_evidence_complete"] is False
    frame = stored["frame"].set_index("Keyword")
    successful_keywords = set(datalab_batches[0])
    failed_keywords = set(datalab_batches[1])
    assert set(frame.index) == successful_keywords | failed_keywords
    assert set(frame.loc[list(successful_keywords), "Trend_Direction"]) == {"rising"}
    assert set(frame.loc[list(successful_keywords), "Trend_Change_Display"]) == {
        "+100.0%"
    }
    assert set(frame.loc[list(failed_keywords), "Trend_Direction"]) == {"unknown"}
    assert set(frame.loc[list(failed_keywords), "Trend_Change_Display"]) == {
        "판단 보류"
    }
    failed_trend_keywords = {
        failure["키워드"]
        for failure in stored["failures"]
        if failure["출처"] == "naver_datalab"
    }
    assert failed_trend_keywords == failed_keywords


def test_stale_complete_datalab_window_is_displayed_as_pending(monkeypatch):
    def fake_session_get(_session, url, **_kwargs):
        if "keywordstool" in url:
            return FakeResponse(
                {
                    "keywordList": [
                        {
                            "relKeyword": "오래된추세후보",
                            "monthlyPcQcCnt": 100,
                            "monthlyMobileQcCnt": 200,
                        }
                    ]
                }
            )
        if "blog" in url:
            return FakeResponse({"total": 120, "items": []})
        raise AssertionError(f"unexpected URL: {url}")

    def fake_session_post(_session, _url, **kwargs):
        return successful_datalab_response(kwargs["json"], lag_days=3)

    monkeypatch.setattr(requests.Session, "get", fake_session_get)
    monkeypatch.setattr(requests.Session, "post", fake_session_post)
    st.cache_resource.clear()
    st.cache_data.clear()
    app = AppTest.from_file(APP_PATH, default_timeout=20)
    app.secrets = dict(FAKE_SECRETS)
    app = login(app.run())

    button_with_label(app, "키워드 분석 시작").click().run(timeout=20)

    assert not app.exception
    assert app.status[0].state == "error"
    stored = app.session_state["analysis_results"]["모드 A: 기초 키워드 분석"]
    assert stored["naver_evidence_complete"] is False
    row = stored["frame"].iloc[0]
    assert row["Trend_Object"].recent_observations == 7
    assert row["Trend_Object"].previous_observations == 28
    assert row["Trend_Object"].stale is True
    assert row["Trend_Object"].lag_days == 3
    assert row["Trend_Object"].complete is False
    assert row["Trend_Direction"] == "unknown"
    assert row["Trend_Change_Percent"] == 100
    assert row["Trend_Change_Display"] == "판단 보류"
    assert row["Opportunity_Object"].evidence_completeness == "partial"
    assert any("3일 오래되어" in failure["사유"] for failure in stored["failures"])
    assert "100.0%" not in row["Why_Now"]
    assert not any("+100.0%" in item.value for item in app.markdown)


def test_near_rising_threshold_stays_stable_without_rounding_up(monkeypatch):
    def fake_session_get(_session, url, **_kwargs):
        if "keywordstool" in url:
            return FakeResponse(
                {
                    "keywordList": [
                        {
                            "relKeyword": "경계추세후보",
                            "monthlyPcQcCnt": 100,
                            "monthlyMobileQcCnt": 200,
                        }
                    ]
                }
            )
        if "blog" in url:
            return FakeResponse({"total": 120, "items": []})
        raise AssertionError(f"unexpected URL: {url}")

    def fake_session_post(_session, _url, **kwargs):
        return successful_datalab_response(
            kwargs["json"],
            previous_ratio=10,
            recent_ratio=10.996,
        )

    monkeypatch.setattr(requests.Session, "get", fake_session_get)
    monkeypatch.setattr(requests.Session, "post", fake_session_post)
    st.cache_resource.clear()
    st.cache_data.clear()
    app = AppTest.from_file(APP_PATH, default_timeout=20)
    app.secrets = dict(FAKE_SECRETS)
    app = login(app.run())

    button_with_label(app, "키워드 분석 시작").click().run(timeout=20)

    assert not app.exception
    assert app.status[0].state == "complete"
    stored = app.session_state["analysis_results"]["모드 A: 기초 키워드 분석"]
    row = stored["frame"].iloc[0]
    assert round(row["Trend_Change_Percent"], 2) == 9.96
    assert row["Trend_Direction"] == "stable"
    assert row["Trend_Direction_Label"] == "→ 비슷함"
    assert row["Trend_Change_Display"] == "+10% 미만"
    assert row["Strategy"] == "recent_stable"
    assert row["Strategy_Label"] == "최근 안정형 검토"
    assert "10.0% 상승" not in row["Why_Now"]
    assert not any("+10.0%" in item.value for item in app.markdown)


def test_row_specific_blog_bad_request_does_not_abort_later_candidates(monkeypatch):
    blog_queries = []

    def fake_session_get(_session, url, **kwargs):
        if "keywordstool" in url:
            return FakeResponse(
                {
                    "keywordList": [
                        {
                            "relKeyword": keyword,
                            "monthlyPcQcCnt": pc,
                            "monthlyMobileQcCnt": mobile,
                        }
                        for keyword, pc, mobile in [
                            ("정상후보1", 100, 200),
                            ("실패후보", 80, 160),
                            ("정상후보2", 60, 120),
                        ]
                    ]
                }
            )
        if "blog" in url:
            query = kwargs["params"]["query"]
            blog_queries.append(query)
            if query == "실패후보":
                return FakeResponse(status_code=400, text="bad keyword")
            return FakeResponse({"total": 120, "items": []})
        raise AssertionError(f"unexpected URL: {url}")

    def fake_session_post(_session, _url, **kwargs):
        payload = kwargs["json"]
        start = date.fromisoformat(payload["startDate"])
        points = [
            {
                "period": (start + timedelta(days=index)).isoformat(),
                "ratio": 10 if index < 49 else 20,
            }
            for index in range(56)
        ]
        return FakeResponse(
            {
                "results": [
                    {"title": group["groupName"], "data": points}
                    for group in payload["keywordGroups"]
                ]
            }
        )

    monkeypatch.setattr(requests.Session, "get", fake_session_get)
    monkeypatch.setattr(requests.Session, "post", fake_session_post)
    st.cache_data.clear()
    app = AppTest.from_file(APP_PATH, default_timeout=20)
    app.secrets = dict(FAKE_SECRETS)
    app = login(app.run())
    button_with_label(app, "키워드 분석 시작").click().run(timeout=20)

    assert not app.exception
    assert app.status[0].state == "error"
    assert app.metric[0].value == "2"
    assert blog_queries == ["정상후보1", "실패후보", "정상후보2"]
    assert any("임시 순서" in item.value for item in app.warning)


def test_authentication_failure_opens_circuit_after_one_keyword(monkeypatch):
    calls = []

    def fake_session_get(_session, url, **_kwargs):
        calls.append(url)
        return FakeResponse(status_code=401, text="invalid credential")

    monkeypatch.setattr(requests.Session, "get", fake_session_get)
    st.cache_data.clear()
    app = AppTest.from_file(APP_PATH, default_timeout=20)
    app.secrets = dict(FAKE_SECRETS)
    app = login(app.run())
    button_with_label(app, "키워드 분석 시작").click().run(timeout=20)

    assert not app.exception
    assert app.status[0].state == "error"
    assert len(calls) == 1
    assert "Search Ads 연관어" in app.error[0].value


def test_two_consecutive_server_failures_open_circuit(monkeypatch):
    calls = []

    def fake_session_get(_session, url, **_kwargs):
        calls.append(url)
        if "keywordstool" in url:
            return FakeResponse(
                {
                    "keywordList": [
                        {
                            "relKeyword": f"후보{index}",
                            "monthlyPcQcCnt": 100 - index,
                            "monthlyMobileQcCnt": 200 - index,
                        }
                        for index in range(6)
                    ]
                }
            )
        if "blog" in url:
            return FakeResponse(status_code=503, text="temporarily unavailable")
        raise AssertionError(f"unexpected URL: {url}")

    monkeypatch.setattr(requests.Session, "get", fake_session_get)
    st.cache_data.clear()
    app = AppTest.from_file(APP_PATH, default_timeout=20)
    app.secrets = dict(FAKE_SECRETS)
    app = login(app.run())
    button_with_label(app, "키워드 분석 시작").click().run(timeout=20)

    assert not app.exception
    assert app.status[0].state == "error"
    assert sum("keywordstool" in url for url in calls) == 1
    assert sum("blog" in url for url in calls) == 4
