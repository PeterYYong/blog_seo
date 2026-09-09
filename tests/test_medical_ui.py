"""Streamlit user-flow tests with explicit synthetic metadata, no live APIs."""

from copy import deepcopy
from datetime import date
from pathlib import Path

import pytest
from streamlit.testing.v1 import AppTest

from medical_research import ui
from medical_research.discovery import SearchConfig, explore
from medical_research.pubmed import Article, PubMedError, SearchResult


APP = Path(__file__).resolve().parents[1] / "medical_ai_app.py"


class FixtureClient:
    def search(self, query, limit=0, sort="pub date"):
        return SearchResult(query, 12, ["99999999"] if limit else [], query, [], "2026-09-09T00:00:00+00:00")

    def fetch(self, pmids):
        return [Article("99999999", "Synthetic UI fixture — not a real citation", "Fixture mentions external validation; no finding asserted.", "Fixture journal", "2026", "", ["Fixture Author"], [], [])]


@pytest.fixture(autouse=True)
def reset_caches():
    ui.cached_explore.clear()
    ui._run_limiter.clear()
    yield
    ui.cached_explore.clear()
    ui._run_limiter.clear()


@pytest.fixture
def result():
    return explore(SearchConfig(lens_ids=("external_validation", "calibration", "domain_shift", "fairness")), client=FixtureClient(), as_of=date(2026, 9, 9))


def test_initial_page_requires_no_secret_or_network(monkeypatch):
    monkeypatch.setattr(ui, "explore", lambda *a, **k: pytest.fail("No auto network on page load"))
    app = AppTest.from_file(str(APP), default_timeout=20).run()
    assert not app.exception
    assert "문헌" in app.title[0].value
    assert app.button(key="medical_search").label == "문헌 근거로 주제 탐색"


def test_result_renders_repeated_paper_across_lenses_and_tabs(monkeypatch, result):
    monkeypatch.setattr(ui, "explore", lambda *a, **k: deepcopy(result))
    app = AppTest.from_file(str(APP), default_timeout=20).run()
    app.button(key="medical_search").click().run()
    assert not app.exception
    assert any(metric.value == "12" for metric in app.metric)
    assert len(app.tabs) == 4
    assert app.session_state["medical_result"]["base_periods"]["recent"]["count"] == 12
    assert any("PubMed" in item.value for item in app.caption)


def test_no_lenses_and_korean_custom_query_do_not_search(monkeypatch):
    monkeypatch.setattr(ui, "explore", lambda *a, **k: pytest.fail("Invalid input should not search"))
    app = AppTest.from_file(str(APP), default_timeout=20).run()
    app.multiselect(key="medical_lenses").set_value([]).run()
    app.button(key="medical_search").click().run()
    assert any("하나 이상" in item.value for item in app.warning)
    app.multiselect(key="medical_lenses").set_value(["external_validation"]).run()
    app.text_area(key="medical_clinical").set_value("폐암").run()
    app.button(key="medical_search").click().run()
    assert any("영어" in item.value for item in app.warning)
    assert not app.exception


def test_changed_inputs_mark_result_stale(monkeypatch, result):
    monkeypatch.setattr(ui, "explore", lambda *a, **k: deepcopy(result))
    app = AppTest.from_file(str(APP), default_timeout=20).run()
    app.button(key="medical_search").click().run()
    app.selectbox(key="medical_preset").set_value("lung_cancer").run()
    assert any("입력 조건이 변경" in item.value for item in app.info)
    assert app.session_state["medical_result"]["config"]["preset"] == "copd_ct"


def test_failed_response_is_not_cached(monkeypatch, result):
    calls = []
    failed = deepcopy(result)
    failed["errors"] = ["Fixture source outage"]
    def fetch(*args, **kwargs):
        calls.append(1)
        return deepcopy(failed)
    monkeypatch.setattr(ui, "explore", fetch)
    import json
    signature = json.dumps(result["config"])
    for _ in range(2):
        with pytest.raises(ui._UncachedResult):
            ui.cached_explore(signature, "2026-09-09")
    assert len(calls) == 2


def test_total_failure_keeps_previous_success(monkeypatch, result):
    from medical_research import ui as module
    responses = [deepcopy(result)]
    class BrokenClient:
        def search(self, *args, **kwargs):
            raise PubMedError("Fixture source outage")
    failed = explore(SearchConfig(preset="lung_cancer", lens_ids=("external_validation",)), client=BrokenClient(), as_of=date(2026, 9, 9))
    responses.append(failed)
    monkeypatch.setattr(module, "explore", lambda *a, **k: responses.pop(0))
    app = AppTest.from_file(str(APP), default_timeout=20).run()
    app.button(key="medical_search").click().run()
    app.selectbox(key="medical_preset").set_value("lung_cancer").run()
    app.session_state["medical_last_search"] = 0
    app.button(key="medical_search").click().run()
    assert not app.exception
    assert any("마지막으로 확인한 결과" in item.value for item in app.error)
    assert app.session_state["medical_result"]["config"]["preset"] == "copd_ct"


def test_no_result_outage_has_failure_status_and_missing_counts(monkeypatch):
    class BrokenClient:
        def search(self, *args, **kwargs):
            raise PubMedError("Fixture source outage")
    failed = explore(SearchConfig(), client=BrokenClient(), as_of=date(2026, 9, 9))
    monkeypatch.setattr(ui, "explore", lambda *a, **k: deepcopy(failed))
    app = AppTest.from_file(str(APP), default_timeout=20).run()
    app.button(key="medical_search").click().run()
    assert not app.exception
    assert any(status.label == "문헌 조회 실패" for status in app.status)
    assert app.metric[0].value == "미확인"
