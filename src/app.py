"""Streamlit dashboard for the evidence-first Naver SEO workflow."""

from __future__ import annotations

import os
import sys
import time
from collections.abc import Iterable
from datetime import datetime, timezone
from typing import Any

import pandas as pd
import streamlit as st


current_dir = os.path.dirname(os.path.abspath(__file__))
if current_dir not in sys.path:
    sys.path.append(current_dir)

try:
    from calculator import (
        calculate_efficiency,
        calculate_saturation,
        classify_keyword,
        filter_keywords,
    )
    from data_fetcher import RealDataFetcher, fetch_keyword_data
    from keyword_expander import expand_keyword
    from rate_limiter import SlidingWindowRateLimiter
    from seo_sources import SourceError, SourceFailureCircuitBreaker
    from trend_hunter import fetch_trending_topics
except ImportError:  # pragma: no cover - package execution path
    sys.path.append(os.path.join(current_dir, ".."))
    from src.calculator import (
        calculate_efficiency,
        calculate_saturation,
        classify_keyword,
        filter_keywords,
    )
    from src.data_fetcher import RealDataFetcher, fetch_keyword_data
    from src.keyword_expander import expand_keyword
    from src.rate_limiter import SlidingWindowRateLimiter
    from src.seo_sources import SourceError, SourceFailureCircuitBreaker
    from src.trend_hunter import fetch_trending_topics


CLASS_LABELS = {
    "insufficient_data": "근거 부족",
    "low_supply_ratio": "낮은 공급비율",
    "moderate_supply_ratio": "중간 공급비율",
    "high_supply_ratio": "높은 공급비율",
}

DISPLAY_COLUMNS = {
    "Keyword": "키워드",
    "Monthly_Search_Volume": "월간 검색량 추정",
    "Search_Volume_Censored": "범위 추정값",
    "Blog_Doc_Count": "블로그 검색 결과 수",
    "Saturation_Index": "공급비율 Sk",
    "Efficiency_Score": "탐색 점수 Ek",
    "Assessment": "해석",
}

SESSION_COOLDOWN_SECONDS = 30
GLOBAL_ANALYSIS_LIMIT_PER_HOUR = 10


def get_fetcher() -> RealDataFetcher:
    """Reuse an HTTP connection pool within, but not across, user sessions."""

    key = "_naver_data_fetcher"
    if key not in st.session_state:
        st.session_state[key] = RealDataFetcher()
    return st.session_state[key]


@st.cache_resource(show_spinner=False)
def get_analysis_rate_limiter() -> SlidingWindowRateLimiter:
    """Share only the explicitly thread-safe quota guard across sessions."""

    return SlidingWindowRateLimiter(GLOBAL_ANALYSIS_LIMIT_PER_HOUR, 3600)


def claim_analysis_slot() -> tuple[bool, str | None]:
    """Apply per-session cooldown and a process-wide hourly run budget."""

    now = time.monotonic()
    last_started = st.session_state.get("_last_analysis_started_at")
    if isinstance(last_started, (int, float)):
        remaining = SESSION_COOLDOWN_SECONDS - (now - float(last_started))
        if remaining > 0:
            return False, f"같은 세션에서는 약 {int(remaining) + 1}초 후 다시 실행할 수 있습니다."

    retry_after = get_analysis_rate_limiter().acquire()
    if retry_after > 0:
        minutes = max(1, int(retry_after // 60) + 1)
        return False, f"공개 데모의 시간당 분석 한도에 도달했습니다. 약 {minutes}분 후 다시 시도하세요."

    st.session_state["_last_analysis_started_at"] = now
    return True, None


@st.cache_data(ttl=600, max_entries=1000, show_spinner=False)
def cached_keyword_data(keyword: str) -> dict[str, Any]:
    return fetch_keyword_data(keyword, fetcher=get_fetcher())


@st.cache_data(ttl=600, max_entries=100, show_spinner=False)
def cached_related_keywords(seed: str) -> list[dict[str, Any]]:
    return get_fetcher().get_related_keywords(seed)


@st.cache_data(ttl=600, max_entries=1000, show_spinner=False)
def cached_blog_doc_count(keyword: str) -> int:
    return get_fetcher().get_doc_count(keyword)


@st.cache_data(ttl=300, max_entries=20, show_spinner=False)
def cached_trending_topics(limit: int, geo: str) -> list[dict[str, Any]]:
    return fetch_trending_topics(limit=limit, geo=geo)


def source_readiness(fetcher: RealDataFetcher) -> tuple[bool, list[Any]]:
    statuses = fetcher.client.status()
    return all(item.available for item in statuses), statuses


def render_source_status(fetcher: RealDataFetcher) -> bool:
    ready, statuses = source_readiness(fetcher)
    st.sidebar.markdown("### API 자격 증명")
    for item in statuses:
        icon = "✅" if item.available else "⚠️"
        label = {
            "naver_search_ads": "네이버 검색광고",
            "naver_datalab_and_search": "네이버 검색·DataLab",
        }.get(item.source, item.source)
        state = "키 설정됨" if item.available else "키 누락"
        st.sidebar.caption(f"{icon} {label}: {state}")
    if not ready:
        st.sidebar.warning("분석에 필요한 네이버 API 키가 모두 설정되지 않았습니다.")
    return ready


def public_error_detail(exc: SourceError) -> str:
    if exc.status_code in {401, 403}:
        return "인증 또는 API 권한을 확인하세요."
    if exc.status_code == 429:
        return "API 호출 한도에 도달했습니다. 잠시 후 다시 시도하세요."
    if exc.status_code and exc.status_code >= 500:
        return "외부 API가 일시적으로 응답하지 않습니다."
    if "missing credentials" in str(exc):
        return "필요한 API 키가 설정되지 않았습니다."
    if "timed out" in str(exc) or "connection failed" in str(exc):
        return "외부 API 연결 시간이 초과됐습니다."
    if "no exact volume row" in str(exc):
        return "해당 키워드의 정확한 검색량 행이 없어 제외했습니다."
    return "신뢰할 수 있는 응답을 받지 못해 결과에서 제외했습니다."


def append_skipped_failures(
    failures: list[dict[str, Any]],
    keywords: list[str],
    start_index: int,
    exc: SourceError,
) -> None:
    """Explain which keywords were intentionally not called after a circuit trip."""

    for keyword in keywords[start_index:]:
        failures.append(
            {
                "키워드": keyword,
                "출처": exc.source,
                "사유": "동일한 출처 오류가 반복될 수 있어 이번 실행에서는 확인하지 않았습니다.",
            }
        )


def collect_keyword_metrics(
    keywords: Iterable[str],
    fetcher: RealDataFetcher,
    progress_bar: Any,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], bool]:
    unique = list(dict.fromkeys(keyword.strip() for keyword in keywords if keyword.strip()))
    records: list[dict[str, Any]] = []
    failures: list[dict[str, Any]] = []
    interrupted = False
    failure_guard = SourceFailureCircuitBreaker()

    for index, keyword in enumerate(unique):
        try:
            records.append(cached_keyword_data(keyword))
            failure_guard.record_success()
        except SourceError as exc:
            failures.append(
                {"키워드": keyword, "출처": exc.source, "사유": public_error_detail(exc)}
            )
            interrupted = failure_guard.should_abort(exc)
            if interrupted:
                append_skipped_failures(failures, unique, index + 1, exc)
                progress_bar.progress(1.0)
                break
        except (TypeError, ValueError):
            failures.append({"키워드": keyword, "출처": "입력", "사유": "유효하지 않은 키워드입니다."})
        progress_bar.progress((index + 1) / max(len(unique), 1))
    return records, failures, interrupted


def score_records(records: list[dict[str, Any]]) -> pd.DataFrame:
    if not records:
        return pd.DataFrame()
    frame = pd.DataFrame(records)
    frame["Saturation_Index"] = frame.apply(
        lambda row: calculate_saturation(row["Blog_Doc_Count"], row["Monthly_Search_Volume"]),
        axis=1,
    )
    frame["Efficiency_Score"] = frame.apply(
        lambda row: calculate_efficiency(row["Saturation_Index"], row["Monthly_Search_Volume"]),
        axis=1,
    )
    frame["Assessment_Code"] = frame.apply(
        lambda row: classify_keyword(row["Saturation_Index"], row["Monthly_Search_Volume"]),
        axis=1,
    )
    frame["Assessment"] = frame["Assessment_Code"].map(CLASS_LABELS)
    return frame.sort_values(by=["Efficiency_Score", "Monthly_Search_Volume"], ascending=False)


def display_frame(frame: pd.DataFrame) -> pd.DataFrame:
    output = frame[list(DISPLAY_COLUMNS)].copy()
    output["Saturation_Index"] = output["Saturation_Index"].round(3)
    output["Efficiency_Score"] = output["Efficiency_Score"].round(4)
    output["Search_Volume_Censored"] = output["Search_Volume_Censored"].map(
        {True: "예", False: "아니오"}
    )
    return output.rename(columns=DISPLAY_COLUMNS)


def render_failures(failures: list[dict[str, Any]]) -> None:
    if not failures:
        return
    st.warning(f"{len(failures)}개 키워드는 출처 오류 또는 미확인 값 때문에 점수에서 제외했습니다.")
    with st.expander("제외된 키워드와 사유"):
        st.dataframe(pd.DataFrame(failures), width="stretch", hide_index=True)


def render_results(
    frame: pd.DataFrame,
    failures: list[dict[str, Any]],
    csv_name: str,
    empty_message: str | None = None,
) -> None:
    render_failures(failures)
    if frame.empty:
        st.error(
            empty_message
            or "검증 가능한 네이버 데이터가 없습니다. API 설정과 호출 한도를 확인하세요."
        )
        return

    candidates = filter_keywords(frame)
    col1, col2, col3 = st.columns(3)
    col1.metric("검증 완료", len(frame))
    col2.metric(
        "근거 부족/실패",
        len(failures) + int((frame["Assessment_Code"] == "insufficient_data").sum()),
    )
    col3.metric("우선 검토 후보", len(candidates))

    st.subheader("우선 검토 후보")
    st.caption("월간 검색량 50 이상이면서 공급비율 Sk < 5인 항목입니다. 네이버 공식 순위 또는 노출 확률이 아닙니다.")
    if candidates.empty:
        st.info("현재 기준을 충족한 후보가 없습니다.")
    else:
        st.dataframe(display_frame(candidates), width="stretch", hide_index=True)

    with st.expander("검증된 전체 결과", expanded=not bool(len(candidates))):
        st.dataframe(display_frame(frame), width="stretch", hide_index=True)

    csv = display_frame(frame).to_csv(index=False).encode("utf-8-sig")
    st.download_button(
        "결과 CSV 다운로드",
        csv,
        csv_name,
        "text/csv",
        on_click="ignore",
    )


def save_result(
    mode_name: str,
    signature: tuple[Any, ...],
    frame: pd.DataFrame,
    failures: list[dict[str, Any]],
    csv_name: str,
    *,
    context: dict[str, Any] | None = None,
    empty_message: str | None = None,
    max_age_seconds: int = 600,
) -> None:
    stored = dict(st.session_state.get("analysis_results", {}))
    stored[mode_name] = {
        "signature": signature,
        "frame": frame,
        "failures": failures,
        "csv_name": csv_name,
        "context": context or {},
        "empty_message": empty_message,
        "saved_at": datetime.now(timezone.utc).isoformat(),
        "max_age_seconds": max_age_seconds,
    }
    st.session_state["analysis_results"] = stored


def saved_result_is_stale(result: dict[str, Any]) -> bool:
    """Treat missing or malformed provenance as expired, never as fresh."""

    try:
        saved_at = datetime.fromisoformat(str(result["saved_at"]).replace("Z", "+00:00"))
        if saved_at.tzinfo is None:
            saved_at = saved_at.replace(tzinfo=timezone.utc)
        max_age_seconds = int(result["max_age_seconds"])
    except (KeyError, TypeError, ValueError):
        return True
    return (datetime.now(timezone.utc) - saved_at).total_seconds() > max_age_seconds


def render_trend_context(topics: list[dict[str, Any]]) -> None:
    """Keep Google Trends provenance visible across Streamlit reruns."""

    if not topics:
        return
    retrieved_at = topics[0].get("retrieved_at") or "확인 불가"
    st.caption(f"Google Trends RSS 조회 시각: {retrieved_at} (UTC 표기)")
    st.dataframe(
        pd.DataFrame(topics)[["keyword", "approx_traffic", "published_at"]].rename(
            columns={
                "keyword": "급상승 주제",
                "approx_traffic": "Google 추정 검색량",
                "published_at": "게시 시각",
            }
        ),
        width="stretch",
        hide_index=True,
    )


st.set_page_config(page_title="네이버 블로그 주제 기회 탐색기", page_icon="🧭", layout="wide")

st.title("🧭 네이버 블로그 주제 기회 탐색기")
st.markdown(
    """
네이버 공식 API의 **월간 검색량 추정치**와 **블로그 검색 결과 수**를 비교하는 탐색 도구입니다.
`Sk`와 `Ek`는 후보를 좁히기 위한 로컬 보조지표이며, 네이버의 공식 랭킹 점수나 상위 노출 확률이 아닙니다.
"""
)

fetcher = get_fetcher()
naver_ready = render_source_status(fetcher)
st.sidebar.caption("API 응답 캐시: 키워드 10분 · 급상승 주제 5분")
st.sidebar.caption("공개 데모 보호: 세션당 30초 간격 · 전체 시간당 10회")

mode = st.sidebar.selectbox(
    "분석 모드 선택",
    ["모드 A: 기초 키워드 분석", "모드 B: 한국 급상승 주제", "모드 C: 니치 마켓 탐색"],
)
current_signature: tuple[Any, ...]

if mode == "모드 A: 기초 키워드 분석":
    st.header("🔍 기초 키워드 분석")
    st.info("시드 키워드를 검색 의도별 표현으로 확장한 뒤 네이버 데이터로 검증합니다.")
    seed = st.text_input("시드 키워드 입력", value="광주 맛집").strip()
    basic_limit = st.slider("검증할 최대 키워드 수", min_value=10, max_value=30, value=20, step=5)
    current_signature = (seed, basic_limit)

    if not seed:
        st.warning("분석할 키워드를 입력하세요.")
    start_requested = st.button("키워드 분석 시작", disabled=not naver_ready or not seed)
    allowed, limit_message = claim_analysis_slot() if start_requested else (False, None)
    if limit_message:
        st.warning(limit_message)
    if start_requested and allowed:
        with st.status("분석 진행 중...", expanded=True) as status:
            keywords, sub_topics = expand_keyword(seed)
            expanded_count = len(keywords)
            keywords = keywords[:basic_limit]
            if sub_topics:
                st.write(f"확장 주제: {', '.join(sub_topics)}")
            if expanded_count > len(keywords):
                st.caption(
                    f"API 호출량을 제한하기 위해 생성된 {expanded_count}개 중 "
                    f"앞선 {len(keywords)}개를 검증합니다."
                )
            st.write(f"네이버 공식 API로 {len(keywords)}개 키워드를 확인합니다.")
            records, failures, interrupted = collect_keyword_metrics(
                keywords,
                fetcher,
                st.progress(0),
            )
            frame = score_records(records)
            if frame.empty:
                status.update(label="검증 가능한 데이터 없음", state="error")
            elif interrupted:
                status.update(label="출처 오류로 일부 결과만 확인", state="error")
            else:
                status.update(label="분석 완료", state="complete")
        save_result(mode, current_signature, frame, failures, "naver_keyword_analysis.csv")

elif mode == "모드 B: 한국 급상승 주제":
    st.header("📈 한국 급상승 주제 분석")
    st.info("Google Trends 한국 공식 RSS에서 현재 주제를 가져온 뒤 네이버 공식 API로 검색 수요와 블로그 공급을 확인합니다.")
    trend_count = st.slider("급상승 주제 수", min_value=3, max_value=10, value=5)
    variants_per_topic = st.slider("주제당 검증 키워드 수", min_value=1, max_value=5, value=3)
    current_signature = (trend_count, variants_per_topic)

    start_requested = st.button("급상승 주제 분석 시작", disabled=not naver_ready)
    allowed, limit_message = claim_analysis_slot() if start_requested else (False, None)
    if limit_message:
        st.warning(limit_message)
    if start_requested and allowed:
        empty_message: str | None = None
        with st.status("급상승 주제 확인 중...", expanded=True) as status:
            try:
                topics = cached_trending_topics(limit=trend_count, geo="KR")
            except SourceError as exc:
                topics = []
                empty_message = f"Google Trends 한국 RSS를 확인하지 못했습니다. {public_error_detail(exc)}"

            if not topics:
                frame = pd.DataFrame()
                failures = []
                status.update(label="급상승 출처 확인 실패", state="error")
            else:
                targets: list[str] = []
                for topic in topics:
                    expanded, _ = expand_keyword(topic["keyword"])
                    targets.extend(expanded[:variants_per_topic])
                targets = list(dict.fromkeys(targets))
                st.write(f"네이버 API로 {len(targets)}개 후보를 교차 확인합니다.")
                records, failures, interrupted = collect_keyword_metrics(
                    targets,
                    fetcher,
                    st.progress(0),
                )
                frame = score_records(records)
                if frame.empty:
                    status.update(label="네이버 검증 데이터 없음", state="error")
                elif interrupted:
                    status.update(label="출처 오류로 일부 결과만 확인", state="error")
                else:
                    status.update(label="분석 완료", state="complete")
        save_result(
            mode,
            current_signature,
            frame,
            failures,
            "korea_trending_topic_analysis.csv",
            context={"trend_topics": topics},
            empty_message=empty_message,
            max_age_seconds=300,
        )

else:
    st.header("🎯 니치 마켓 탐색")
    st.info("네이버 검색광고의 연관 키워드 중 검색량 상위 항목을 선별해 블로그 검색 결과 수를 확인합니다.")
    seed = st.text_input("분야/주제 입력", value="미국 주식").strip()
    candidate_limit = st.slider("검증할 후보 수", min_value=10, max_value=50, value=30, step=10)
    current_signature = (seed, candidate_limit)

    if not seed:
        st.warning("탐색할 분야나 주제를 입력하세요.")
    start_requested = st.button("니치 마켓 탐색 시작", disabled=not naver_ready or not seed)
    allowed, limit_message = claim_analysis_slot() if start_requested else (False, None)
    if limit_message:
        st.warning(limit_message)
    if start_requested and allowed:
        empty_message: str | None = None
        with st.status("연관 키워드 확인 중...", expanded=True) as status:
            try:
                related = cached_related_keywords(seed)[:candidate_limit]
            except SourceError as exc:
                related = []
                empty_message = f"네이버 검색광고 연관 키워드를 확인하지 못했습니다. {public_error_detail(exc)}"

            records: list[dict[str, Any]] = []
            failures: list[dict[str, Any]] = []
            interrupted = False
            failure_guard = SourceFailureCircuitBreaker()
            progress = st.progress(0)
            for index, item in enumerate(related):
                try:
                    blog_doc_count = cached_blog_doc_count(item["keyword"])
                    records.append(
                        {
                            "Keyword": item["keyword"],
                            "Monthly_Search_Volume": item["volume"],
                            "Search_Volume_Censored": item["volume_censored"],
                            "Blog_Doc_Count": blog_doc_count,
                            "Total_Docs": blog_doc_count,
                        }
                    )
                    failure_guard.record_success()
                except SourceError as exc:
                    failures.append(
                        {
                            "키워드": item["keyword"],
                            "출처": exc.source,
                            "사유": public_error_detail(exc),
                        }
                    )
                    interrupted = failure_guard.should_abort(exc)
                    if interrupted:
                        append_skipped_failures(
                            failures,
                            [row["keyword"] for row in related],
                            index + 1,
                            exc,
                        )
                        progress.progress(1.0)
                        break
                progress.progress((index + 1) / max(len(related), 1))

            frame = score_records(records)
            if not related:
                if empty_message is None:
                    empty_message = (
                        "입력한 주제에서 월간 검색량 추정 100 이상인 연관 키워드를 "
                        "찾지 못했습니다. 다른 시드 키워드로 다시 시도하세요."
                    )
                status.update(label="연관 키워드 데이터 없음", state="error")
            elif frame.empty:
                status.update(label="네이버 검증 데이터 없음", state="error")
            elif interrupted:
                status.update(label="출처 오류로 일부 결과만 확인", state="error")
            else:
                status.update(label="분석 완료", state="complete")
        save_result(
            mode,
            current_signature,
            frame,
            failures,
            "naver_niche_market_analysis.csv",
            empty_message=empty_message,
        )

saved_result = st.session_state.get("analysis_results", {}).get(mode)
if saved_result and saved_result["signature"] == current_signature:
    if saved_result_is_stale(saved_result):
        st.warning("저장된 분석 결과의 유효시간이 지났습니다. 다시 분석해 최신 값을 확인하세요.")
    else:
        render_trend_context(saved_result.get("context", {}).get("trend_topics", []))
        render_results(
            saved_result["frame"],
            saved_result["failures"],
            saved_result["csv_name"],
            saved_result.get("empty_message"),
        )

st.markdown("---")
st.caption("© 2026 Naver Blog Topic Opportunity Explorer")
