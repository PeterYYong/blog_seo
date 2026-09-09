"""Korean Streamlit interface for the medical AI literature explorer."""

from __future__ import annotations

import copy
import json
import math
import re
import time
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any
from urllib.parse import quote

import altair as alt
import pandas as pd
import streamlit as st

from medical_research.discovery import AI_METHODS, LENSES, PRESETS, SearchConfig, build_base_query, explore
from medical_research.exports import to_bibtex, to_csv, to_json, to_markdown
from src.rate_limiter import SlidingWindowRateLimiter


CAPABILITIES = {
    "clinical_data": "분석 가능한 임상·영상 데이터",
    "outcome_labels": "검증 가능한 정답·임상 결과",
    "external_cohort": "개발 기관과 독립된 외부 코호트",
    "predictions": "환자별 예측확률·점수 또는 이를 생성할 모델",
    "subgroup_attributes": "사전에 정의한 하위집단 정보",
    "multimodal_data": "동일 대상자의 두 종류 이상 데이터",
    "prospective_followup": "전향적 수집·추적 또는 평가 환경",
    "time_or_site_metadata": "검사 시점·기관·장비 구분 정보",
}
STATUS_NAMES = {"unknown": "미확인", "available": "확보", "unavailable": "미확보"}

CSS = """
<style>
:root { --med-ink: #162c36; --med-teal: #087f82; }
.stApp { background: #f7f9fa; }
.block-container { max-width: 1270px; padding-top: 2.8rem; padding-bottom: 3rem; }
[data-testid="stSidebar"] { background: #eef3f4; border-right: 1px solid #dbe5e7; }
h1, h2, h3 { color: var(--med-ink); letter-spacing: -.035em; }
h1 { font-size: 2.75rem !important; font-weight: 750 !important; }
[data-testid="stMetric"] { background: white; border: 1px solid #dce7e9;
 border-radius: 12px; padding: 18px 20px; }
[data-testid="stMetricValue"] { color: var(--med-teal); }
.med-kicker { color: #087f82; font-weight: 700; font-size: .76rem; letter-spacing: .15em; }
.med-intro { max-width: 790px; color: #506572; font-size: 1.05rem; line-height: 1.8; }
.med-step { border-top: 3px solid #13898b; padding-top: 12px; }
.med-step span { color: #087f82; font-size: .78rem; font-weight: 700; }
.med-step h3 { font-size: 1.13rem; margin: 8px 0; }
.med-step p { font-size: .92rem; color: #526671; line-height: 1.6; }
[data-testid="stTabs"] { margin-top: 1rem; }
.stButton > button[kind="primary"] { background: #087f82; border-color: #087f82; }
@media (max-width: 700px) { h1 { font-size: 2rem !important; }
 .block-container { padding-top: 1.5rem; } }
</style>
"""


def _md(value: Any) -> str:
    return re.sub(r"([\\`*_{}\[\]<>])", r"\\\1", str(value))


def _number(value: Any) -> str:
    return f"{value:,}" if isinstance(value, int) and not isinstance(value, bool) else "미확인"


def _period_label(window: dict) -> str:
    return f"{str(window.get('start', ''))[:4]}–{str(window.get('end', ''))[:4]}"


def _utc_label(value: str) -> str:
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        return parsed.strftime("%Y-%m-%d %H:%M UTC")
    except (ValueError, AttributeError):
        return str(value)


@st.cache_resource
def _run_limiter() -> SlidingWindowRateLimiter:
    return SlidingWindowRateLimiter(30, 3600)


class _UncachedResult(Exception):
    """Keep a partial service response visible without caching its failures."""

    def __init__(self, result: dict) -> None:
        super().__init__("Partial PubMed response")
        self.result = result


@st.cache_data(ttl=21600, max_entries=32, show_spinner=False)
def cached_explore(config_json: str, as_of_iso: str) -> dict:
    config_data = json.loads(config_json)
    config_data["ai_methods"] = tuple(config_data["ai_methods"])
    config_data["lens_ids"] = tuple(config_data["lens_ids"])
    result = explore(SearchConfig(**config_data), as_of=date.fromisoformat(as_of_iso))
    if result.get("errors") or any(lens.get("errors") for lens in result.get("lenses", [])):
        raise _UncachedResult(result)
    return result


def _sidebar() -> dict:
    with st.sidebar:
        st.markdown("### 탐색 범위")
        preset = st.selectbox("임상 분야", list(PRESETS), format_func=lambda x: PRESETS[x]["label"], key="medical_preset")
        method = st.selectbox("AI 방법", list(AI_METHODS), format_func=lambda x: AI_METHODS[x]["label"], key="medical_method")
        st.caption("기본 검색어를 사용하거나 영어 동의어를 쉼표로 구분해 입력하세요.")
        clinical = st.text_area("질환·임상 개념 (선택)", placeholder=PRESETS[preset]["clinical_terms"], height=85, max_chars=500, key="medical_clinical")
        modality = st.text_input("데이터·검사 종류 (선택)", placeholder=PRESETS[preset]["modality_terms"] or "선택한 분야의 기본 범위", max_chars=300, key="medical_modality")
        lens_ids = st.multiselect("비교할 연구 관점", list(LENSES), default=list(LENSES)[:4], format_func=lambda x: LENSES[x]["label"], key="medical_lenses")
        window = st.select_slider("비교 기간", options=[2, 3], value=3, format_func=lambda x: f"최근 {x}년 vs 이전 {x}년", key="medical_window")
        sample = st.select_slider("관점별 확인할 최신 논문", options=[3, 5, 8], value=5, key="medical_sample")
        st.divider()
        st.markdown("### 데이터 준비 상황")
        st.caption("본인이 알고 있는 보유 현황입니다. 표본 수나 연구 승인 여부를 자동 판단하지 않습니다.")
        capabilities = {}
        with st.expander("보유 데이터·평가 환경 입력", expanded=False):
            for key, label in CAPABILITIES.items():
                capabilities[key] = st.selectbox(label, list(STATUS_NAMES), format_func=STATUS_NAMES.get, key=f"medical_cap_{key}")
        st.divider()
        st.caption("출처 · PubMed / NCBI\n\n별도 API 키 없이 사용합니다. 검색어는 PubMed로 전송됩니다. 공개 연구 개념만 입력하세요.")
    return {
        "preset": preset, "clinical_terms": clinical.strip(), "modality_terms": modality.strip(),
        "ai_methods": [method], "lens_ids": lens_ids, "window_years": window,
        "sample_size": sample, "capabilities": capabilities,
    }


def _overview(result: dict) -> None:
    windows = result["windows"]
    recent_label = _period_label(windows["recent"])
    prior_label = _period_label(windows["prior"])
    periods = result.get("base_periods", {})
    recent = periods.get("recent", {}).get("count")
    prior = periods.get("prior", {}).get("count")
    ytd = periods.get("current_ytd", {}).get("count")
    cols = st.columns(4)
    cols[0].metric(f"최근 기간 · {recent_label}", _number(recent))
    cols[1].metric(f"이전 기간 · {prior_label}", _number(prior))
    cols[2].metric(f"올해 누적 · {result['as_of'][:4]}", _number(ytd))
    cols[3].metric("비교한 연구 관점", len(result.get("lenses", [])))
    st.caption(f"PubMed 검색 일치 건수 · {recent_label}와 {prior_label}는 같은 길이의 완료된 연도입니다. 올해 누적은 증가율 계산에 포함하지 않습니다.")
    annual = pd.DataFrame(result.get("yearly_counts", []))
    if not annual.empty and annual["count"].notna().any():
        st.subheader("분야의 문헌 흐름")
        chart = alt.Chart(annual).mark_bar(cornerRadiusTopLeft=5, cornerRadiusTopRight=5, color="#0c8587").encode(
            x=alt.X("year:O", title="출판연도 검색 구간"),
            y=alt.Y("count:Q", title="PubMed 검색 일치 건수"),
            tooltip=[alt.Tooltip("year:O", title="연도"), alt.Tooltip("count:Q", title="검색 건수", format=",")],
        ).properties(height=270)
        st.altair_chart(chart, use_container_width=True)
        if annual["count"].isna().any():
            st.warning("일부 연도는 조회에 실패했습니다. 빈 값은 0건을 뜻하지 않습니다.")
    st.caption("전자출판·인쇄출판 날짜가 다른 논문은 인접 연도에 중복 집계될 수 있습니다. 기간별 총건수는 별도 검색하며, 연도별 막대를 더한 값과 다를 수 있습니다.")
    st.subheader("관점별 연구 분포")
    rows = []
    for lens in result.get("lenses", []):
        growth = lens.get("growth_ratio")
        rows.append({
            "연구 관점": lens["label"], f"이전 {prior_label}": lens.get("prior_count"),
            f"최근 {recent_label}": lens.get("recent_count"), "건수 변화": lens.get("delta"),
            "최근 / 이전": round(growth, 2) if isinstance(growth, (int, float)) and math.isfinite(growth) else None,
            "논문 표본": len(lens.get("papers", [])), "조회 상태": "일부 미확인" if lens.get("errors") else "확인",
        })
    if rows:
        st.dataframe(pd.DataFrame(rows), hide_index=True, use_container_width=True)
    st.info("논문 수와 증가율은 관심 분야를 비교하는 단서입니다. 적은 논문 수는 새로운 주제의 증명이 아니며, 이전 기간이 5건 미만이면 증가 배율을 표시하지 않습니다.")


def _paper_card(paper: dict, prefix: str = "") -> None:
    pmid = str(paper.get("pmid", ""))
    st.markdown(f"**{_md(paper.get('title') or '제목 미제공')}**")
    authors = paper.get("authors") or []
    author_label = ", ".join(authors[:3]) + (" 외" if len(authors) > 3 else "")
    st.caption(" · ".join(x for x in [paper.get("year", ""), paper.get("journal", ""), author_label, f"PMID {pmid}"] if x))
    if paper.get("retracted"):
        st.error("철회 관련 표지가 있습니다. PubMed 기록과 출판사 공지를 먼저 확인하세요.")
    link_cols = st.columns([1, 1, 3])
    if pmid.isdigit():
        link_cols[0].link_button("PubMed 원문 정보 ↗", f"https://pubmed.ncbi.nlm.nih.gov/{pmid}/")
    doi = str(paper.get("doi") or "")
    if re.match(r"^10\.\d{4,9}/\S+$", doi):
        link_cols[1].link_button("DOI ↗", f"https://doi.org/{quote(doi, safe='/')}" )
    with st.expander("초록과 연구 관점의 단서"):
        abstract = paper.get("abstract") or ""
        st.text(abstract[:1000] + ("…" if len(abstract) > 1000 else "") if abstract else "PubMed에 초록이 제공되지 않았습니다.")
        if len(abstract) > 1000:
            st.caption("초록 앞부분을 표시합니다. 전체 초록은 PubMed 링크에서 확인하세요.")
        mentions = paper.get("mentions") or []
        if mentions:
            st.caption("다음은 제목·초록에서 발견한 표현입니다. 해당 방법을 실제 수행했다는 판정은 아닙니다.")
            for mention in mentions[:6]:
                st.markdown(f"**{_md(mention.get('label', ''))}** · {_md(mention.get('field', ''))}")
                st.text(mention.get("snippet", ""))
        else:
            st.caption("선택한 관점의 표현을 제목·초록에서 확인하지 못했습니다. 원문에서의 부재를 뜻하지 않습니다.")


def _candidate_cards(result: dict) -> None:
    st.subheader("문헌을 읽으며 좁혀갈 연구 질문")
    st.caption("아래는 검색 근거를 확인할 질문 초안입니다. 기존 연구와의 차별성은 원문을 읽고 비교해야 확정할 수 있습니다.")
    sort_mode = st.selectbox("후보 정렬", ["관점 순서", "최근 문헌 많은 순", "건수 증가 큰 순"], key="medical_sort")
    lenses = list(result.get("lenses", []))
    if sort_mode != "관점 순서":
        key = "recent_count" if sort_mode == "최근 문헌 많은 순" else "delta"
        lenses.sort(key=lambda x: (bool(x.get("errors")), x.get(key) is None, -(x.get(key) or 0)))
    for lens in lenses:
        with st.container(border=True):
            left, right = st.columns([4, 1])
            left.markdown(f"### {_md(lens['label'])}")
            right.checkbox("관심 주제", key=f"medical_saved_{lens['id']}")
            st.markdown(f"**검토할 질문**  \n{_md(lens.get('question', ''))}")
            a, b, c = st.columns(3)
            a.metric("최근 기간 문헌", _number(lens.get("recent_count")))
            b.metric("이전 기간 문헌", _number(lens.get("prior_count")))
            growth = lens.get("growth_ratio")
            c.metric("최근 / 이전", f"{growth:.2f}배" if isinstance(growth, (int, float)) else "비교 보류")
            if lens.get("errors"):
                st.warning("조회하지 못한 항목이 있어 이 후보의 근거를 일부 확인하지 못했습니다.")
            elif lens.get("recent_count") == 0:
                st.info("이 검색식의 최근 기간 결과가 0건입니다. 동의어·검색 범위와 최신 문헌을 먼저 확인하세요.")
            elif (lens.get("recent_count") or 0) < 5:
                st.info("검색 건수가 적습니다. 작은 수의 변화를 연구 공백으로 해석하지 마세요.")
            feasibility = lens.get("feasibility") or []
            if feasibility:
                st.markdown("**이 질문을 연구하려면**")
                for item in feasibility:
                    st.write(f"{STATUS_NAMES.get(item.get('status'), '미확인')} · {item.get('label', item.get('id', ''))}")
                st.caption("자기 보고에 따른 준비물 점검이며 표본 수, 데이터 품질, 연구 승인 적합성 판단은 포함하지 않습니다.")
            papers = lens.get("papers") or []
            with st.expander(f"관련 최신 논문 {len(papers)}편 확인"):
                st.caption(f"최신 논문 검색 구간에서 전체 {_number(lens.get('sample_total_count'))}건 중 메타데이터 {len(papers)}편을 가져왔습니다.")
                st.caption("PubMed 출판일순 검색의 제한된 표본입니다. 가장 유사한 연구 전체를 찾았다는 뜻은 아닙니다.")
                if not papers:
                    st.write("표시할 메타데이터가 없습니다. 아래 검색식을 PubMed에서 확인하세요.")
                for i, paper in enumerate(papers):
                    _paper_card(paper, f"{lens['id']}_{i}")
                    if i < len(papers) - 1:
                        st.divider()
            st.link_button("이 관점의 PubMed 검색 열기 ↗", lens.get("sample_url") or lens["url"])


def _literature(result: dict) -> None:
    st.subheader("검색에서 가져온 논문")
    unique: dict[str, dict] = {}
    for lens in result.get("lenses", []):
        for paper in lens.get("papers", []):
            unique.setdefault(paper["pmid"], paper)
    st.caption(f"PMID 기준 중복 제거 후 {len(unique)}편 · 각 관점의 제한된 최신 표본이며 체계적 문헌고찰 결과가 아닙니다.")
    filter_text = st.text_input("가져온 제목·초록에서 찾기", key="medical_paper_filter").strip().casefold()
    for paper in unique.values():
        if filter_text and filter_text not in (paper.get("title", "") + " " + paper.get("abstract", "")).casefold():
            continue
        with st.container(border=True):
            _paper_card(paper, "all")
    if not unique:
        st.info("이 검색에서 가져온 논문이 없습니다. 검색 범위를 넓혀 다시 탐색할 수 있습니다.")


def _notes(result: dict) -> None:
    lenses = result.get("lenses", [])
    if not lenses:
        return
    st.subheader("연구 질문을 내 데이터에 맞게 다듬기")
    selected_id = st.selectbox("초안으로 발전시킬 관점", [x["id"] for x in lenses], format_func=lambda x: LENSES[x]["label"], key="medical_draft_lens")
    selected = next(x for x in lenses if x["id"] == selected_id)
    st.info(selected.get("question", ""))
    a, b = st.columns(2)
    population = a.text_input("대상 환자·진료 환경", placeholder="예: 외부 기관에서 촬영한 성인 흉부 CT", key="medical_note_population")
    model = b.text_input("평가할 AI 또는 입력 데이터", placeholder="예: 영상 모델과 임상정보 결합 모델", key="medical_note_model")
    comparator = a.text_input("비교할 기준", placeholder="예: 임상정보만 사용한 모델", key="medical_note_comparator")
    endpoint = b.text_input("주 평가 결과", placeholder="예: 정해진 시점의 결과에 대한 calibration", key="medical_note_endpoint")
    difference = st.text_area("기존 논문과 다른 점 · 원문에서 확인할 내용", placeholder="대상 집단, 데이터 수집 시점, 평가 설계, 비교 모델 등의 차이를 근거와 함께 기록하세요.", key="medical_note_difference")
    draft = "\n".join([
        "# 의료 AI 연구 질문 초안", "", f"작성일: {date.today().isoformat()}", "",
        f"## 연구 관점\n{selected['label']}", f"\n## 검토할 질문\n{selected.get('question', '')}",
        f"\n- 대상: {population or '[미정]'}", f"- AI / 입력: {model or '[미정]'}",
        f"- 비교 기준: {comparator or '[미정]'}", f"- 주 평가 결과: {endpoint or '[미정]'}",
        f"\n## 차별성 확인 메모\n{difference or '[원문 비교 후 작성]'}",
        "\n## 다음 확인", "- 유사 연구의 원문과 최근 체계적 고찰을 비교한다.",
        "- 표본 수·사건 수·데이터 누락과 참조 기준을 확인한다.",
        "- 개발·평가 데이터 분리, 비교 모델, 외부 검증 계획을 정한다.",
        "- 데이터 이용 권한과 필요한 연구 승인 범위를 확인한다.",
        f"\n## 검색 근거\n{selected.get('sample_url') or selected['url']}",
        "\n이 문서는 검토용 질문 초안이며 신규성·실행 가능성이 확정된 연구계획서가 아닙니다.",
    ])
    st.download_button("연구 질문 초안 내려받기", draft, file_name="medical_ai_question.md", mime="text/markdown", key="medical_draft_download")


def _provenance(result: dict) -> None:
    with st.expander("검색식·조회 기록·해석 방법"):
        st.code(result.get("base_query", ""), language=None)
        st.caption(f"문헌 조회 시각: {_utc_label(result.get('retrieved_at', ''))} · 최신 논문 검색 종료일: {result.get('as_of', '')}")
        st.write("관점별 논문 표본은 최근 비교 기간의 시작일부터 검색일까지 포함합니다. 올해 논문도 표시되며, 완료된 연도끼리 비교하는 건수표와 검색 범위가 다릅니다.")
        for limitation in result.get("limitations", []):
            st.write(f"• {limitation}")
        for error in result.get("errors", []):
            st.warning(str(error))
        for name, record in result.get("base_periods", {}).items():
            st.markdown(f"**기본 범위 · {_md(name)}**")
            st.code(record.get("query", ""), language=None)
            if record.get("translation"):
                st.caption("PubMed가 적용한 검색식")
                st.code(record["translation"], language=None)
            for warning in record.get("warnings", []):
                st.warning(str(warning))
        for lens in result.get("lenses", []):
            st.markdown(f"**{_md(lens['label'])}**")
            st.code(lens.get("sample_query") or lens.get("query", ""), language=None)
            sample_record = lens.get("sample_search", {})
            if sample_record.get("translation"):
                st.caption("PubMed가 적용한 최신 논문 검색식")
                st.code(sample_record["translation"], language=None)
            for warning in lens.get("warnings", []):
                st.warning(str(warning))
            for limitation in lens.get("limitations", []):
                st.caption(str(limitation))
        st.link_button("PubMed 검색 도움말", "https://pubmed.ncbi.nlm.nih.gov/help/")
        st.markdown("**전체 검색 변환·경고 기록**")
        st.json({
            "base_periods": result.get("base_periods", {}),
            "yearly_counts": result.get("yearly_counts", []),
            "lenses": [{"id": lens["id"], **{name: lens.get(name, {}) for name in ("prior_search", "recent_search", "sample_search")}} for lens in result.get("lenses", [])],
        }, expanded=False)
        method_path = Path(__file__).resolve().parents[1] / "MEDICAL_AI_METHODOLOGY.md"
        if method_path.exists():
            st.download_button("지표 해석 방법 내려받기", method_path.read_text(encoding="utf-8"), file_name="medical_ai_methodology.md", mime="text/markdown")


def _exports(result: dict) -> None:
    export_result = copy.deepcopy(result)
    saved = [x for x in export_result.get("lenses", []) if st.session_state.get(f"medical_saved_{x['id']}", False)]
    if saved:
        export_result["lenses"] = saved
        export_result["export_note"] = "사용자가 관심 주제로 선택한 관점만 포함합니다."
        st.caption(f"관심 주제 {len(saved)}개를 내보냅니다.")
    else:
        st.caption("모든 관점을 내보냅니다. 관심 주제를 선택하면 선택한 관점만 포함됩니다.")
    stamp = result.get("as_of", date.today().isoformat()).replace("-", "")
    columns = st.columns(4)
    columns[0].download_button("탐색 보고서 · Markdown", to_markdown(export_result), f"medical_ai_topics_{stamp}.md", "text/markdown", use_container_width=True)
    columns[1].download_button("후보·문헌표 · CSV", to_csv(export_result).encode("utf-8-sig"), f"medical_ai_topics_{stamp}.csv", "text/csv", use_container_width=True)
    columns[2].download_button("참고문헌 · BibTeX", to_bibtex(export_result), f"medical_ai_references_{stamp}.bib", "application/x-bibtex", use_container_width=True)
    columns[3].download_button("검색 기록 · JSON", to_json(export_result), f"medical_ai_search_{stamp}.json", "application/json", use_container_width=True)


def run() -> None:
    st.set_page_config(page_title="의료 AI 연구 주제 탐색기", page_icon="🔬", layout="wide", initial_sidebar_state="expanded")
    st.markdown(CSS, unsafe_allow_html=True)
    config_data = _sidebar()
    signature = json.dumps(config_data, ensure_ascii=False, sort_keys=True)
    st.markdown('<div class="med-kicker">MEDICAL AI · RESEARCH EXPLORER</div>', unsafe_allow_html=True)
    st.title("다음 연구 질문을, 문헌에서 찾다")
    st.markdown('<p class="med-intro">임상 분야의 연구 흐름을 살펴보고, 내 데이터로 검토할 의료 인공지능 논문 주제를 좁혀보세요. 모든 후보에는 검색 근거와 확인할 논문이 연결됩니다.</p>', unsafe_allow_html=True)
    left, right = st.columns([3, 2])
    with left:
        submitted = st.button("문헌 근거로 주제 탐색", type="primary", use_container_width=True, key="medical_search")
    right.caption("PubMed 실시간 조회 · 영어 문헌 개념 검색 · 결과 6시간 캐시")
    st.caption(f"선택한 분야: {PRESETS[config_data['preset']]['label']} · {len(config_data['lens_ids'])}개 연구 관점 · 관점별 최신 논문 최대 {config_data['sample_size']}편")
    with st.expander("이번 탐색에 사용할 검색식"):
        st.code(build_base_query(SearchConfig(**config_data)), language=None)
        st.caption("기본 범위에 각 연구 관점의 표현과 출판일 구간을 더해 검색합니다. 입력을 비워두면 분야별 기본 영어 검색어가 적용됩니다.")
    st.caption("자료 출처: [PubMed](https://pubmed.ncbi.nlm.nih.gov/) · [NCBI 이용 안내·저작권 고지](https://www.ncbi.nlm.nih.gov/About/disclaimer.html)")

    if submitted:
        if not config_data["lens_ids"]:
            st.warning("비교할 연구 관점을 하나 이상 선택하세요.")
        elif re.search(r"[가-힣]", config_data["clinical_terms"] + config_data["modality_terms"]):
            st.warning("PubMed 검색어는 영어로 입력하세요. 입력란을 비우면 선택한 분야의 영어 동의어를 사용합니다.")
        else:
            now = time.monotonic()
            last = st.session_state.get("medical_last_search", 0.0)
            session_retry = max(0.0, 20 - (now - last)) if last else 0.0
            retry = session_retry or _run_limiter().acquire()
            if retry:
                st.warning(f"조회 간격을 두고 {math.ceil(retry)}초 뒤에 다시 시도하세요.")
            else:
                st.session_state["medical_last_search"] = now
                try:
                    with st.status("PubMed 문헌과 연구 관점을 확인하고 있습니다…", expanded=True) as status:
                        st.write("연도별 검색 건수 → 관점별 비교 → 최신 논문 메타데이터 순서로 확인합니다.")
                        try:
                            result = cached_explore(signature, datetime.now(timezone.utc).date().isoformat())
                        except _UncachedResult as partial:
                            result = partial.result
                        has_any_count = any(record.get("count") is not None for record in result.get("base_periods", {}).values())
                        has_errors = bool(result.get("errors")) or any(x.get("errors") for x in result.get("lenses", []))
                        if has_any_count or not st.session_state.get("medical_result"):
                            st.session_state["medical_result"] = result
                            st.session_state["medical_result_signature"] = signature
                            for key in list(st.session_state):
                                if key.startswith("medical_saved_"):
                                    del st.session_state[key]
                        else:
                            st.error("새 검색을 완료하지 못해 마지막으로 확인한 결과를 유지합니다. 새 검색 조건의 결과가 아닙니다.")
                        status.update(label=("문헌 조회 실패" if not has_any_count else "문헌 탐색 완료 · 일부 항목 미확인" if has_errors else "문헌 탐색 완료"), state="error" if has_errors else "complete", expanded=False)
                except ValueError as exc:
                    st.error(f"검색 조건을 확인하세요: {exc}")
                except Exception:
                    st.error("문헌 서비스의 응답을 처리하지 못했습니다. 잠시 후 다시 시도하세요. 이전 결과가 있으면 아래에 유지됩니다.")

    result = st.session_state.get("medical_result")
    if not result:
        st.divider()
        for col, number, title, body in zip(st.columns(3), ["01", "02", "03"],
            ["관심 분야를 정하세요", "근거를 비교하세요", "내 연구 질문을 만드세요"],
            ["질환·데이터·AI 방법을 선택하고 검토할 연구 관점을 고릅니다.",
             "같은 기간의 논문 수와 최신 논문을 나란히 읽고 후속 질문을 찾습니다.",
             "외부 데이터·정답·추적 자료 등 준비 상황을 확인하고 질문 초안을 내려받습니다."]):
            col.markdown(f'<div class="med-step"><span>{number}</span><h3>{title}</h3><p>{body}</p></div>', unsafe_allow_html=True)
        st.info("예: COPD · 흉부 CT를 선택한 뒤 외부 검증, 보정·임상 유용성, 기관·장비 변화의 관점에서 연구 질문을 비교해보세요.")
        st.caption("이 앱은 연구 아이디어를 검토하는 도구입니다. 문헌 검색만으로 신규성, 게재 가능성, 임상적 유효성이 확정되지는 않습니다.")
        return

    if signature != st.session_state.get("medical_result_signature"):
        st.info("입력 조건이 변경되었습니다. 아래는 마지막 실행 조건의 결과이며, 새 조건을 적용하려면 다시 탐색하세요.")
    st.caption(f"결과 기준: {PRESETS[result['config']['preset']]['label']} · {_utc_label(result.get('retrieved_at', ''))}")
    tabs = st.tabs(
        ["문헌 지도", "주제 후보", "관련 논문", "연구 질문 메모"],
        key="medical_results_tab", on_change="rerun",
    )
    with tabs[0]:
        _overview(result)
    with tabs[1]:
        _candidate_cards(result)
    with tabs[2]:
        _literature(result)
    with tabs[3]:
        _notes(result)
    st.divider()
    _exports(result)
    _provenance(result)
