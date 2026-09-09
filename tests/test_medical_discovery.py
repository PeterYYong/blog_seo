import csv
from datetime import date
import io
import json
from types import SimpleNamespace

import pytest

from medical_research.discovery import (
    AI_METHODS,
    LENSES,
    PRESETS,
    SearchConfig,
    build_base_query,
    explore,
    feasibility,
    keyword_mentions,
)
from medical_research.exports import to_bibtex, to_csv, to_json, to_markdown
from medical_research.pubmed import PubMedError


class FakeClient:
    def __init__(self, counter=None, fetch_error=False, title="External validation of a COPD model"):
        self.calls = []
        self.counter = counter or (lambda query: 12)
        self.fetch_error = fetch_error
        self.title = title
        self.fetch_calls = []

    def search(self, query, limit=0, sort="pub date"):
        self.calls.append((query, limit, sort))
        count = self.counter(query)
        return SimpleNamespace(
            query=query, count=count, pmids=["12345"] if limit and count else [],
            translation="TRANSLATED " + query, warnings=["test warning"],
            retrieved_at="2026-09-09T00:00:00+00:00",
        )

    def fetch(self, pmids):
        self.fetch_calls.append(pmids)
        if self.fetch_error:
            raise PubMedError("metadata endpoint unavailable")
        return [SimpleNamespace(
            pmid="12345", title=self.title,
            abstract="No external validation was performed. Calibration requires future work.",
            journal="Source Journal", year="2026", doi="10.1234/test_doi",
            authors=["Jane A Smith", "Data {Group}"], publication_types=["Journal Article"],
            mesh_terms=["Pulmonary Disease, Chronic Obstructive"],
            publication_date="2026 Sep 1", retracted=False,
        )]


def _explore(client=None, **config):
    config.setdefault("lens_ids", ("external_validation",))
    return explore(SearchConfig(**config), client=client or FakeClient(), as_of=date(2026, 9, 9))


def test_complete_calendar_windows_current_ytd_and_sample_are_distinct():
    result = _explore()
    assert result["windows"]["prior"]["years"] == [2020, 2021, 2022]
    assert result["windows"]["recent"]["years"] == [2023, 2024, 2025]
    assert [row["year"] for row in result["yearly_counts"]] == list(range(2020, 2026))
    assert '"2026/01/01"' in result["base_periods"]["current_ytd"]["query"]
    assert '"2026/09/09"' in result["base_periods"]["current_ytd"]["query"]
    lens = result["lenses"][0]
    assert '"2025/12/31"' in lens["recent_search"]["query"]
    assert '"2026/09/09"' in lens["sample_query"]
    assert '"2023/01/01"' in lens["sample_query"]
    assert '"2026/12/31"' not in lens["sample_query"]
    assert lens["sample_window"]["includes_current_year"] is True
    assert lens["papers"][0]["year"] == "2026"


def test_two_year_window_and_new_year_boundary():
    result = explore(SearchConfig(window_years=2, lens_ids=("calibration",)), client=FakeClient(), as_of=date(2026, 1, 1))
    assert result["windows"]["prior"]["years"] == [2022, 2023]
    assert result["windows"]["recent"]["years"] == [2024, 2025]
    assert result["windows"]["current_ytd"]["start"] == result["windows"]["current_ytd"]["end"]
    assert result["lenses"][0]["sample_window"]["end"] == "2026-01-01"


def test_period_totals_are_direct_queries_not_sum_of_overlapping_annual_bins():
    def counter(query):
        return 17 if ('"2020/01/01"' in query and '"2022/12/31"' in query) else 11
    result = _explore(FakeClient(counter))
    assert sum(row["count"] for row in result["yearly_counts"][:3]) == 33
    assert result["base_periods"]["prior"]["count"] == 17
    assert result["lenses"][0]["prior_count"] == 17
    assert any("겹" in text or "양쪽" in text for text in result["limitations"])


@pytest.mark.parametrize("baseline,recent,expected", [(0, 20, None), (1, 20, None), (4, 20, None), (5, 20, 4.0), (10, 0, 0.0)])
def test_growth_ratio_is_suppressed_for_sparse_baseline(baseline, recent, expected):
    def counter(query):
        return baseline if '"2020/01/01"' in query and '"2022/12/31"' in query else recent
    lens = _explore(FakeClient(counter))["lenses"][0]
    assert lens["growth_ratio"] == expected
    assert lens["delta"] == recent - baseline
    if baseline < 5:
        assert "5건 미만" in lens["growth_note"]


def test_successful_zero_and_failed_search_are_never_conflated():
    def counter(query):
        if '"external validation"' in query and '"2023/01/01"' in query and '"2025/12/31"' in query:
            raise PubMedError("offline")
        return 0
    result = _explore(FakeClient(counter))
    lens = result["lenses"][0]
    assert result["base_periods"]["recent"]["count"] == 0
    assert lens["prior_count"] == 0
    assert lens["recent_count"] is None
    assert lens["delta"] is None
    assert lens["growth_ratio"] is None
    assert lens["errors"]
    assert lens["recent_search"]["error"]
    assert not lens["papers"]


def test_outage_stops_after_two_consecutive_search_failures_without_zero_fill():
    def counter(query):
        raise PubMedError("service unavailable")
    client = FakeClient(counter)
    result = _explore(client, lens_ids=tuple(LENSES))
    assert len(client.calls) == 2
    assert all(row["count"] is None for row in result["yearly_counts"])
    assert all(row["recent_count"] is None and row["prior_count"] is None for row in result["lenses"])
    assert all(row["errors"] for row in result["lenses"])
    assert "요청을 중단" in result["base_periods"]["recent"]["error"]


def test_fetch_failure_preserves_counts_and_flags_missing_sample():
    result = _explore(FakeClient(fetch_error=True))
    lens = result["lenses"][0]
    assert lens["recent_count"] == 12
    assert lens["sample_total_count"] == 12
    assert lens["sample_count"] == 0
    assert not lens["papers"]
    assert any("메타데이터" in error for error in lens["errors"])


def test_mentions_are_literal_excerpts_even_when_design_is_negated():
    paper = {"title": "COPD model", "abstract": "No external validation was performed. Calibration was not assessed."}
    mentions = keyword_mentions(paper)
    assert {m["lens_id"] for m in mentions} == {"external_validation", "calibration"}
    assert all(m["snippet"] in paper[m["field"]] for m in mentions)
    assert all(m["term"] in m["snippet"] for m in mentions)
    assert all("performed" not in m and "validated" not in m for m in mentions)
    lens = _explore()["lenses"][0]
    assert "원문" in lens["papers"][0]["mention_caution"]
    assert lens["question_status"] == "탐색 가설 · 원문 검토 전"


def test_feasibility_uses_only_user_declarations():
    rows = feasibility("external_validation", {"clinical_data": "available", "outcome_labels": "unavailable", "external_cohort": "maybe"})
    states = {row["id"]: row["status"] for row in rows}
    assert states == {"clinical_data": "available", "outcome_labels": "unavailable", "external_cohort": "unknown", "predictions": "unknown"}
    assert all(row["status"] == "unknown" for row in feasibility("prospective"))
    assert all("N=" not in row["reason"] for row in rows)


def test_presets_and_custom_synonyms_produce_literal_fielded_queries():
    assert len(PRESETS) == 6
    assert len(LENSES) == 6
    assert all(lens["query"] for lens in LENSES.values())
    for preset in PRESETS:
        assert '[Title/Abstract]' in build_base_query(SearchConfig(preset=preset))
    query = build_base_query(SearchConfig(clinical_terms="asthma, severe asthma", modality_terms="MRI", ai_methods=("radiomics",)))
    assert '"asthma"[Title/Abstract] OR "severe asthma"[Title/Abstract]' in query
    assert '"MRI"[Title/Abstract]' in query
    assert "COPD" not in query
    assert AI_METHODS["radiomics"]["query"] in query


@pytest.mark.parametrize("config", [SearchConfig(preset="bad"), SearchConfig(ai_methods=()), SearchConfig(lens_ids=("bad",)), SearchConfig(window_years=4), SearchConfig(sample_size=11)])
def test_invalid_configuration_fails_before_network(config):
    client = FakeClient()
    with pytest.raises(ValueError):
        explore(config, client=client, as_of=date(2026, 9, 9))
    assert not client.calls


def test_json_and_markdown_preserve_queries_counts_provenance_and_snippets():
    result = _explore()
    lens = result["lenses"][0]
    loaded = json.loads(to_json(result))
    assert loaded["lenses"][0]["recent_search"]["translation"] == lens["recent_search"]["translation"]
    assert loaded["lenses"][0]["sample_total_count"] == 12
    assert loaded["lenses"][0]["sample_count"] == 1
    report = to_markdown(result)
    for text in (lens["sample_query"], lens["recent_search"]["query"], "pubmed metadata", "2026-09-09", "12345", "탐색 가설", "test warning", "TRANSLATED"):
        assert text in report
    assert "No external validation was performed" in report
    assert "완료 기간 비교에서 제외" in report


def test_csv_formula_escaping_and_standalone_provenance():
    result = _explore(FakeClient(title='  =HYPERLINK("https://example.org")'))
    rows = list(csv.DictReader(io.StringIO(to_csv(result))))
    assert len(rows) == 1
    assert rows[0]["title"].startswith("'  =")
    assert rows[0]["sample_total_count"] == "12"
    assert rows[0]["sample_metadata_count"] == "1"
    assert rows[0]["verified_by"] == "pubmed metadata"
    assert rows[0]["sample_query"] == result["lenses"][0]["sample_query"]
    assert json.loads(rows[0]["limitations_json"])
    assert json.loads(rows[0]["mentions_json"])[0]["snippet"]
    assert rows[0]["excluded_current_year"] == "2026"


def test_csv_empty_sample_retains_failed_count_as_blank_and_error():
    def counter(query):
        raise PubMedError("offline")
    rows = list(csv.DictReader(io.StringIO(to_csv(_explore(FakeClient(counter))))))
    assert rows[0]["recent_count"] == ""
    assert rows[0]["pmid"] == ""
    assert rows[0]["verified_by"] == ""
    assert json.loads(rows[0]["errors_json"])


def test_csv_negative_numeric_change_remains_a_number():
    result = _explore()
    result["lenses"][0]["delta"] = -7
    rows = list(csv.DictReader(io.StringIO(to_csv(result))))
    assert rows[0]["delta"] == "-7"


def test_bibtex_exports_actual_metadata_escaped_and_deduplicated():
    title = r"AI {test} 50% $x_1$ & \end{article}"
    client = FakeClient(title=title)
    result = _explore(client, lens_ids=("external_validation", "calibration"))
    bib = to_bibtex(result)
    assert bib.count("@article{pubmed12345,") == 1
    assert r"AI \{test\} 50\% \$x\_1\$ \& \textbackslash{}end\{article\}" in bib
    assert "Jane A Smith" in bib
    assert "pubmed metadata" in bib
    assert "verified = {true}" in bib
    assert "verified_by = {pubmed}" in bib
    assert f"verified_on = {{{result['retrieved_at'][:10]}}}" in bib
    assert "PubMed bibliographic metadata only" in bib
    assert result["lenses"][0]["sample_query"].replace('"', '\\"') in bib
    assert "2026-09-09" in bib
    assert len(client.fetch_calls) == 1


def test_selection_scope_note_travels_with_exports():
    result = _explore()
    result["export_note"] = "관심 주제로 선택한 외부 검증 관점만 내보냈습니다."
    assert result["export_note"] in to_markdown(result)
    assert result["export_note"] in to_bibtex(result)
    rows = list(csv.DictReader(io.StringIO(to_csv(result))))
    assert rows[0]["export_note"] == result["export_note"]
