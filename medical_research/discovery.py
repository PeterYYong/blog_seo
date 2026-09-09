"""Reproducible PubMed searches and explicitly provisional research questions.

This module does not infer study designs, novelty or publication prospects from
abstract keywords. Custom clinical/modality inputs are comma-separated English
synonyms, quoted as literal Title/Abstract phrases; blank inputs use the preset.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field, is_dataclass
from datetime import date, datetime, timezone
import re
from typing import Any, Callable, Mapping, Sequence
from urllib.parse import urlencode

from .pubmed import PubMedClient


PRESETS = {
    "copd_ct": {
        "label": "COPD · 흉부 CT",
        "clinical_terms": "COPD, chronic obstructive pulmonary disease, emphysema",
        "modality_terms": "computed tomography, CT",
    },
    "lung_cancer": {
        "label": "폐암 · 흉부 CT",
        "clinical_terms": "lung cancer, pulmonary nodule, lung neoplasm",
        "modality_terms": "computed tomography, CT",
    },
    "chest_xray": {
        "label": "흉부 X선 · 진단",
        "clinical_terms": "chest radiograph, chest x-ray, chest xray",
        "modality_terms": "",
    },
    "icu_sepsis": {
        "label": "중환자실 · 패혈증",
        "clinical_terms": "sepsis, septic shock",
        "modality_terms": "intensive care, ICU, electronic health record, EHR",
    },
    "pathology": {
        "label": "디지털 병리",
        "clinical_terms": "histopathology, digital pathology, whole slide image",
        "modality_terms": "",
    },
    "general_ai": {
        "label": "의료 인공지능 전반",
        "clinical_terms": "clinical, medical, patient, diagnosis, prognosis",
        "modality_terms": "",
    },
}


def _terms_query(terms: str) -> str:
    """Quote user phrases rather than accepting arbitrary PubMed query syntax."""
    phrases = [re.sub(r'[\x00-\x1f"\\\[\]]', " ", item).strip() for item in terms.split(",")]
    phrases = list(dict.fromkeys(re.sub(r"\s+", " ", item) for item in phrases if item))
    return "(" + " OR ".join(f'"{item}"[Title/Abstract]' for item in phrases) + ")" if phrases else ""


AI_METHODS = {
    "broad_ai": {
        "label": "의료 AI 전체",
        "query": _terms_query("artificial intelligence, machine learning, deep learning, neural network, radiomics, large language model, foundation model"),
    },
    "deep_learning": {
        "label": "딥러닝",
        "query": _terms_query("deep learning, neural network, convolutional neural network, transformer"),
    },
    "radiomics": {"label": "라디오믹스", "query": _terms_query("radiomics, radiomic")},
    "foundation_model": {
        "label": "파운데이션 모델",
        "query": _terms_query("foundation model, vision language model, self-supervised learning"),
    },
    "llm": {
        "label": "대규모 언어모델",
        "query": _terms_query("large language model, LLM, generative artificial intelligence"),
    },
}

CAPABILITIES = {
    "clinical_data": "임상 데이터 접근 가능 여부",
    "outcome_labels": "분석 목표에 맞는 정답·결과 변수",
    "external_cohort": "학습과 독립된 외부 기관 코호트",
    "predictions": "환자별 예측확률·점수 또는 이를 생성할 모델",
    "subgroup_attributes": "비교할 하위집단 변수와 이용 근거",
    "multimodal_data": "동일 환자에서 연결 가능한 여러 모달리티",
    "prospective_followup": "전향적 수집·추적을 수행할 환경",
    "time_or_site_metadata": "수집 시점·기관·장비 등 분포 변화 변수",
}

LENSES = {
    "external_validation": {
        "label": "외부 검증",
        "terms": "external validation, externally validated, independent validation, multicenter, multi-center",
        "question_template": "{topic}에서 AI 모델의 성능과 오차가 학습과 독립된 기관 코호트에서도 유지되는가?",
        "required_capabilities": ("clinical_data", "outcome_labels", "external_cohort", "predictions"),
    },
    "calibration": {
        "label": "보정 · 임상 유용성",
        "terms": "calibration, calibrated, decision curve, net benefit, clinical utility",
        "question_template": "{topic}에서 AI 예측의 보정과 의사결정 임계값별 순편익이 기존 임상 기준 대비 개선되는가?",
        "required_capabilities": ("clinical_data", "outcome_labels", "predictions"),
    },
    "domain_shift": {
        "label": "기관 · 시간 변화",
        "terms": "domain shift, distribution shift, dataset shift, temporal validation, domain adaptation, generalizability",
        "question_template": "{topic}에서 수집 기관·시점·장비 차이에 따라 AI 성능이 어떻게 변하며 재보정 후 회복되는가?",
        "required_capabilities": ("clinical_data", "outcome_labels", "predictions", "time_or_site_metadata"),
    },
    "fairness": {
        "label": "하위집단 · 공정성",
        "terms": "fairness, algorithmic bias, demographic bias, subgroup performance, health equity, disparities",
        "question_template": "{topic}에서 사전에 정의한 환자 하위집단 사이 AI 오류율·보정 차이가 임상적으로 의미 있는가?",
        "required_capabilities": ("clinical_data", "outcome_labels", "predictions", "subgroup_attributes"),
    },
    "multimodal": {
        "label": "다중모달 추가 가치",
        "terms": "multimodal, multi-modal, added value, incremental value, incremental predictive value, data fusion",
        "question_template": "{topic}에서 여러 모달리티를 결합하면 동일 환자의 단일 모달리티 기준 모델보다 예측·보정·임상 순편익이 개선되는가?",
        "required_capabilities": ("clinical_data", "outcome_labels", "predictions", "multimodal_data"),
    },
    "prospective": {
        "label": "전향적 평가",
        "terms": "prospective evaluation, prospective validation, prospective study, clinical trial, randomized controlled trial, workflow integration",
        "question_template": "{topic}에서 AI 사용이 전향적 실제 진료 환경의 의사결정·업무 시간·환자 결과에 어떤 영향을 미치는가?",
        "required_capabilities": ("clinical_data", "outcome_labels", "prospective_followup"),
    },
}
for _lens in LENSES.values():
    _lens["query"] = _terms_query(_lens["terms"])

LIMITATIONS = [
    "검색 건수와 증가량은 검색식에 일치한 PubMed 레코드 수입니다. 연구의 질·참신성·미충족 수요·게재 가능성을 측정하지 않습니다.",
    "기간 비교는 동일 길이의 완료된 달력 연도를 사용하며 올해는 제외합니다. 올해 누적 건수와 최신 문헌 표본에는 별도로 올해 자료가 포함됩니다.",
    "출판일[Date - Publication]은 전자·인쇄 출판일을 검색하므로 같은 PMID가 인접 연도나 비교 기간 양쪽에 포함될 수 있습니다. 연도별 건수를 더해 고유 논문 수로 해석하지 마세요. 기간별 건수는 별도 검색 결과입니다.",
    "제목·초록의 영어 표현과 동의어에 의존한 탐색입니다. PubMed 밖의 연구, 아직 색인되지 않은 연구, 다른 표현의 연구는 누락될 수 있습니다. NCBI 검색식 변환과 경고를 함께 확인하세요.",
    "문헌 표본은 지정 검색식의 최신 결과 일부입니다. 전체 문헌 검토나 관련성이 가장 높은 모든 선행연구를 대표하지 않습니다.",
    "표현 감지는 제목·초록의 문자 일치입니다. 해당 연구 설계를 실제 수행했다는 근거가 아니며 표현 부재도 연구 공백의 근거가 아닙니다. 원문 확인이 필요합니다.",
    "연구 질문은 탐색용 가설입니다. 입증된 공백이 아니며 기존 연구·등록 연구·프로토콜과 추가 비교해야 합니다.",
    "실행 여건은 사용자가 입력한 데이터 보유 상태만 반영합니다. 표본 수·사건 수·동의·윤리 심의·데이터 품질·통계적 검정력은 별도 확인 대상입니다.",
]


@dataclass(frozen=True)
class SearchConfig:
    preset: str = "copd_ct"
    clinical_terms: str = ""
    modality_terms: str = ""
    ai_methods: tuple[str, ...] = ("broad_ai",)
    lens_ids: tuple[str, ...] = tuple(LENSES)
    window_years: int = 3
    sample_size: int = 5
    capabilities: dict[str, str] = field(default_factory=dict)


def pubmed_url(query: str) -> str:
    return "https://pubmed.ncbi.nlm.nih.gov/?" + urlencode({"term": query})


def _dated_query(query: str, start: str, end: str) -> str:
    return f'({query}) AND ("{start.replace("-", "/")}"[Date - Publication] : "{end.replace("-", "/")}"[Date - Publication])'


def build_base_query(config: SearchConfig) -> str:
    if config.preset not in PRESETS:
        raise ValueError("알 수 없는 임상 프리셋입니다.")
    if not config.ai_methods or any(key not in AI_METHODS for key in config.ai_methods):
        raise ValueError("AI 방법을 한 개 이상 선택하세요.")
    preset = PRESETS[config.preset]
    clinical = _terms_query(config.clinical_terms.strip() or preset["clinical_terms"])
    modality = _terms_query(config.modality_terms.strip() or preset["modality_terms"])
    method = "(" + " OR ".join(AI_METHODS[key]["query"] for key in dict.fromkeys(config.ai_methods)) + ")"
    return " AND ".join(item for item in (clinical, modality, method) if item)


def feasibility(lens_id: str, capabilities: Mapping[str, str] | None = None) -> list[dict[str, str]]:
    """Return declarations, not an inferred overall feasibility score."""
    if lens_id not in LENSES:
        raise ValueError("알 수 없는 연구 관점입니다.")
    capabilities = capabilities or {}
    reasons = {
        "available": "사용자가 보유 가능으로 입력했습니다. 적합성·품질·표본 수는 별도 확인이 필요합니다.",
        "unavailable": "사용자가 현재 확보되지 않음으로 입력했습니다. 이 자료를 요구하는 설계의 실행 전 확보가 필요합니다.",
        "unknown": "사용자가 확보 여부를 확인하지 않았습니다. 실행 가능 여부를 판단할 수 없습니다.",
    }
    rows = []
    for key in LENSES[lens_id]["required_capabilities"]:
        status = capabilities.get(key, "unknown")
        status = status if status in reasons else "unknown"
        reason = reasons[status]
        if lens_id == "calibration" and key == "predictions":
            reason += " 보정·임상 순편익 평가는 경성 분류 라벨만으로 수행할 수 없으며 예측확률과 결과 변수가 필요합니다."
        rows.append({"id": key, "label": CAPABILITIES[key], "status": status, "reason": reason})
    return rows


def _mapping(value: Any) -> dict[str, Any]:
    if isinstance(value, Mapping):
        return dict(value)
    return asdict(value) if is_dataclass(value) else dict(vars(value))


def keyword_mentions(paper: Mapping[str, Any]) -> list[dict[str, str]]:
    """Locate literal excerpts; never label a mention as a performed design."""
    found = []
    for lens_id, lens in LENSES.items():
        for field_name in ("title", "abstract"):
            source = str(paper.get(field_name) or "")
            for term in lens["terms"].split(", "):
                match = re.search(r"(?<!\w)" + re.escape(term) + r"(?!\w)", source, re.IGNORECASE)
                if match:
                    found.append({
                        "lens_id": lens_id, "label": lens["label"],
                        "term": source[match.start():match.end()], "field": field_name,
                        "snippet": source[max(0, match.start() - 90): min(len(source), match.end() + 150)],
                    })
                    break
    return found


def _paper_dict(article: Any) -> dict[str, Any]:
    row = _mapping(article)
    row["pmid"] = str(row["pmid"])
    row["url"] = f'https://pubmed.ncbi.nlm.nih.gov/{row["pmid"]}/'
    row["verified_by"] = "pubmed metadata"
    row["mentions"] = keyword_mentions(row)
    row["mention_caution"] = "제목·초록의 표현 감지이며 해당 설계의 수행 여부·결과는 원문에서 확인해야 합니다."
    return row


def explore(
    config: SearchConfig,
    client: Any = None,
    progress: Callable[[str], Any] | None = None,
    as_of: date | None = None,
) -> dict[str, Any]:
    """Collect comparable query counts and bounded samples, preserving failures.

    ``progress`` receives a short Korean status string. Search/network failures
    are represented by a null count plus error; successful empty results are 0.
    The returned object is fully JSON serializable.
    """
    base_query = build_base_query(config)
    if config.window_years not in (2, 3):
        raise ValueError("비교 기간은 2년 또는 3년이어야 합니다.")
    if not 1 <= config.sample_size <= 10:
        raise ValueError("문헌 표본 수는 1–10이어야 합니다.")
    if not 1 <= len(config.lens_ids) <= len(LENSES) or any(key not in LENSES for key in config.lens_ids):
        raise ValueError("연구 관점을 1–6개 선택하세요.")
    today = as_of or date.today()
    if isinstance(today, datetime):
        today = today.date()
    now = datetime.now(timezone.utc).isoformat()
    current = today.year
    windows = {
        "prior": {"start": f"{current - 2 * config.window_years}-01-01", "end": f"{current - config.window_years - 1}-12-31", "years": list(range(current - 2 * config.window_years, current - config.window_years))},
        "recent": {"start": f"{current - config.window_years}-01-01", "end": f"{current - 1}-12-31", "years": list(range(current - config.window_years, current))},
        "current_ytd": {"start": f"{current}-01-01", "end": today.isoformat(), "years": [current]},
        "excluded_current_year": current,
    }
    client = client or PubMedClient()
    errors: list[str] = []
    search_cache: dict[tuple[str, int], dict[str, Any]] = {}
    consecutive_failures = 0

    def search(query: str, limit: int = 0) -> dict[str, Any]:
        nonlocal consecutive_failures
        key = (query, limit)
        if key in search_cache:
            return dict(search_cache[key])
        record = {"query": query, "url": pubmed_url(query), "count": None, "error": None, "translation": None, "warnings": [], "retrieved_at": now, "pmids": []}
        if consecutive_failures >= 2:
            record["error"] = "연속된 PubMed 검색 오류 2회로 이후 요청을 중단했습니다. 이 건수는 0이 아니라 미확인입니다. 잠시 후 다시 검색하세요."
            errors.append(record["error"])
            search_cache[key] = dict(record)
            return record
        try:
            response = _mapping(client.search(query, limit=limit, sort="pub date"))
            count = response.get("count")
            if isinstance(count, bool) or not isinstance(count, int) or count < 0:
                raise ValueError("PubMed 응답에 유효한 검색 건수가 없습니다.")
            record.update({"count": count, "translation": response.get("translation"), "warnings": list(response.get("warnings") or []), "retrieved_at": str(response.get("retrieved_at") or now), "pmids": [str(pmid) for pmid in (response.get("pmids") or [])][:limit] if limit else []})
            consecutive_failures = 0
        except Exception as exc:
            consecutive_failures += 1
            record["error"] = f"{type(exc).__name__}: {exc}"
            errors.append(record["error"])
        search_cache[key] = dict(record)
        return record

    def report(message: str) -> None:
        if progress:
            progress(message)

    report("동일 길이의 완료된 연도별 PubMed 검색 건수를 확인합니다.")
    yearly_counts = []
    for year in windows["prior"]["years"] + windows["recent"]["years"]:
        yearly_counts.append({"year": year, **search(_dated_query(base_query, f"{year}-01-01", f"{year}-12-31"))})
    base_periods = {}
    for period in ("prior", "recent", "current_ytd"):
        window = windows[period]
        base_periods[period] = search(_dated_query(base_query, window["start"], window["end"]))
    lens_rows = []
    article_cache: dict[str, dict[str, Any]] = {}
    topic = config.clinical_terms.strip() or PRESETS[config.preset]["label"]
    for lens_id in dict.fromkeys(config.lens_ids):
        spec = LENSES[lens_id]
        report(f'{spec["label"]}: 기간별 검색과 최신 문헌 표본을 확인합니다.')
        query = f'({base_query}) AND {spec["query"]}'
        periods = {name: search(_dated_query(query, windows[name]["start"], windows[name]["end"])) for name in ("prior", "recent")}
        sample_query = _dated_query(query, windows["recent"]["start"], today.isoformat())
        sample = search(sample_query, limit=config.sample_size)
        lens_errors = [record["error"] for record in (*periods.values(), sample) if record["error"]]
        to_fetch = [pmid for pmid in sample["pmids"] if pmid not in article_cache]
        if to_fetch:
            try:
                for article in client.fetch(to_fetch):
                    paper = _paper_dict(article)
                    article_cache[paper["pmid"]] = paper
            except Exception as exc:
                error = f"문헌 메타데이터 수집 실패 ({lens_id}): {type(exc).__name__}: {exc}"
                lens_errors.append(error)
                errors.append(error)
        missing = [pmid for pmid in sample["pmids"] if pmid not in article_cache]
        if missing:
            error = f'요청한 문헌 메타데이터 {len(missing)}개를 받지 못했습니다: {", ".join(missing)}'
            lens_errors.append(error)
            errors.append(error)
        previous, recent = periods["prior"]["count"], periods["recent"]["count"]
        comparable = previous is not None and recent is not None
        growth = round(recent / previous, 4) if comparable and previous >= 5 else None
        lens_rows.append({
            "id": lens_id, "label": spec["label"], "query": query, "url": pubmed_url(query),
            "prior_search": periods["prior"], "recent_search": periods["recent"],
            "prior_count": previous, "recent_count": recent,
            "delta": recent - previous if comparable else None,
            "growth_ratio": growth,
            "growth_note": "최근 기간 건수 / 이전 기간 건수" if growth is not None else ("기간 검색 실패로 계산할 수 없습니다." if not comparable else "이전 기간이 5건 미만이어서 불안정한 증가배수를 표시하지 않습니다."),
            "sample_query": sample_query, "sample_url": pubmed_url(sample_query), "sample_search": sample,
            "sample_window": {"start": windows["recent"]["start"], "end": today.isoformat(), "includes_current_year": True},
            "sample_limit": config.sample_size, "sample_count": len(sample["pmids"]) - len(missing),
            "sample_total_count": sample["count"],
            "papers": [article_cache[pmid] for pmid in sample["pmids"] if pmid in article_cache],
            "sample_label": "PubMed 출판일 정렬의 최신 검색 결과 일부 (올해 포함). 전체·최인접 선행연구 목록이 아닙니다.",
            "question": spec["question_template"].format(topic=topic), "question_status": "탐색 가설 · 원문 검토 전",
            "feasibility": feasibility(lens_id, config.capabilities),
            "errors": lens_errors, "warnings": list(dict.fromkeys(w for record in (*periods.values(), sample) for w in record["warnings"])),
            "limitations": list(LIMITATIONS),
        })
    report("검색 기록과 근거 문헌 표본을 정리했습니다.")
    return {
        "schema_version": "1.0", "config": asdict(config), "base_query": base_query, "base_url": pubmed_url(base_query),
        "retrieved_at": now, "as_of": today.isoformat(), "windows": windows,
        "yearly_counts": yearly_counts, "base_periods": base_periods,
        "lenses": lens_rows, "errors": errors, "limitations": list(LIMITATIONS),
        "source": "NCBI PubMed E-utilities", "verified_by": "pubmed metadata",
        "verification_scope": "PMID와 서지정보를 PubMed 응답에서 가져왔습니다. 연구 결과·설계·참신성에 대한 검증은 아닙니다.",
    }
