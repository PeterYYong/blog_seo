"""Transparent, evidence-first helpers for blog topic opportunities.

All thresholds in this module are local editorial rules.  They are not Naver
ranking factors, exposure probabilities, or traffic guarantees.  The module
contains only deterministic, side-effect-free transformations so the caller
can keep source retrieval, caching, and presentation separate.
"""

from __future__ import annotations

import math
import re
import statistics
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from numbers import Real
from typing import Any, Literal, Mapping, Sequence


# These deliberately match the legacy dashboard labels, but remain local
# editorial cut-offs rather than official Naver thresholds.
LOCAL_MIN_MONTHLY_VOLUME = 50
LOCAL_LOW_SUPPLY_RATIO_THRESHOLD = 1.0
LOCAL_HIGH_SUPPLY_RATIO_THRESHOLD = 5.0
LOCAL_TREND_RISING_THRESHOLD_PERCENT = 10.0
LOCAL_TREND_FALLING_THRESHOLD_PERCENT = -10.0


SupplyClassification = Literal[
    "insufficient_data",
    "low_supply_ratio",
    "moderate_supply_ratio",
    "high_supply_ratio",
]
TrendDirection = Literal["rising", "stable", "falling", "unknown"]
EditorialStrategy = Literal["fast_trend", "balanced", "recent_stable"]
EvidenceCompleteness = Literal["complete", "partial", "limited"]
Confidence = Literal["high", "medium", "low", "verification_pending"]


@dataclass(frozen=True)
class VolumeRange:
    """Possible monthly search volume after preserving censored API values."""

    lower: int
    estimate: int
    upper: int
    censored: bool


@dataclass(frozen=True)
class SupplyRatioRange:
    """Range for ``blog result count / monthly search volume`` (legacy Sk)."""

    lower: float
    estimate: float
    upper: float


@dataclass(frozen=True)
class BoundarySensitivity:
    """Whether plausible values can change the local supply classification."""

    sensitive: bool
    possible_classifications: tuple[SupplyClassification, ...]
    crossed_boundaries: tuple[str, ...]


@dataclass(frozen=True)
class TrendSummary:
    """A within-series DataLab comparison using two adjacent local windows."""

    recent_mean: float | None
    previous_mean: float | None
    percent_change: float | None
    direction: TrendDirection
    recent_observations: int
    previous_observations: int
    required_recent_observations: int
    required_previous_observations: int
    complete: bool
    latest_period: date | None
    rising_threshold_percent: float
    falling_threshold_percent: float
    stale: bool = False
    lag_days: int | None = None
    expected_end_date: date | None = None
    max_lag_days: int | None = None


@dataclass(frozen=True)
class OpportunityAssessment:
    """Qualitative editorial decision without a pseudo-precise numeric score."""

    strategy: EditorialStrategy
    recheck_interval: Literal["24 hours", "7 days", "30 days"]
    confidence: Confidence
    evidence_completeness: EvidenceCompleteness
    observed_evidence: tuple[str, ...]
    missing_evidence: tuple[str, ...]
    validation_families: tuple[Literal["naver", "youtube"], ...]
    popular_topic_eligible: bool
    boundary_sensitive: bool


def _finite_nonnegative(value: Real, name: str) -> float:
    if isinstance(value, bool) or not isinstance(value, Real):
        raise TypeError(f"{name} must be a real number")
    numeric = float(value)
    if not math.isfinite(numeric) or numeric < 0:
        raise ValueError(f"{name} must be finite and nonnegative")
    return numeric


def _positive_integer(value: int, name: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise TypeError(f"{name} must be an integer")
    if value < 1:
        raise ValueError(f"{name} must be positive")
    return value


def _count_range(raw_value: Any, name: str) -> VolumeRange:
    """Parse one exact integer or a Search Ads value such as ``'<10'``."""

    if raw_value is None or isinstance(raw_value, bool):
        raise ValueError(f"{name} must be a nonnegative integer or '< N'")

    if isinstance(raw_value, str):
        censored = re.fullmatch(r"\s*<\s*(\d+)\s*", raw_value)
        if censored:
            upper_exclusive = int(censored.group(1))
            if upper_exclusive < 1:
                raise ValueError(f"{name} censored upper bound must be positive")
            upper = upper_exclusive - 1
            # Preserve the existing integer midpoint convention: '<10' => 4.
            return VolumeRange(0, upper // 2, upper, True)
        if not re.fullmatch(r"\s*\d+\s*", raw_value):
            raise ValueError(f"{name} must be a nonnegative integer or '< N'")
        parsed = int(raw_value)
    elif isinstance(raw_value, Real):
        numeric = _finite_nonnegative(raw_value, name)
        parsed = int(numeric)
        if numeric != parsed:
            raise ValueError(f"{name} must be an integer")
    else:
        raise TypeError(f"{name} must be a nonnegative integer or '< N'")

    return VolumeRange(parsed, parsed, parsed, False)


def monthly_volume_range(pc_raw: Any, mobile_raw: Any) -> VolumeRange:
    """Combine raw PC/mobile Search Ads counts without hiding ``'<10'``.

    A censored component ``'<10'`` means 0--9 and uses 4 as the conservative
    integer midpoint estimate, consistent with the existing data client.
    """

    pc = _count_range(pc_raw, "pc_raw")
    mobile = _count_range(mobile_raw, "mobile_raw")
    return VolumeRange(
        lower=pc.lower + mobile.lower,
        estimate=pc.estimate + mobile.estimate,
        upper=pc.upper + mobile.upper,
        censored=pc.censored or mobile.censored,
    )


def _ratio(doc_count: float, volume: int) -> float:
    # Zero demand is unknown/unusable, never a perfect zero supply ratio.
    return math.inf if volume == 0 else doc_count / volume


def calculate_sk_range(
    blog_doc_count: Real,
    volume: VolumeRange,
) -> SupplyRatioRange:
    """Calculate the lower/estimate/upper legacy Sk under volume uncertainty."""

    documents = _finite_nonnegative(blog_doc_count, "blog_doc_count")
    if not isinstance(volume, VolumeRange):
        raise TypeError("volume must be a VolumeRange")
    if not (0 <= volume.lower <= volume.estimate <= volume.upper):
        raise ValueError("volume bounds must satisfy lower <= estimate <= upper")
    return SupplyRatioRange(
        lower=_ratio(documents, volume.upper),
        estimate=_ratio(documents, volume.estimate),
        upper=_ratio(documents, volume.lower),
    )


def supply_ratio_range(
    blog_doc_count: Real,
    volume: VolumeRange,
) -> SupplyRatioRange:
    """Descriptive alias for :func:`calculate_sk_range`."""

    return calculate_sk_range(blog_doc_count, volume)


def _validate_local_classification_thresholds(
    minimum_volume: int,
    low_threshold: Real,
    high_threshold: Real,
) -> tuple[int, float, float]:
    if isinstance(minimum_volume, bool) or not isinstance(minimum_volume, int):
        raise TypeError("minimum_volume must be an integer")
    if minimum_volume < 0:
        raise ValueError("minimum_volume must be nonnegative")
    low = _finite_nonnegative(low_threshold, "low_threshold")
    high = _finite_nonnegative(high_threshold, "high_threshold")
    if low >= high:
        raise ValueError("low_threshold must be less than high_threshold")
    return minimum_volume, low, high


def classify_sk(
    sk: Real,
    monthly_volume: Real,
    *,
    minimum_volume: int = LOCAL_MIN_MONTHLY_VOLUME,
    low_threshold: Real = LOCAL_LOW_SUPPLY_RATIO_THRESHOLD,
    high_threshold: Real = LOCAL_HIGH_SUPPLY_RATIO_THRESHOLD,
) -> SupplyClassification:
    """Apply explicit local Sk categories; this is not a ranking prediction."""

    minimum_volume, low, high = _validate_local_classification_thresholds(
        minimum_volume, low_threshold, high_threshold
    )
    volume = _finite_nonnegative(monthly_volume, "monthly_volume")
    if isinstance(sk, bool) or not isinstance(sk, Real):
        raise TypeError("sk must be a real number")
    ratio = float(sk)
    if math.isnan(ratio) or ratio == -math.inf or ratio < 0:
        raise ValueError("sk must be nonnegative and not NaN")
    if volume < minimum_volume or math.isinf(ratio):
        return "insufficient_data"
    if ratio < low:
        return "low_supply_ratio"
    if ratio < high:
        return "moderate_supply_ratio"
    return "high_supply_ratio"


def is_conservative_candidate(
    volume: VolumeRange,
    sk: SupplyRatioRange,
    *,
    minimum_volume: int = LOCAL_MIN_MONTHLY_VOLUME,
    high_threshold: Real = LOCAL_HIGH_SUPPLY_RATIO_THRESHOLD,
) -> bool:
    """Return whether every plausible value stays inside the reviewable range."""

    if not isinstance(volume, VolumeRange):
        raise TypeError("volume must be a VolumeRange")
    if not isinstance(sk, SupplyRatioRange):
        raise TypeError("sk must be a SupplyRatioRange")
    if isinstance(minimum_volume, bool) or not isinstance(minimum_volume, int):
        raise TypeError("minimum_volume must be an integer")
    if minimum_volume < 0:
        raise ValueError("minimum_volume must be nonnegative")
    high = _finite_nonnegative(high_threshold, "high_threshold")
    return volume.lower >= minimum_volume and sk.upper < high


def detect_boundary_sensitivity(
    volume: VolumeRange,
    sk: SupplyRatioRange,
    *,
    minimum_volume: int = LOCAL_MIN_MONTHLY_VOLUME,
    low_threshold: Real = LOCAL_LOW_SUPPLY_RATIO_THRESHOLD,
    high_threshold: Real = LOCAL_HIGH_SUPPLY_RATIO_THRESHOLD,
) -> BoundarySensitivity:
    """Report all local categories allowed by the supplied uncertainty bounds."""

    minimum_volume, low, high = _validate_local_classification_thresholds(
        minimum_volume, low_threshold, high_threshold
    )
    if not isinstance(volume, VolumeRange):
        raise TypeError("volume must be a VolumeRange")
    if not isinstance(sk, SupplyRatioRange):
        raise TypeError("sk must be a SupplyRatioRange")
    if not (0 <= volume.lower <= volume.estimate <= volume.upper):
        raise ValueError("volume bounds must satisfy lower <= estimate <= upper")
    if any(math.isnan(value) or value < 0 for value in (sk.lower, sk.estimate, sk.upper)):
        raise ValueError("sk bounds must be nonnegative and not NaN")
    if not sk.lower <= sk.estimate <= sk.upper:
        raise ValueError("sk bounds must satisfy lower <= estimate <= upper")

    # Sk and volume are coupled through one document count (Sk = D / V).
    # Combining the lowest volume with the lowest Sk independently can invent
    # classifications that no admissible volume can produce.  Recover D from
    # the corresponding endpoints and validate that the supplied ranges are a
    # coherent pair before considering only the volume range where demand is
    # sufficient.
    document_candidates: list[float] = []
    for ratio, denominator in (
        (sk.lower, volume.upper),
        (sk.estimate, volume.estimate),
        (sk.upper, volume.lower),
    ):
        if denominator == 0:
            if not math.isinf(ratio):
                raise ValueError("sk and volume ranges are not mathematically coupled")
            continue
        if not math.isfinite(ratio):
            raise ValueError("sk and volume ranges are not mathematically coupled")
        document_candidates.append(ratio * denominator)

    document_count: float | None = None
    if document_candidates:
        document_count = document_candidates[0]
        if any(
            not math.isclose(candidate, document_count, rel_tol=1e-9, abs_tol=1e-9)
            for candidate in document_candidates[1:]
        ):
            raise ValueError("sk and volume ranges are not mathematically coupled")
        nearest_integer = round(document_count)
        if math.isclose(document_count, nearest_integer, rel_tol=1e-9, abs_tol=1e-9):
            document_count = float(nearest_integer)

    possible: list[SupplyClassification] = []
    # Volume below the local minimum (and volume zero even if a caller selects
    # a zero minimum) is always insufficient rather than a low-ratio result.
    if volume.lower < minimum_volume or volume.lower == 0:
        possible.append("insufficient_data")

    valid_lower = max(volume.lower, minimum_volume, 1)
    valid_upper = volume.upper
    valid_ratio_lower: float | None = None
    valid_ratio_upper: float | None = None
    if valid_lower <= valid_upper and document_count is not None:
        valid_ratio_lower = document_count / valid_upper
        valid_ratio_upper = document_count / valid_lower
        if valid_ratio_lower < low:
            possible.append("low_supply_ratio")
        if valid_ratio_lower < high and valid_ratio_upper >= low:
            possible.append("moderate_supply_ratio")
        if valid_ratio_upper >= high:
            possible.append("high_supply_ratio")

    # An exact zero-volume interval has no finite category.
    if not possible:
        possible.append("insufficient_data")

    ordered_categories: tuple[SupplyClassification, ...] = tuple(
        category
        for category in (
            "insufficient_data",
            "low_supply_ratio",
            "moderate_supply_ratio",
            "high_supply_ratio",
        )
        if category in possible
    )
    boundaries: list[str] = []
    if volume.lower < minimum_volume <= volume.upper:
        boundaries.append(f"monthly_volume_{minimum_volume}")
    if (
        valid_ratio_lower is not None
        and valid_ratio_upper is not None
        and valid_ratio_lower < low <= valid_ratio_upper
    ):
        boundaries.append(f"sk_{low:g}")
    if (
        valid_ratio_lower is not None
        and valid_ratio_upper is not None
        and valid_ratio_lower < high <= valid_ratio_upper
    ):
        boundaries.append(f"sk_{high:g}")
    return BoundarySensitivity(
        sensitive=len(ordered_categories) > 1,
        possible_classifications=ordered_categories,
        crossed_boundaries=tuple(boundaries),
    )


def classification_is_boundary_sensitive(
    sk: SupplyRatioRange,
    volume: VolumeRange,
    **thresholds: Any,
) -> bool:
    """Boolean convenience wrapper around :func:`detect_boundary_sensitivity`."""

    return detect_boundary_sensitivity(volume, sk, **thresholds).sensitive


def _point_date(raw_period: Any) -> date:
    if isinstance(raw_period, datetime):
        return raw_period.date()
    if isinstance(raw_period, date):
        return raw_period
    if isinstance(raw_period, str):
        try:
            return date.fromisoformat(raw_period.strip())
        except ValueError as exc:
            raise ValueError("DataLab period must be an ISO date") from exc
    raise ValueError("DataLab period must be an ISO date")


def _point_ratio(point: Mapping[str, Any]) -> float:
    if "ratio" not in point:
        raise ValueError("DataLab point is missing ratio")
    ratio = _finite_nonnegative(point["ratio"], "DataLab ratio")
    if ratio > 100:
        raise ValueError("DataLab ratio must be at most 100")
    return ratio


def summarize_datalab(
    points: Sequence[Mapping[str, Any]],
    *,
    recent_days: int = 7,
    previous_days: int = 28,
    rising_threshold_percent: Real = LOCAL_TREND_RISING_THRESHOLD_PERCENT,
    falling_threshold_percent: Real = LOCAL_TREND_FALLING_THRESHOLD_PERCENT,
    expected_end_date: date | datetime | str | None = None,
    max_lag_days: int | None = None,
) -> TrendSummary:
    """Compare recent 7 days with the preceding 28 days by default.

    With API ``period`` fields, windows are calendar based and missing dates
    keep the direction ``unknown``.  Ratio-only test/input series are accepted
    in their supplied chronological order.  Percent change is undefined when
    the previous mean is zero.
    """

    recent_days = _positive_integer(recent_days, "recent_days")
    previous_days = _positive_integer(previous_days, "previous_days")
    rising = float(rising_threshold_percent)
    falling = float(falling_threshold_percent)
    if (
        isinstance(rising_threshold_percent, bool)
        or isinstance(falling_threshold_percent, bool)
        or not isinstance(rising_threshold_percent, Real)
        or not isinstance(falling_threshold_percent, Real)
        or not math.isfinite(rising)
        or not math.isfinite(falling)
    ):
        raise TypeError("trend thresholds must be finite real numbers")
    if falling >= rising:
        raise ValueError("falling threshold must be less than rising threshold")
    if max_lag_days is not None:
        if isinstance(max_lag_days, bool) or not isinstance(max_lag_days, int):
            raise TypeError("max_lag_days must be an integer or None")
        if max_lag_days < 0:
            raise ValueError("max_lag_days must be nonnegative")
        if expected_end_date is None:
            raise ValueError("expected_end_date is required when max_lag_days is set")
    expected_end = (
        _point_date(expected_end_date) if expected_end_date is not None else None
    )
    if isinstance(points, (str, bytes)) or not isinstance(points, Sequence):
        raise TypeError("points must be a sequence of mappings")
    if any(not isinstance(point, Mapping) for point in points):
        raise TypeError("each DataLab point must be a mapping")

    has_period = ["period" in point and point.get("period") is not None for point in points]
    if has_period and any(has_period) and not all(has_period):
        raise ValueError("DataLab periods must be present on all points or none")

    latest_period: date | None = None
    if points and all(has_period):
        dated: dict[date, float] = {}
        for point in points:
            period = _point_date(point["period"])
            if period in dated:
                raise ValueError(f"duplicate DataLab period: {period.isoformat()}")
            dated[period] = _point_ratio(point)
        latest_period = max(dated)
        recent_start = latest_period - timedelta(days=recent_days - 1)
        previous_end = recent_start - timedelta(days=1)
        previous_start = previous_end - timedelta(days=previous_days - 1)
        recent_values = [
            value for period, value in dated.items() if recent_start <= period <= latest_period
        ]
        previous_values = [
            value for period, value in dated.items() if previous_start <= period <= previous_end
        ]
    else:
        if expected_end is not None and max_lag_days is not None:
            raise ValueError("period fields are required for DataLab freshness checks")
        values = [_point_ratio(point) for point in points]
        recent_values = values[-recent_days:]
        before_recent = values[:-recent_days]
        previous_values = before_recent[-previous_days:]

    recent_mean = statistics.fmean(recent_values) if recent_values else None
    previous_mean = statistics.fmean(previous_values) if previous_values else None
    window_complete = (
        len(recent_values) == recent_days and len(previous_values) == previous_days
    )
    lag_days: int | None = None
    stale = False
    if latest_period is not None and expected_end is not None:
        lag_days = (expected_end - latest_period).days
        if lag_days < 0:
            raise ValueError("latest DataLab period cannot be after expected_end_date")
        stale = max_lag_days is not None and lag_days > max_lag_days
    complete = window_complete and not stale
    if previous_mean in (None, 0.0) or recent_mean is None:
        percent_change = None
    else:
        percent_change = (recent_mean - previous_mean) / previous_mean * 100.0

    if not complete or percent_change is None:
        direction: TrendDirection = "unknown"
    elif percent_change >= rising:
        direction = "rising"
    elif percent_change <= falling:
        direction = "falling"
    else:
        direction = "stable"

    return TrendSummary(
        recent_mean=recent_mean,
        previous_mean=previous_mean,
        percent_change=percent_change,
        direction=direction,
        recent_observations=len(recent_values),
        previous_observations=len(previous_values),
        required_recent_observations=recent_days,
        required_previous_observations=previous_days,
        complete=complete,
        latest_period=latest_period,
        rising_threshold_percent=rising,
        falling_threshold_percent=falling,
        stale=stale,
        lag_days=lag_days,
        expected_end_date=expected_end,
        max_lag_days=max_lag_days,
    )


def assign_editorial_strategy(
    trend: TrendSummary | None,
) -> tuple[EditorialStrategy, Literal["24 hours", "7 days", "30 days"]]:
    """Map observed momentum to a strategy and a deliberately short validity."""

    if trend is not None and not isinstance(trend, TrendSummary):
        raise TypeError("trend must be a TrendSummary or None")
    if trend is not None and trend.direction == "rising":
        return "fast_trend", "24 hours"
    if trend is not None and trend.direction == "stable" and trend.complete:
        return "recent_stable", "30 days"
    return "balanced", "7 days"


def assess_opportunity(
    *,
    volume: VolumeRange | None,
    sk: SupplyRatioRange | None,
    trend: TrendSummary | None,
    youtube_signal: bool | None,
    boundary_sensitivity: BoundarySensitivity | bool = False,
) -> OpportunityAssessment:
    """Build a conservative qualitative assessment from named evidence.

    ``youtube_signal=None`` means unavailable, while ``False`` means the source
    was checked but did not support the topic.  Naver endpoints count as one
    validation family, in accordance with the workflow contract.
    """

    if volume is not None and not isinstance(volume, VolumeRange):
        raise TypeError("volume must be a VolumeRange or None")
    if sk is not None and not isinstance(sk, SupplyRatioRange):
        raise TypeError("sk must be a SupplyRatioRange or None")
    if trend is not None and not isinstance(trend, TrendSummary):
        raise TypeError("trend must be a TrendSummary or None")
    if youtube_signal is not None and not isinstance(youtube_signal, bool):
        raise TypeError("youtube_signal must be True, False, or None")
    if isinstance(boundary_sensitivity, BoundarySensitivity):
        boundary_sensitive = boundary_sensitivity.sensitive
    elif isinstance(boundary_sensitivity, bool):
        boundary_sensitive = boundary_sensitivity
    else:
        raise TypeError("boundary_sensitivity must be BoundarySensitivity or bool")

    observed: list[str] = []
    if volume is not None:
        observed.append("naver_search_ads")
    if sk is not None:
        observed.append("naver_blog_search")
    if trend is not None and trend.complete:
        observed.append("naver_datalab")
    if youtube_signal is not None:
        observed.append("youtube")
    required = (
        "naver_search_ads",
        "naver_blog_search",
        "naver_datalab",
        "youtube",
    )
    missing = tuple(item for item in required if item not in observed)
    observed_tuple = tuple(observed)
    if len(observed) == len(required):
        completeness: EvidenceCompleteness = "complete"
    elif len(observed) >= 2:
        completeness = "partial"
    else:
        completeness = "limited"

    naver_support = bool(
        (volume is not None and volume.lower >= LOCAL_MIN_MONTHLY_VOLUME)
        or (
            trend is not None
            and trend.complete
            and trend.direction in {"rising", "stable"}
        )
    )
    families: list[Literal["naver", "youtube"]] = []
    if naver_support:
        families.append("naver")
    if youtube_signal is True:
        families.append("youtube")
    popular_topic_eligible = len(families) == 2
    strategy, recheck = assign_editorial_strategy(trend)

    if not popular_topic_eligible:
        confidence: Confidence = "verification_pending"
    elif (
        completeness == "complete"
        and not boundary_sensitive
        and volume is not None
        and not volume.censored
        and trend is not None
        and trend.direction in {"rising", "stable"}
    ):
        confidence = "high"
    elif completeness in {"complete", "partial"} and not boundary_sensitive:
        confidence = "medium"
    else:
        confidence = "low"

    return OpportunityAssessment(
        strategy=strategy,
        recheck_interval=recheck,
        confidence=confidence,
        evidence_completeness=completeness,
        observed_evidence=observed_tuple,
        missing_evidence=missing,
        validation_families=tuple(families),
        popular_topic_eligible=popular_topic_eligible,
        boundary_sensitive=boundary_sensitive,
    )


def _format_number(value: float) -> str:
    return f"{value:,.0f}" if float(value).is_integer() else f"{value:,.2f}"


def _format_ratio_for_narrative(value: float) -> str:
    for threshold in (
        LOCAL_LOW_SUPPLY_RATIO_THRESHOLD,
        LOCAL_HIGH_SUPPLY_RATIO_THRESHOLD,
    ):
        if value < threshold <= round(value, 2):
            return f"{threshold:g}배 미만"
    return f"{_format_number(value)}배"


def build_why_now(
    *,
    volume: VolumeRange | None,
    trend: TrendSummary | None,
    sk: SupplyRatioRange | None = None,
) -> str:
    """Create source-bounded Korean rationale without promising exposure."""

    reasons: list[str] = []
    if volume is not None:
        if volume.censored:
            reasons.append(
                "네이버 Search Ads 월간 검색량은 "
                f"{volume.estimate:,}회로 추정되며 가능한 범위는 "
                f"{volume.lower:,}~{volume.upper:,}회입니다."
            )
        else:
            reasons.append(
                f"네이버 Search Ads 월간 검색량 추정치는 {volume.estimate:,}회입니다."
            )
    if trend is not None and trend.direction != "unknown" and trend.percent_change is not None:
        direction_text = {"rising": "상승", "stable": "안정", "falling": "하락"}[
            trend.direction
        ]
        if trend.direction == "stable":
            reasons.append(
                "네이버 DataLab 최근 7일 평균은 이전 28일 평균과 비교해 "
                "이 도구의 상승·하락 기준 사이에 있어 비슷한 흐름입니다."
            )
        else:
            reasons.append(
                "네이버 DataLab 최근 7일 평균은 이전 28일 평균보다 "
                f"{abs(trend.percent_change):.1f}% "
                f"{'높아' if trend.percent_change >= 0 else '낮아'} {direction_text} 흐름입니다"
                f"(상승 {trend.rising_threshold_percent:g}% 이상·하락 "
                f"{trend.falling_threshold_percent:g}% 이하는 이 도구의 로컬 기준)."
            )
    if sk is not None and math.isfinite(sk.estimate):
        reasons.append(
            "블로그 검색 결과 수는 월간 검색량 추정치의 약 "
            f"{_format_ratio_for_narrative(sk.estimate)}입니다. 수요 대비 누적 글 수를 보는 "
            "참고값이며 검색 노출 난이도는 아닙니다."
        )
    return " ".join(reasons) or "현재 시점을 뒷받침할 정량 근거가 충분하지 않습니다."


def build_counter_evidence(
    *,
    volume: VolumeRange | None,
    trend: TrendSummary | None,
    sk: SupplyRatioRange | None = None,
    boundary_sensitivity: BoundarySensitivity | bool = False,
    youtube_signal: bool | None = None,
) -> str:
    """Explain missing, weak, or contradictory evidence in Korean."""

    if isinstance(boundary_sensitivity, BoundarySensitivity):
        boundary_sensitive = boundary_sensitivity.sensitive
    elif isinstance(boundary_sensitivity, bool):
        boundary_sensitive = boundary_sensitivity
    else:
        raise TypeError("boundary_sensitivity must be BoundarySensitivity or bool")

    caveats: list[str] = []
    if volume is None:
        caveats.append("Search Ads 월간 검색량 근거가 없습니다.")
    elif volume.censored:
        caveats.append(
            "PC 또는 모바일 검색량이 '<10'처럼 범위로 제공돼 "
            "실제 합계가 표시 범위 안에서 달라질 수 있습니다."
        )
    elif volume.estimate < LOCAL_MIN_MONTHLY_VOLUME:
        caveats.append(
            f"월간 검색량 추정치가 이 도구의 검토 기준 {LOCAL_MIN_MONTHLY_VOLUME}회보다 낮습니다."
        )

    if trend is None:
        caveats.append("최근 검색 관심 흐름을 확인하지 못했습니다.")
    elif trend.stale:
        caveats.append(
            f"최근 검색 관심 기준일이 요청 종료일보다 {trend.lag_days}일 오래되어 "
            "현재 흐름으로 사용하지 않았습니다."
        )
    elif not trend.complete:
        caveats.append(
            "최근 7일과 이전 28일 데이터가 충분히 채워지지 않아 흐름 판단을 보류했습니다."
        )
    elif trend.direction == "unknown":
        caveats.append("직전 DataLab 평균이 0이어서 변화율과 방향을 정의할 수 없습니다.")
    elif trend.direction == "falling":
        caveats.append("DataLab 최근 7일 평균이 직전 28일보다 낮아 하락 근거가 있습니다.")

    if sk is None:
        caveats.append("네이버 블로그 검색 결과 수가 없어 수요 대비 글 수를 확인하지 못했습니다.")
    elif math.isinf(sk.upper):
        caveats.append(
            "월간 검색량의 가능한 최솟값이 0이라 수요 대비 글 수의 "
            "최댓값을 계산할 수 없습니다."
        )
    elif sk.lower >= LOCAL_HIGH_SUPPLY_RATIO_THRESHOLD:
        caveats.append(
            "월간 검색량에 비해 블로그 검색 결과가 많은 편입니다(이 도구 기준)."
        )
    if boundary_sensitive:
        caveats.append(
            "검색량이 범위로 제공되어 수요 대비 글이 적은지 많은지 판단이 달라질 수 있습니다."
        )

    if youtube_signal is None:
        caveats.append("YouTube 교차 검증 근거가 없습니다.")
    elif youtube_signal is False:
        caveats.append("확인한 YouTube 자료에서는 현재 관심을 뒷받침하는 신호가 부족합니다.")

    return " ".join(caveats) or "현재 수집된 범위에서 뚜렷한 반대 근거는 확인되지 않았습니다."


__all__ = [
    "BoundarySensitivity",
    "Confidence",
    "EditorialStrategy",
    "EvidenceCompleteness",
    "LOCAL_HIGH_SUPPLY_RATIO_THRESHOLD",
    "LOCAL_LOW_SUPPLY_RATIO_THRESHOLD",
    "LOCAL_MIN_MONTHLY_VOLUME",
    "LOCAL_TREND_FALLING_THRESHOLD_PERCENT",
    "LOCAL_TREND_RISING_THRESHOLD_PERCENT",
    "OpportunityAssessment",
    "SupplyClassification",
    "SupplyRatioRange",
    "TrendDirection",
    "TrendSummary",
    "VolumeRange",
    "assess_opportunity",
    "assign_editorial_strategy",
    "build_counter_evidence",
    "build_why_now",
    "calculate_sk_range",
    "classification_is_boundary_sensitive",
    "classify_sk",
    "detect_boundary_sensitivity",
    "is_conservative_candidate",
    "monthly_volume_range",
    "summarize_datalab",
    "supply_ratio_range",
]
