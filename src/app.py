"""Streamlit dashboard for the evidence-first Naver SEO workflow."""

from __future__ import annotations

import os
import secrets
import sys
import time
from collections.abc import Iterable
from datetime import date, datetime, timedelta, timezone
from math import ceil, isfinite
from typing import Any
from urllib.parse import quote
from zoneinfo import ZoneInfo

import pandas as pd
import streamlit as st


current_dir = os.path.dirname(os.path.abspath(__file__))
if current_dir not in sys.path:
    sys.path.append(current_dir)

try:
    from app_auth import (
        AUTH_SESSION_STATE_KEY,
        AuthenticationStatus,
        authenticate_password,
        authenticated_session_is_valid,
        build_authenticated_session,
        get_app_password,
        get_password_throttle_status,
    )
    from calculator import (
        calculate_saturation,
        classify_keyword,
    )
    from candidate_selection import (
        build_reader_topic_angle,
        canonical_keyword_key,
        select_related_keyword_candidates,
    )
    from data_fetcher import RealDataFetcher
    from opportunity import (
        assess_opportunity,
        build_counter_evidence,
        build_why_now,
        calculate_sk_range,
        detect_boundary_sensitivity,
        is_conservative_candidate,
        monthly_volume_range,
        summarize_datalab,
    )
    from rate_limiter import SlidingWindowRateLimiter
    from seo_sources import SourceError, SourceFailureCircuitBreaker
    from trend_hunter import fetch_trending_topics
except ImportError:  # pragma: no cover - package execution path
    sys.path.append(os.path.join(current_dir, ".."))
    from src.app_auth import (
        AUTH_SESSION_STATE_KEY,
        AuthenticationStatus,
        authenticate_password,
        authenticated_session_is_valid,
        build_authenticated_session,
        get_app_password,
        get_password_throttle_status,
    )
    from src.calculator import (
        calculate_saturation,
        classify_keyword,
    )
    from src.candidate_selection import (
        build_reader_topic_angle,
        canonical_keyword_key,
        select_related_keyword_candidates,
    )
    from src.data_fetcher import RealDataFetcher
    from src.opportunity import (
        assess_opportunity,
        build_counter_evidence,
        build_why_now,
        calculate_sk_range,
        detect_boundary_sensitivity,
        is_conservative_candidate,
        monthly_volume_range,
        summarize_datalab,
    )
    from src.rate_limiter import SlidingWindowRateLimiter
    from src.seo_sources import SourceError, SourceFailureCircuitBreaker
    from src.trend_hunter import fetch_trending_topics


CLASS_LABELS = {
    "insufficient_data": "판단 자료 부족",
    "low_supply_ratio": "수요 대비 글 적음",
    "moderate_supply_ratio": "수요 대비 글 보통",
    "high_supply_ratio": "수요 대비 글 많음",
}

DISPLAY_COLUMNS = {
    "Keyword": "키워드",
    "Parent_Topic": "출발 주제",
    "Volume_Tier_Label": "검색량 그룹",
    "Monthly_Search_Volume": "월간 검색량 추정",
    "Search_Volume_Range": "월간 검색량 가능 범위",
    "Search_Volume_PC_Raw": "PC 제공값",
    "Search_Volume_Mobile_Raw": "모바일 제공값",
    "Blog_Doc_Count": "블로그 검색 결과 수",
    "Saturation_Range": "수요 대비 글 수 범위",
    "Trend_Change_Display": "최근 검색 관심 변화",
    "Trend_Direction_Label": "최근 관심 흐름",
    "Boundary_Sensitive_Label": "판단 안정성",
    "Assessment": "해석",
    "Trend_Latest_Period": "검색 관심 기준일",
    "Search_Result_URL": "네이버 블로그 검색",
    "Analyzed_At_Display": "분석 시각(한국시간)",
}

TREND_LABELS = {
    "rising": "↑ 오르는 중",
    "stable": "→ 비슷함",
    "falling": "↓ 내려가는 중",
    "unknown": "데이터 부족",
}

STRATEGY_LABELS = {
    "fast_trend": "빠르게 검토",
    "balanced": "일반 검토",
    "recent_stable": "최근 안정형 검토",
}

CONFIDENCE_LABELS = {
    "high": "높음",
    "medium": "중간",
    "low": "낮음",
    "verification_pending": "외부 출처 확인 전",
}

VOLUME_TIER_LABELS = {
    "high": "목록 내 높은 그룹",
    "mid": "목록 내 중간 그룹",
    "long_tail": "목록 내 낮은 그룹",
}

RESULT_COLUMN_CONFIG = {
    "검색량 그룹": st.column_config.TextColumn(
        help="이번 연관 검색어 목록 안에서 상대적으로 나눈 그룹이며 절대 등급이 아닙니다."
    ),
    "월간 검색량 가능 범위": st.column_config.TextColumn(
        help="네이버가 '<10'처럼 범위로 제공한 값은 가능한 최솟값과 최댓값을 함께 표시합니다."
    ),
    "수요 대비 글 수 범위": st.column_config.TextColumn(
        help=(
            "블로그 검색 결과 수 ÷ 월간 검색량 추정치입니다. 낮을수록 수요에 비해 "
            "누적 글 수가 적다는 뜻이며 검색 노출 난이도는 아닙니다."
        ),
    ),
    "최근 검색 관심 변화": st.column_config.TextColumn(
        help=(
            "네이버 데이터랩의 최근 7일 관심 지수 평균을 이전 28일 평균과 비교합니다. "
            "실제 검색 횟수 증감률은 아닙니다."
        ),
    ),
    "판단 안정성": st.column_config.TextColumn(
        help="검색량이 범위로 제공될 때 가능한 값에 따라 해석이 달라지는지 보여줍니다."
    ),
    "네이버 블로그 검색": st.column_config.LinkColumn(
        display_text="검색 결과 열기"
    ),
}

KST = ZoneInfo("Asia/Seoul")

SESSION_COOLDOWN_SECONDS = 30
GLOBAL_ANALYSIS_LIMIT_PER_HOUR = 10
MIN_APP_PASSWORD_LENGTH = 20
MAX_APP_PASSWORD_LENGTH = 256
DATALAB_MAX_LAG_DAYS = 2


def _streamlit_secrets() -> Any:
    """Return Streamlit secrets without making a missing file an app error."""

    try:
        return st.secrets
    except (FileNotFoundError, RuntimeError):
        return {}


@st.cache_resource(show_spinner=False)
def get_auth_signing_key() -> bytes:
    """Keep an in-memory signer so password changes invalidate existing sessions."""

    return secrets.token_bytes(32)


def require_password_login() -> None:
    """Stop before any API client or analysis UI is created unless authenticated."""

    configured_password = get_app_password(_streamlit_secrets())
    if configured_password is None:
        st.title("🔒 네이버 블로그 주제 기회 탐색기")
        st.error(
            "앱 비밀번호가 설정되지 않아 잠겨 있습니다. "
            "관리자가 Streamlit Secrets에 APP_PASSWORD를 설정해야 합니다."
        )
        st.stop()
    if len(configured_password) < MIN_APP_PASSWORD_LENGTH:
        st.title("🔒 네이버 블로그 주제 기회 탐색기")
        st.error(
            f"APP_PASSWORD가 너무 짧아 앱을 잠갔습니다. "
            f"관리자가 {MIN_APP_PASSWORD_LENGTH}자 이상의 고유한 비밀번호로 바꿔야 합니다."
        )
        st.stop()
    if len(configured_password) > MAX_APP_PASSWORD_LENGTH:
        st.title("🔒 네이버 블로그 주제 기회 탐색기")
        st.error(
            f"APP_PASSWORD가 너무 길어 앱을 잠갔습니다. "
            f"관리자가 {MAX_APP_PASSWORD_LENGTH}자 이하로 바꿔야 합니다."
        )
        st.stop()

    signing_key = get_auth_signing_key()
    session_auth = st.session_state.get(AUTH_SESSION_STATE_KEY)
    if authenticated_session_is_valid(
        session_auth,
        configured_password,
        signing_key,
    ):
        if st.sidebar.button("로그아웃", key="app_logout", use_container_width=True):
            for key in (
                AUTH_SESSION_STATE_KEY,
                "analysis_results",
                "_last_analysis_started_at",
                "_naver_data_fetcher",
            ):
                st.session_state.pop(key, None)
            st.rerun()
        return
    st.session_state.pop(AUTH_SESSION_STATE_KEY, None)

    st.title("🔒 네이버 블로그 주제 기회 탐색기")
    st.caption("허가된 사용자만 이용할 수 있습니다.")
    throttle = get_password_throttle_status(st.session_state)
    if throttle.locked:
        st.warning(
            f"로그인 시도가 잠겼습니다. 약 {max(1, ceil(throttle.retry_after_seconds))}초 후 다시 시도하세요."
        )

    with st.form("app_password_form", clear_on_submit=True):
        candidate = st.text_input(
            "비밀번호",
            type="password",
            max_chars=MAX_APP_PASSWORD_LENGTH,
            disabled=throttle.locked,
            autocomplete="current-password",
        )
        submitted = st.form_submit_button(
            "로그인",
            disabled=throttle.locked,
            use_container_width=True,
        )

    if submitted:
        result = authenticate_password(candidate, configured_password, st.session_state)
        if result.status is AuthenticationStatus.AUTHENTICATED:
            st.session_state[AUTH_SESSION_STATE_KEY] = build_authenticated_session(
                configured_password,
                signing_key,
            )
            st.rerun()
        elif result.status is AuthenticationStatus.LOCKED:
            st.error("비밀번호를 5회 잘못 입력해 5분 동안 로그인이 잠겼습니다.")
        else:
            st.error(
                f"비밀번호가 올바르지 않습니다. 남은 시도 횟수: {result.attempts_remaining}회"
            )
    st.stop()


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
        return False, f"앱의 시간당 분석 한도에 도달했습니다. 약 {minutes}분 후 다시 시도하세요."

    st.session_state["_last_analysis_started_at"] = now
    return True, None


@st.cache_data(ttl=600, max_entries=100, show_spinner=False)
def cached_related_keyword_details(
    seed: str,
    min_volume: int = 0,
    limit: int = 1000,
) -> list[dict[str, Any]]:
    return get_fetcher().get_related_keyword_details(
        seed,
        min_volume=min_volume,
        limit=limit,
    )


@st.cache_data(ttl=600, max_entries=1000, show_spinner=False)
def cached_blog_doc_count(keyword: str) -> int:
    return get_fetcher().get_doc_count(keyword)


@st.cache_data(ttl=300, max_entries=20, show_spinner=False)
def cached_trending_topics(limit: int, geo: str) -> list[dict[str, Any]]:
    return fetch_trending_topics(limit=limit, geo=geo)


@st.cache_data(ttl=900, max_entries=200, show_spinner=False)
def cached_datalab_trends(
    keywords: tuple[str, ...],
    start_date_text: str,
    end_date_text: str,
) -> dict[str, list[dict[str, Any]]]:
    return get_fetcher().client.datalab_trends(
        list(keywords),
        date.fromisoformat(start_date_text),
        date.fromisoformat(end_date_text),
    )


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


def _record_from_related_row(
    row: dict[str, Any],
    blog_doc_count: int,
    *,
    parent_topic: str | None = None,
) -> dict[str, Any]:
    """Convert one canonical Search Ads row into the dashboard record shape."""

    volume = monthly_volume_range(row.get("pc_raw"), row.get("mobile_raw"))
    if int(row.get("monthly_search_estimate", -1)) != volume.estimate:
        raise ValueError("Search Ads estimate does not match its PC/mobile raw values")
    record = {
        "Keyword": str(row["keyword"]).strip(),
        "Monthly_Search_Volume": volume.estimate,
        "Search_Volume_Censored": volume.censored,
        "Search_Volume_PC_Raw": str(row.get("pc_raw", "")),
        "Search_Volume_Mobile_Raw": str(row.get("mobile_raw", "")),
        "Search_Volume_Lower": volume.lower,
        "Search_Volume_Upper": volume.upper,
        "Blog_Doc_Count": int(blog_doc_count),
        "Total_Docs": int(blog_doc_count),
        "Volume_Tier": row.get("volume_tier", ""),
        "Search_Result_URL": (
            "https://search.naver.com/search.naver?where=blog&query="
            f"{quote(str(row['keyword']).strip())}"
        ),
        "Analyzed_At": datetime.now(timezone.utc).isoformat(),
    }
    resolved_parent = parent_topic or row.get("parent_topic")
    if resolved_parent:
        record["Parent_Topic"] = str(resolved_parent)
    return record


def _format_sk_range(value: Any) -> str:
    def format_bound(bound: float) -> str:
        if not isfinite(bound):
            return "계산 불가"
        for threshold in (1.0, 5.0):
            if bound < threshold <= round(bound, 3):
                return f"{threshold:g} 미만(경계 근처)"
        return f"{bound:.3f}배"

    if value.lower == value.upper:
        return format_bound(value.estimate)
    return f"{format_bound(value.lower)}~{format_bound(value.upper)}"


def _format_trend_change(value: Any, direction: str) -> str:
    if direction == "unknown" or value is None or pd.isna(value):
        return "판단 보류"
    numeric = float(value)
    if direction == "stable" and 0 <= numeric < 10 and round(numeric, 1) >= 10:
        return "+10% 미만"
    if direction == "stable" and -10 < numeric < 0 and round(numeric, 1) <= -10:
        return "-10% 초과"
    return f"{numeric:+.1f}%"


def collect_related_keyword_metrics(
    rows: Iterable[dict[str, Any]],
    progress_bar: Any,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], bool]:
    """Fetch Blog Search supply for pre-validated Search Ads rows."""

    selected_rows = list(rows)
    records: list[dict[str, Any]] = []
    failures: list[dict[str, Any]] = []
    interrupted = False
    failure_guard = SourceFailureCircuitBreaker()
    for index, row in enumerate(selected_rows):
        keyword = str(row.get("keyword", "")).strip()
        try:
            blog_doc_count = cached_blog_doc_count(keyword)
            records.append(
                _record_from_related_row(
                    row,
                    blog_doc_count,
                    parent_topic=row.get("parent_topic"),
                )
            )
            failure_guard.record_success()
        except SourceError as exc:
            failures.append(
                {"키워드": keyword, "출처": exc.source, "사유": public_error_detail(exc)}
            )
            interrupted = failure_guard.should_abort(exc)
            if interrupted:
                append_skipped_failures(
                    failures,
                    [str(item.get("keyword", "")) for item in selected_rows],
                    index + 1,
                    exc,
                )
                break
        except (KeyError, TypeError, ValueError):
            failures.append(
                {"키워드": keyword or "확인 불가", "출처": "입력", "사유": "유효하지 않은 후보 데이터입니다."}
            )
        progress_bar.progress((index + 1) / max(len(selected_rows), 1))
    return records, failures, interrupted


def attach_datalab_evidence(
    records: list[dict[str, Any]],
    failures: list[dict[str, Any]],
) -> bool:
    """Attach within-keyword 7-day versus previous-28-day momentum."""

    if not records:
        return False
    keywords = tuple(record["Keyword"] for record in records)
    end_date = datetime.now(KST).date()
    start_date = end_date - timedelta(days=55)
    complete = True
    series_by_keyword: dict[str, list[dict[str, Any]]] = {}
    failed_keywords: set[str] = set()
    failure_guard = SourceFailureCircuitBreaker()
    for offset in range(0, len(keywords), 5):
        batch = keywords[offset : offset + 5]
        try:
            series_by_keyword.update(
                cached_datalab_trends(
                    batch,
                    start_date.isoformat(),
                    end_date.isoformat(),
                )
            )
            failure_guard.record_success()
        except SourceError as exc:
            complete = False
            failed_keywords.update(batch)
            failures.extend(
                {
                    "키워드": keyword,
                    "출처": exc.source,
                    "사유": public_error_detail(exc),
                }
                for keyword in batch
            )
            if failure_guard.should_abort(exc):
                remaining = keywords[offset + len(batch) :]
                failed_keywords.update(remaining)
                append_skipped_failures(
                    failures,
                    list(keywords),
                    offset + len(batch),
                    exc,
                )
                break

    for record in records:
        keyword = record["Keyword"]
        if keyword in failed_keywords:
            record["Trend_Object"] = None
            continue
        points = series_by_keyword.get(keyword)
        if points is None:
            record["Trend_Object"] = None
            complete = False
            failures.append(
                {
                    "키워드": keyword,
                    "출처": "naver_datalab",
                    "사유": "해당 키워드의 DataLab 시계열이 반환되지 않았습니다.",
                }
            )
            continue
        try:
            trend = summarize_datalab(
                points,
                expected_end_date=end_date,
                max_lag_days=DATALAB_MAX_LAG_DAYS,
            )
            record["Trend_Object"] = trend
            if not trend.complete:
                complete = False
                if trend.stale:
                    reason = (
                        f"검색 관심 최신 기준일이 요청 종료일보다 {trend.lag_days}일 오래되어 "
                        "현재 흐름 판단에서 제외했습니다."
                    )
                else:
                    reason = "최근 7일과 이전 28일을 비교할 일별 데이터가 충분하지 않습니다."
                failures.append(
                    {
                        "키워드": keyword,
                        "출처": "naver_datalab",
                        "사유": reason,
                    }
                )
        except (TypeError, ValueError):
            record["Trend_Object"] = None
            complete = False
            failures.append(
                {
                    "키워드": keyword,
                    "출처": "naver_datalab",
                    "사유": "DataLab 시계열이 불완전해 추세를 계산하지 않았습니다.",
                }
            )
    return complete


def score_records(records: list[dict[str, Any]]) -> pd.DataFrame:
    if not records:
        return pd.DataFrame()
    frame = pd.DataFrame(records)
    frame["_Input_Order"] = range(len(frame))
    volume_objects = frame.apply(
        lambda row: monthly_volume_range(
            row["Search_Volume_PC_Raw"],
            row["Search_Volume_Mobile_Raw"],
        ),
        axis=1,
    )
    frame["Volume_Object"] = volume_objects
    frame["Search_Volume_Lower"] = volume_objects.map(lambda value: value.lower)
    frame["Search_Volume_Upper"] = volume_objects.map(lambda value: value.upper)
    frame["Search_Volume_Range"] = volume_objects.map(
        lambda value: (
            f"{value.lower:,}~{value.upper:,}"
            if value.lower != value.upper
            else f"{value.estimate:,}"
        )
    )
    frame["Saturation_Index"] = frame.apply(
        lambda row: calculate_saturation(row["Blog_Doc_Count"], row["Monthly_Search_Volume"]),
        axis=1,
    )
    frame["Sk_Object"] = frame.apply(
        lambda row: calculate_sk_range(row["Blog_Doc_Count"], row["Volume_Object"]),
        axis=1,
    )
    frame["Boundary_Object"] = frame.apply(
        lambda row: detect_boundary_sensitivity(row["Volume_Object"], row["Sk_Object"]),
        axis=1,
    )
    frame["Saturation_Lower"] = frame["Sk_Object"].map(lambda value: value.lower)
    frame["Saturation_Upper"] = frame["Sk_Object"].map(lambda value: value.upper)
    frame["Saturation_Range"] = frame["Sk_Object"].map(_format_sk_range)
    frame["Assessment_Code"] = frame.apply(
        lambda row: classify_keyword(row["Saturation_Index"], row["Monthly_Search_Volume"]),
        axis=1,
    )
    frame["Assessment"] = frame["Assessment_Code"].map(CLASS_LABELS)
    if "Trend_Object" not in frame:
        frame["Trend_Object"] = None
    frame["Trend_Change_Percent"] = frame["Trend_Object"].map(
        lambda value: value.percent_change if value is not None else None
    )
    frame["Trend_Direction"] = frame["Trend_Object"].map(
        lambda value: value.direction if value is not None else "unknown"
    )
    frame["Trend_Direction_Label"] = frame["Trend_Direction"].map(TREND_LABELS)
    frame["Trend_Change_Display"] = frame.apply(
        lambda row: _format_trend_change(
            row["Trend_Change_Percent"], row["Trend_Direction"]
        ),
        axis=1,
    )
    frame["Trend_Latest_Period"] = frame["Trend_Object"].map(
        lambda value: value.latest_period.isoformat()
        if value is not None and value.latest_period is not None
        else ""
    )
    frame["Volume_Tier_Label"] = frame["Volume_Tier"].map(VOLUME_TIER_LABELS).fillna("")
    frame["Boundary_Sensitive"] = frame["Boundary_Object"].map(lambda value: value.sensitive)
    frame["Boundary_Sensitive_Label"] = frame["Boundary_Sensitive"].map(
        {True: "범위에 따라 달라짐", False: "안정"}
    )
    frame.loc[frame["Boundary_Sensitive"], "Assessment"] = (
        frame.loc[frame["Boundary_Sensitive"], "Assessment"]
        + " (가능 범위에 따라 달라짐)"
    )
    frame["Opportunity_Object"] = frame.apply(
        lambda row: assess_opportunity(
            volume=row["Volume_Object"],
            sk=row["Sk_Object"],
            trend=row["Trend_Object"],
            youtube_signal=None,
            boundary_sensitivity=row["Boundary_Object"],
        ),
        axis=1,
    )
    frame["Strategy"] = frame["Opportunity_Object"].map(lambda value: value.strategy)
    frame["Strategy_Label"] = frame["Strategy"].map(STRATEGY_LABELS)
    frame["Confidence"] = frame["Opportunity_Object"].map(lambda value: value.confidence)
    frame["Confidence_Label"] = frame["Confidence"].map(CONFIDENCE_LABELS)
    frame["Recheck_Interval"] = frame["Opportunity_Object"].map(
        lambda value: value.recheck_interval
    )
    frame["Why_Now"] = frame.apply(
        lambda row: build_why_now(
            volume=row["Volume_Object"],
            trend=row["Trend_Object"],
            sk=row["Sk_Object"],
        ),
        axis=1,
    )
    frame["Counter_Evidence"] = frame.apply(
        lambda row: build_counter_evidence(
            volume=row["Volume_Object"],
            trend=row["Trend_Object"],
            sk=row["Sk_Object"],
            boundary_sensitivity=row["Boundary_Object"],
            youtube_signal=None,
        ),
        axis=1,
    )
    trend_priority = {"rising": 3, "stable": 2, "unknown": 1, "falling": 0}
    frame["_Candidate_Eligible"] = frame.apply(
        lambda row: is_conservative_candidate(
            row["Volume_Object"], row["Sk_Object"]
        ),
        axis=1,
    )
    frame["_Trend_Priority"] = frame["Trend_Direction"].map(trend_priority)
    return frame.sort_values(
        by=[
            "_Candidate_Eligible",
            "Boundary_Sensitive",
            "_Trend_Priority",
            "Saturation_Upper",
            "Monthly_Search_Volume",
            "_Input_Order",
        ],
        ascending=[False, True, False, True, False, True],
    )


def display_frame(frame: pd.DataFrame) -> pd.DataFrame:
    available = [column for column in DISPLAY_COLUMNS if column in frame.columns]
    output = frame[available].copy()
    if "Analyzed_At" in frame:
        output["Analyzed_At_Display"] = frame["Analyzed_At"].map(_kst_timestamp)
        available = [column for column in DISPLAY_COLUMNS if column in output.columns]
        output = output[available]
    return output.rename(columns=DISPLAY_COLUMNS)


def render_failures(failures: list[dict[str, Any]]) -> None:
    if not failures:
        return
    st.warning(f"{len(failures)}개 항목의 데이터를 가져오지 못했거나 충분히 확인하지 못했습니다.")
    with st.expander("가져오지 못한 데이터 상세"):
        st.dataframe(pd.DataFrame(failures), width="stretch", hide_index=True)


def _kst_timestamp(raw_value: Any) -> str:
    try:
        parsed = datetime.fromisoformat(str(raw_value).replace("Z", "+00:00"))
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=timezone.utc)
        return parsed.astimezone(KST).strftime("%Y-%m-%d %H:%M KST")
    except (TypeError, ValueError):
        return "확인 불가"


def render_recommendation_cards(
    candidates: pd.DataFrame,
    *,
    naver_evidence_complete: bool,
) -> None:
    st.subheader("먼저 볼 주제 후보")
    st.caption(
        "최대 5개만 표시합니다. 작성 전략과 관심 흐름 구분은 글감 비교용 기준이며 "
        "네이버 공식 순위 또는 노출 확률이 아닙니다."
    )
    if candidates.empty:
        st.info("현재 도구의 보수적 기준을 충족한 후보가 없습니다.")
        return
    if not naver_evidence_complete:
        st.warning(
            "일부 데이터를 가져오지 못했습니다. 아래 순서는 확인된 데이터만으로 정한 임시 순서입니다."
        )

    top_keyword = str(candidates.iloc[0]["Keyword"])
    if naver_evidence_complete:
        st.success(
            f"현재 후보 중 먼저 검토할 항목은 ‘{top_keyword}’입니다. "
            "아래 주의할 점과 실제 검색 결과를 확인한 뒤 글감으로 확정하세요."
        )

    recheck_labels = {"24 hours": "24시간", "7 days": "7일", "30 days": "30일"}
    for rank, (_, row) in enumerate(candidates.head(5).iterrows(), start=1):
        angle = build_reader_topic_angle(str(row["Keyword"]))
        with st.container(border=True):
            st.markdown(
                f"### {rank}. {row['Keyword']}  \n"
                f"**작성 시점: {row['Strategy_Label']}**"
            )
            parent_topic = str(row.get("Parent_Topic", "")).strip()
            if parent_topic:
                st.caption(f"Google 급상승 출발 주제: {parent_topic}")
            st.markdown(
                " · ".join(
                    [
                        f"**월 검색량:** {row['Search_Volume_Range']}",
                        f"**최근 관심:** {row['Trend_Change_Display']} ({row['Trend_Direction_Label']})",
                        f"**수요 대비 글 수:** {row['Saturation_Range']}",
                    ]
                )
            )
            st.markdown(f"**독자 질문**  \n{angle['reader_question']}")
            st.markdown(f"**글의 방향**  \n{angle['topic_angle']}")
            st.markdown(f"**왜 지금 확인할 만한가**  \n{row['Why_Now']}")
            st.markdown(f"**주의할 점·확인 못한 데이터**  \n{row['Counter_Evidence']}")
            st.caption(
                " · ".join(
                    [
                        f"분석: {_kst_timestamp(row.get('Analyzed_At'))}",
                        f"검색 관심 기준일: {row.get('Trend_Latest_Period') or '확인 불가'}",
                        f"재확인: {recheck_labels.get(row['Recheck_Interval'], row['Recheck_Interval'])}",
                        "외부 확인 상태: YouTube 관심 신호 미확인",
                    ]
                )
            )
            st.link_button(
                "네이버 블로그 검색 결과 직접 확인",
                str(row["Search_Result_URL"]),
            )


def render_results(
    frame: pd.DataFrame,
    failures: list[dict[str, Any]],
    csv_name: str,
    empty_message: str | None = None,
    *,
    naver_evidence_complete: bool = True,
) -> None:
    render_failures(failures)
    if frame.empty:
        st.error(
            empty_message
            or "분석할 수 있는 네이버 데이터가 없습니다. API 설정과 호출 한도를 확인하세요."
        )
        return

    candidates = frame.loc[frame["_Candidate_Eligible"]].copy()
    skipped = sum("이번 실행에서는 확인하지 않았습니다" in row.get("사유", "") for row in failures)
    source_failures = len(failures) - skipped
    not_recommended = len(frame) - len(candidates)
    col1, col2, col3, col4 = st.columns(4)
    col1.metric("기본 데이터 확인", len(frame))
    col2.metric("추천 기준 미충족", not_recommended)
    col3.metric("확인 못한 항목", source_failures + skipped)
    col4.metric("추천 후보", len(candidates))

    st.info(
        "숫자 읽기: 월간 검색량은 PC와 모바일 추정치를 합친 값입니다. "
        "‘수요 대비 글 수’가 1이면 월간 검색량과 누적 블로그 검색 결과 수가 비슷한 규모이고, "
        "낮을수록 검색량에 비해 누적 글이 적습니다. ‘최근 관심’은 최근 7일을 이전 28일과 "
        "비교한 상대 변화이며 실제 검색 횟수 증감률은 아닙니다."
    )

    render_recommendation_cards(
        candidates,
        naver_evidence_complete=naver_evidence_complete,
    )

    with st.expander("전체 분석 결과", expanded=not bool(len(candidates))):
        st.dataframe(
            display_frame(frame),
            width="stretch",
            hide_index=True,
            column_config=RESULT_COLUMN_CONFIG,
        )

    st.caption(
        "먼저 보는 순서: 판단 자료가 충분한지 → 값 범위에 따라 판단이 바뀌지 않는지 → "
        "최근 검색 관심 흐름 → 수요 대비 글 수 → 월간 검색량. 네이버 공식 순위가 아닙니다."
    )

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
    naver_evidence_complete: bool = True,
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
        "naver_evidence_complete": naver_evidence_complete,
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
    retrieved_at = _kst_timestamp(topics[0].get("retrieved_at"))
    st.caption(f"Google Trends RSS 조회 시각: {retrieved_at}")
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


def combine_region_and_seed(region: str, seed: str) -> str:
    cleaned_seed = " ".join(seed.split())
    cleaned_region = " ".join(region.split())
    if not cleaned_region:
        return cleaned_seed
    normalized_region = canonical_keyword_key(cleaned_region)
    normalized_seed = canonical_keyword_key(cleaned_seed)
    if normalized_region in normalized_seed:
        return cleaned_seed
    if normalized_seed in normalized_region:
        return cleaned_region
    return f"{cleaned_region} {cleaned_seed}"


def deduplicate_candidate_rows(rows: Iterable[dict[str, Any]]) -> list[dict[str, Any]]:
    output: list[dict[str, Any]] = []
    seen: set[str] = set()
    for row in rows:
        raw_keyword = row.get("keyword", "")
        keyword = canonical_keyword_key(raw_keyword) if isinstance(raw_keyword, str) else ""
        if not keyword or keyword in seen:
            continue
        seen.add(keyword)
        output.append(row)
    return output


st.set_page_config(page_title="네이버 블로그 주제 기회 탐색기", page_icon="🧭", layout="wide")
require_password_login()

st.title("🧭 네이버 블로그 주제 기회 탐색기")
st.markdown(
    """
네이버 공식 API의 **월간 검색량**, **수요 대비 블로그 글 수**, **최근 검색 관심 변화**를 함께 비교해 먼저 검토할 주제를 찾습니다.
결과는 글감 비교용 참고값이며 네이버 공식 순위나 상위 노출 가능성을 예측하지 않습니다.
"""
)

fetcher = get_fetcher()
naver_ready = render_source_status(fetcher)
if not naver_ready:
    st.warning(
        "분석에 필요한 네이버 API 키가 모두 설정되지 않았습니다. "
        "관리자가 Streamlit Secrets의 네이버 자격 증명을 확인해야 합니다."
    )
st.sidebar.caption("API 응답 캐시: 키워드 10분 · 급상승 주제 5분 · DataLab 15분")
st.sidebar.caption("호출 보호: 세션당 30초 간격 · 앱 전체 시간당 10회")

mode = st.sidebar.selectbox(
    "분석 모드 선택",
    ["모드 A: 기초 키워드 분석", "모드 B: 한국 급상승 주제", "모드 C: 니치 마켓 탐색"],
)
current_signature: tuple[Any, ...]

if mode == "모드 A: 기초 키워드 분석":
    st.header("🔍 기초 키워드 분석")
    st.info(
        "임의 단어를 붙이지 않고 네이버가 반환한 실제 연관 검색어를 고른 뒤, "
        "블로그 글 수와 최근 검색 관심 변화로 확인합니다."
    )
    with st.form("basic_analysis_form"):
        seed = st.text_input("시드 키워드 입력", value="광주 맛집").strip()
        region = st.text_input("지역·범위 추가 (선택)", placeholder="예: 광주").strip()
        basic_limit = st.slider(
            "한 번에 분석할 키워드 수", min_value=10, max_value=30, value=20, step=5
        )
        start_requested = st.form_submit_button(
            "키워드 분석 시작",
            disabled=not naver_ready or not seed,
            use_container_width=True,
        )
    discovery_seed = combine_region_and_seed(region, seed)
    current_signature = (discovery_seed, basic_limit)

    if not seed:
        st.warning("분석할 키워드를 입력하세요.")
    allowed, limit_message = claim_analysis_slot() if start_requested else (False, None)
    if limit_message:
        st.warning(limit_message)
    if start_requested and allowed:
        empty_message: str | None = None
        naver_evidence_complete = False
        failures: list[dict[str, Any]] = []
        with st.status("분석 진행 중...", expanded=True) as status:
            try:
                related_pool = cached_related_keyword_details(
                    discovery_seed,
                    min_volume=0,
                    limit=1000,
                )
                selected_rows = select_related_keyword_candidates(
                    related_pool,
                    basic_limit,
                    seed_keyword=discovery_seed,
                )
            except SourceError as exc:
                selected_rows = []
                failures = [
                    {
                        "키워드": discovery_seed,
                        "출처": exc.source,
                        "사유": public_error_detail(exc),
                    }
                ]
                empty_message = "네이버 Search Ads 연관어를 확인하지 못했습니다."

            if selected_rows:
                st.write(
                    f"연관어 {len(related_pool)}개 중 이번 목록의 검색량 높은·중간·낮은 그룹에서 "
                    f"{len(selected_rows)}개를 균형 있게 분석합니다."
                )
                status.update(label=f"블로그 글 수 확인 중 (최대 {len(selected_rows)}개)")
                records, blog_failures, interrupted = collect_related_keyword_metrics(
                    selected_rows,
                    st.progress(0),
                )
                failures = blog_failures
                status.update(label="최근 검색 관심 변화 확인 중")
                datalab_complete = attach_datalab_evidence(records, failures)
                frame = score_records(records)
                naver_evidence_complete = (
                    datalab_complete
                    and not interrupted
                    and len(records) == len(selected_rows)
                )
            else:
                interrupted = False
                frame = pd.DataFrame()
                empty_message = empty_message or (
                    "입력한 시드에서 Search Ads 연관어가 반환되지 않았습니다. "
                    "다른 시드 키워드로 다시 시도하세요."
                )

            if frame.empty:
                status.update(label="분석 가능한 데이터 없음", state="error")
            elif interrupted or not naver_evidence_complete:
                status.update(label="일부 데이터 확인 실패", state="error")
            else:
                status.update(label="분석 완료", state="complete")
        save_result(
            mode,
            current_signature,
            frame,
            failures,
            "naver_keyword_analysis.csv",
            empty_message=empty_message,
            naver_evidence_complete=naver_evidence_complete,
        )

elif mode == "모드 B: 한국 급상승 주제":
    st.header("📈 한국 급상승 주제 분석")
    st.info(
        "Google의 한국 급상승 주제를 출발점으로 삼고, 네이버가 실제 반환한 연관 검색어를 "
        "블로그 글 수와 최근 검색 관심 변화로 다시 확인합니다."
    )
    with st.form("trending_analysis_form"):
        focus = st.text_input(
            "분야·지역 맥락 추가 (선택)",
            placeholder="예: 광주 맛집, 의료 AI",
        ).strip()
        trend_count = st.slider("급상승 주제 수", min_value=3, max_value=10, value=5)
        variants_per_topic = st.slider(
            "주제당 분석할 연관어 수", min_value=1, max_value=5, value=3
        )
        start_requested = st.form_submit_button(
            "급상승 주제 분석 시작",
            disabled=not naver_ready,
            use_container_width=True,
        )
    current_signature = (focus, trend_count, variants_per_topic)

    allowed, limit_message = claim_analysis_slot() if start_requested else (False, None)
    if limit_message:
        st.warning(limit_message)
    if start_requested and allowed:
        empty_message: str | None = None
        naver_evidence_complete = False
        topics: list[dict[str, Any]] = []
        with st.status("급상승 주제 확인 중...", expanded=True) as status:
            try:
                topics = cached_trending_topics(limit=trend_count, geo="KR")
            except SourceError as exc:
                empty_message = (
                    "Google Trends 한국 RSS를 확인하지 못했습니다. "
                    f"{public_error_detail(exc)}"
                )

            failures: list[dict[str, Any]] = []
            selected_rows: list[dict[str, Any]] = []
            candidate_guard = SourceFailureCircuitBreaker()
            candidate_interrupted = False
            candidate_discovery_complete = bool(topics)
            for topic_index, topic in enumerate(topics):
                topic_keyword = str(topic["keyword"])
                discovery_seed = combine_region_and_seed(focus, topic_keyword)
                try:
                    related_pool = cached_related_keyword_details(
                        discovery_seed,
                        min_volume=0,
                        limit=500,
                    )
                    annotated_rows = [
                        {**row, "parent_topic": topic_keyword} for row in related_pool
                    ]
                    selected_rows.extend(
                        select_related_keyword_candidates(
                            annotated_rows,
                            variants_per_topic,
                            seed_keyword=discovery_seed,
                        )
                    )
                    candidate_guard.record_success()
                except SourceError as exc:
                    candidate_discovery_complete = False
                    failures.append(
                        {
                            "키워드": topic_keyword,
                            "출처": exc.source,
                            "사유": public_error_detail(exc),
                        }
                    )
                    candidate_interrupted = candidate_guard.should_abort(exc)
                    if candidate_interrupted:
                        append_skipped_failures(
                            failures,
                            [str(item["keyword"]) for item in topics],
                            topic_index + 1,
                            exc,
                        )
                        break

            selected_rows = deduplicate_candidate_rows(selected_rows)
            if selected_rows:
                st.write(
                    f"{len(topics)}개 급상승 주제에서 실제 연관어 "
                    f"{len(selected_rows)}개를 네이버 데이터로 분석합니다."
                )
                status.update(label=f"블로그 글 수 확인 중 (최대 {len(selected_rows)}개)")
                records, blog_failures, blog_interrupted = collect_related_keyword_metrics(
                    selected_rows,
                    st.progress(0),
                )
                failures.extend(blog_failures)
                status.update(label="최근 검색 관심 변화 확인 중")
                datalab_complete = attach_datalab_evidence(records, failures)
                frame = score_records(records)
                naver_evidence_complete = (
                    datalab_complete
                    and candidate_discovery_complete
                    and not candidate_interrupted
                    and not blog_interrupted
                    and len(records) == len(selected_rows)
                )
            else:
                frame = pd.DataFrame()
                blog_interrupted = False

            if not topics:
                status.update(label="급상승 출처 확인 실패", state="error")
            elif frame.empty:
                empty_message = empty_message or "선택한 급상승 주제에서 분석할 연관어가 없습니다."
                status.update(label="분석 가능한 네이버 데이터 없음", state="error")
            elif not naver_evidence_complete:
                status.update(label="일부 데이터 확인 실패", state="error")
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
            naver_evidence_complete=naver_evidence_complete,
        )

else:
    st.header("🎯 니치 마켓 탐색")
    st.info(
        "검색량 상위 항목만 고르지 않고, 네이버 연관 검색어 목록의 검색량 높은·중간·낮은 "
        "세 그룹에서 균형 있게 선택해 확인합니다."
    )
    with st.form("niche_analysis_form"):
        seed = st.text_input("분야/주제 입력", value="미국 주식").strip()
        region = st.text_input("지역·범위 추가 (선택)", placeholder="예: 한국").strip()
        candidate_limit = st.slider(
            "한 번에 분석할 후보 수", min_value=10, max_value=50, value=30, step=10
        )
        start_requested = st.form_submit_button(
            "니치 마켓 탐색 시작",
            disabled=not naver_ready or not seed,
            use_container_width=True,
        )
    discovery_seed = combine_region_and_seed(region, seed)
    current_signature = (discovery_seed, candidate_limit)

    if not seed:
        st.warning("탐색할 분야나 주제를 입력하세요.")
    allowed, limit_message = claim_analysis_slot() if start_requested else (False, None)
    if limit_message:
        st.warning(limit_message)
    if start_requested and allowed:
        empty_message: str | None = None
        naver_evidence_complete = False
        with st.status("연관 키워드 확인 중...", expanded=True) as status:
            try:
                related_pool = cached_related_keyword_details(
                    discovery_seed,
                    min_volume=0,
                    limit=1000,
                )
                selected_rows = select_related_keyword_candidates(
                    related_pool,
                    candidate_limit,
                    seed_keyword=discovery_seed,
                )
                failures: list[dict[str, Any]] = []
            except SourceError as exc:
                selected_rows = []
                failures = [
                    {
                        "키워드": discovery_seed,
                        "출처": exc.source,
                        "사유": public_error_detail(exc),
                    }
                ]
                empty_message = "네이버 Search Ads 연관어를 확인하지 못했습니다."

            if selected_rows:
                st.write(
                    f"연관어 {len(related_pool)}개 중 이번 목록의 검색량 세 그룹에서 "
                    f"{len(selected_rows)}개를 분석합니다."
                )
                status.update(label=f"블로그 글 수 확인 중 (최대 {len(selected_rows)}개)")
                records, blog_failures, interrupted = collect_related_keyword_metrics(
                    selected_rows,
                    st.progress(0),
                )
                failures.extend(blog_failures)
                status.update(label="최근 검색 관심 변화 확인 중")
                datalab_complete = attach_datalab_evidence(records, failures)
                frame = score_records(records)
                naver_evidence_complete = (
                    datalab_complete
                    and not interrupted
                    and len(records) == len(selected_rows)
                )
            else:
                frame = pd.DataFrame()
                interrupted = False

            if not selected_rows:
                empty_message = empty_message or (
                    "입력한 주제에서 분석할 Search Ads 연관어를 찾지 못했습니다. "
                    "다른 시드 키워드로 다시 시도하세요."
                )
                status.update(label="연관 키워드 데이터 없음", state="error")
            elif frame.empty:
                status.update(label="분석 가능한 네이버 데이터 없음", state="error")
            elif not naver_evidence_complete:
                status.update(label="일부 데이터 확인 실패", state="error")
            else:
                status.update(label="분석 완료", state="complete")
        save_result(
            mode,
            current_signature,
            frame,
            failures,
            "naver_niche_market_analysis.csv",
            empty_message=empty_message,
            naver_evidence_complete=naver_evidence_complete,
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
            naver_evidence_complete=saved_result.get(
                "naver_evidence_complete", False
            ),
        )

st.markdown("---")
st.caption("© 2026 Naver Blog Topic Opportunity Explorer")
