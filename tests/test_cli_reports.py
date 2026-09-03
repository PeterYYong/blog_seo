from datetime import datetime, timezone

import pytest

from src import main as keyword_cli
from src import niche_hunter, trend_hunter
from src.seo_sources import SourceError, SourceFailureCircuitBreaker


def censored_keyword_record(keyword="검증키워드"):
    return {
        "Keyword": keyword,
        "Monthly_Search_Volume": 105,
        "Search_Volume_Censored": True,
        "Search_Volume_PC_Raw": "< 10",
        "Search_Volume_Mobile_Raw": "101",
        "Total_Docs": 50,
        "Blog_Doc_Count": 50,
        "SmartBlock_Type": "공식 API로 확인 불가",
    }


def assert_censoring_disclosure(report):
    content = report.read_text(encoding="utf-8")
    assert "Search_Volume_Censored" in content
    assert "Search_Volume_PC_Raw" in content
    assert "Search_Volume_Mobile_Raw" in content
    assert "< 10" in content
    assert "midpoint" in content


@pytest.mark.parametrize("status_code", [401, 403, 404, 405, 429])
def test_source_failure_guard_stops_terminal_status_immediately(status_code):
    guard = SourceFailureCircuitBreaker()

    assert guard.should_abort(SourceError("naver", "terminal", status_code)) is True


@pytest.mark.parametrize(
    "message",
    [
        "missing credentials: key",
        "invalid JSON response",
        "unexpected JSON response shape",
        "missing or invalid response field: total",
    ],
)
def test_source_failure_guard_stops_terminal_contract_failure(message):
    guard = SourceFailureCircuitBreaker()

    assert guard.should_abort(SourceError("naver", message)) is True


@pytest.mark.parametrize(
    "error",
    [
        SourceError("naver", "server unavailable", 503),
        SourceError("naver", "request timed out"),
    ],
)
def test_source_failure_guard_stops_second_consecutive_transient_failure(error):
    guard = SourceFailureCircuitBreaker()

    assert guard.should_abort(error) is False
    assert guard.should_abort(error) is True


def test_source_failure_guard_resets_after_success():
    guard = SourceFailureCircuitBreaker()
    error = SourceError("naver", "connection failed")

    assert guard.should_abort(error) is False
    guard.record_success()
    assert guard.should_abort(error) is False


def test_source_failure_guard_stops_on_invalid_success_schema():
    guard = SourceFailureCircuitBreaker()

    error = SourceError("naver_search_ads", "missing or invalid monthly search count")

    assert guard.should_abort(error) is True


def test_keyword_cli_report_retains_search_ads_raw_values(monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(
        keyword_cli.sys,
        "argv",
        ["main.py", "--seed", "검증키워드", "--limit", "1"],
    )
    monkeypatch.setattr(
        keyword_cli,
        "expand_keyword",
        lambda _seed: (["검증키워드"], []),
    )
    monkeypatch.setattr(keyword_cli, "RealDataFetcher", object)
    monkeypatch.setattr(
        keyword_cli,
        "fetch_keyword_data",
        lambda _keyword, fetcher=None: censored_keyword_record(),
    )

    assert keyword_cli.main() == 0

    reports = list((tmp_path / "reports").glob("result_REAL_*.md"))
    assert len(reports) == 1
    assert_censoring_disclosure(reports[0])


def test_niche_cli_report_retains_search_ads_raw_values(monkeypatch, tmp_path):
    class FakeFetcher:
        def get_related_keywords(self, _seed):
            return [
                {
                    "keyword": "검증키워드",
                    "volume": 105,
                    "volume_censored": True,
                    "pc_raw": "< 10",
                    "mobile_raw": "101",
                }
            ]

        def get_doc_count(self, _keyword):
            return 50

    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(
        niche_hunter.sys,
        "argv",
        ["niche_hunter.py", "--seed", "검증키워드", "--limit", "1"],
    )
    monkeypatch.setattr(niche_hunter, "RealDataFetcher", FakeFetcher)

    assert niche_hunter.main() == 0

    reports = list((tmp_path / "reports").glob("niche_report_*.md"))
    assert len(reports) == 1
    assert_censoring_disclosure(reports[0])


def test_trend_cli_report_retains_search_ads_raw_values(monkeypatch, tmp_path):
    snapshot = trend_hunter.TrendSnapshot(
        keywords=("검증키워드",),
        source=trend_hunter.GOOGLE_TRENDS_SOURCE,
        source_url=trend_hunter.GOOGLE_TRENDS_KR_RSS_URL,
        retrieved_at=datetime(2026, 9, 3, tzinfo=timezone.utc),
    )
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(
        trend_hunter,
        "fetch_trending_snapshot",
        lambda limit=5: snapshot,
    )
    monkeypatch.setattr(
        trend_hunter,
        "_ordered_unique_expansions",
        lambda _trends: ["검증키워드"],
    )
    monkeypatch.setattr(trend_hunter, "RealDataFetcher", object)
    monkeypatch.setattr(
        trend_hunter,
        "fetch_keyword_data",
        lambda _keyword, fetcher=None: censored_keyword_record(),
    )

    assert trend_hunter.main([]) == 0

    reports = list((tmp_path / "reports").glob("DEEP_DIVE_*.md"))
    assert len(reports) == 1
    assert_censoring_disclosure(reports[0])


def test_keyword_cli_stops_after_two_consecutive_server_failures(
    monkeypatch,
    tmp_path,
    capsys,
):
    calls = []

    def fail_keyword(keyword, fetcher=None):
        calls.append(keyword)
        raise SourceError("naver_blog_search", "unavailable", 503)

    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(
        keyword_cli.sys,
        "argv",
        ["main.py", "--seed", "시드", "--limit", "4"],
    )
    monkeypatch.setattr(
        keyword_cli,
        "expand_keyword",
        lambda _seed: (["하나", "둘", "셋", "넷"], []),
    )
    monkeypatch.setattr(keyword_cli, "RealDataFetcher", object)
    monkeypatch.setattr(keyword_cli, "fetch_keyword_data", fail_keyword)

    assert keyword_cli.main() == 1

    assert calls == ["하나", "둘"]
    assert "남은 2개 키워드 조회를 중단" in capsys.readouterr().out


def test_niche_cli_stops_after_two_consecutive_server_failures(
    monkeypatch,
    tmp_path,
    capsys,
):
    class FailingFetcher:
        calls = []

        def get_related_keywords(self, _seed):
            return [
                {
                    "keyword": keyword,
                    "volume": 105,
                    "volume_censored": False,
                    "pc_raw": "50",
                    "mobile_raw": "55",
                }
                for keyword in ("하나", "둘", "셋", "넷")
            ]

        def get_doc_count(self, keyword):
            self.calls.append(keyword)
            raise SourceError("naver_blog_search", "unavailable", 503)

    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(
        niche_hunter.sys,
        "argv",
        ["niche_hunter.py", "--seed", "시드", "--limit", "4"],
    )
    monkeypatch.setattr(niche_hunter, "RealDataFetcher", FailingFetcher)

    assert niche_hunter.main() == 1

    assert FailingFetcher.calls == ["하나", "둘"]
    assert "남은 2개 키워드 조회를 중단" in capsys.readouterr().out


def test_trend_cli_stops_after_two_consecutive_network_failures(
    monkeypatch,
    tmp_path,
    capsys,
):
    snapshot = trend_hunter.TrendSnapshot(
        keywords=("시드",),
        source=trend_hunter.GOOGLE_TRENDS_SOURCE,
        source_url=trend_hunter.GOOGLE_TRENDS_KR_RSS_URL,
        retrieved_at=datetime(2026, 9, 3, tzinfo=timezone.utc),
    )
    calls = []

    def fail_keyword(keyword, fetcher=None):
        calls.append(keyword)
        raise SourceError("naver_search_ads", "connection failed")

    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(
        trend_hunter,
        "fetch_trending_snapshot",
        lambda limit=5: snapshot,
    )
    monkeypatch.setattr(
        trend_hunter,
        "_ordered_unique_expansions",
        lambda _trends: ["하나", "둘", "셋", "넷"],
    )
    monkeypatch.setattr(trend_hunter, "RealDataFetcher", object)
    monkeypatch.setattr(trend_hunter, "fetch_keyword_data", fail_keyword)

    assert trend_hunter.main([]) == 1

    assert calls == ["하나", "둘"]
    assert "남은 2개 키워드 조회를 중단" in capsys.readouterr().out
