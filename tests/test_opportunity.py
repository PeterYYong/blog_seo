import math
from dataclasses import FrozenInstanceError
from datetime import date, timedelta

import pytest

from src.opportunity import (
    BoundarySensitivity,
    SupplyRatioRange,
    VolumeRange,
    assess_opportunity,
    assign_editorial_strategy,
    build_counter_evidence,
    build_why_now,
    calculate_sk_range,
    classification_is_boundary_sensitive,
    classify_sk,
    detect_boundary_sensitivity,
    is_conservative_candidate,
    monthly_volume_range,
    summarize_datalab,
)


def test_monthly_volume_range_preserves_channel_censoring():
    assert monthly_volume_range("100", "200") == VolumeRange(300, 300, 300, False)
    assert monthly_volume_range("100", " < 10 ") == VolumeRange(100, 104, 109, True)
    assert monthly_volume_range("<10", "<10") == VolumeRange(0, 8, 18, True)


@pytest.mark.parametrize("value", [None, True, -1, 1.5, "-1", "ten", "<0"])
def test_monthly_volume_range_rejects_invalid_counts(value):
    with pytest.raises((TypeError, ValueError)):
        monthly_volume_range(value, 10)


def test_sk_range_reverses_denominator_bounds_and_keeps_zero_as_infinite():
    assert calculate_sk_range(180, VolumeRange(100, 150, 200, True)) == (
        SupplyRatioRange(0.9, 1.2, 1.8)
    )

    unbounded = calculate_sk_range(180, monthly_volume_range("<10", "<10"))
    assert unbounded.lower == 10
    assert unbounded.estimate == 22.5
    assert math.isinf(unbounded.upper)

    no_demand = calculate_sk_range(0, VolumeRange(0, 0, 0, False))
    assert all(math.isinf(value) for value in no_demand.__dict__.values())


@pytest.mark.parametrize(
    ("sk", "volume", "expected"),
    [
        (0.1, 49, "insufficient_data"),
        (0.999, 50, "low_supply_ratio"),
        (1.0, 50, "moderate_supply_ratio"),
        (4.999, 50, "moderate_supply_ratio"),
        (5.0, 50, "high_supply_ratio"),
        (math.inf, 50, "insufficient_data"),
    ],
)
def test_classify_sk_uses_explicit_inclusive_local_boundaries(sk, volume, expected):
    assert classify_sk(sk, volume) == expected


def test_boundary_sensitivity_reports_volume_and_sk_flips():
    volume = VolumeRange(49, 50, 59, True)
    result = detect_boundary_sensitivity(
        volume,
        calculate_sk_range(50, volume),
    )

    assert result == BoundarySensitivity(
        sensitive=True,
        possible_classifications=(
            "insufficient_data",
            "low_supply_ratio",
            "moderate_supply_ratio",
        ),
        crossed_boundaries=("monthly_volume_50", "sk_1"),
    )
    assert classification_is_boundary_sensitive(
        calculate_sk_range(50, volume),
        volume,
    )


def test_censoring_inside_one_class_is_not_boundary_sensitive():
    volume = VolumeRange(100, 104, 109, True)
    result = detect_boundary_sensitivity(
        volume,
        calculate_sk_range(220, volume),
    )

    assert result.sensitive is False
    assert result.possible_classifications == ("moderate_supply_ratio",)
    assert result.crossed_boundaries == ()


def test_boundary_sensitivity_keeps_sk_and_volume_mathematically_coupled():
    volume = VolumeRange(49, 53, 58, True)
    sk = calculate_sk_range(49, volume)

    result = detect_boundary_sensitivity(volume, sk)

    assert result.sensitive is True
    assert result.possible_classifications == (
        "insufficient_data",
        "low_supply_ratio",
    )
    assert result.crossed_boundaries == ("monthly_volume_50",)


def test_boundary_sensitivity_preserves_exact_threshold_after_float_recovery():
    volume = VolumeRange(43, 52, 61, True)
    result = detect_boundary_sensitivity(volume, calculate_sk_range(250, volume))

    assert result.possible_classifications == (
        "insufficient_data",
        "moderate_supply_ratio",
        "high_supply_ratio",
    )
    assert "sk_5" in result.crossed_boundaries


def test_boundary_sensitivity_rejects_incoherent_independent_ranges():
    with pytest.raises(ValueError, match="mathematically coupled"):
        detect_boundary_sensitivity(
            VolumeRange(49, 53, 58, True),
            SupplyRatioRange(0.8, 1.0, 1.2),
        )


def test_conservative_candidate_requires_every_plausible_value_to_be_reviewable():
    exact = VolumeRange(100, 100, 100, False)
    assert is_conservative_candidate(exact, calculate_sk_range(400, exact)) is True
    assert is_conservative_candidate(exact, calculate_sk_range(500, exact)) is False

    uncertain = VolumeRange(49, 53, 58, True)
    assert is_conservative_candidate(uncertain, calculate_sk_range(49, uncertain)) is False


def _dated_points(previous_value=10.0, recent_value=20.0):
    start = date(2026, 7, 31)
    values = [previous_value] * 28 + [recent_value] * 7
    return [
        {"period": (start + timedelta(days=index)).isoformat(), "ratio": value}
        for index, value in enumerate(values)
    ]


def test_datalab_summary_sorts_dates_and_compares_7_days_to_previous_28():
    points = list(reversed(_dated_points()))
    original = [dict(point) for point in points]

    summary = summarize_datalab(points)

    assert summary.recent_mean == 20
    assert summary.previous_mean == 10
    assert summary.percent_change == 100
    assert summary.direction == "rising"
    assert summary.complete is True
    assert summary.recent_observations == 7
    assert summary.previous_observations == 28
    assert summary.latest_period == date(2026, 9, 3)
    assert points == original


@pytest.mark.parametrize(
    ("recent_value", "expected_direction"),
    [(11.0, "rising"), (10.999, "stable"), (9.001, "stable"), (9.0, "falling")],
)
def test_datalab_local_direction_thresholds_are_inclusive(
    recent_value, expected_direction
):
    summary = summarize_datalab(_dated_points(recent_value=recent_value))

    assert summary.direction == expected_direction
    assert summary.rising_threshold_percent == 10
    assert summary.falling_threshold_percent == -10


def test_datalab_missing_calendar_day_keeps_direction_unknown():
    points = _dated_points()
    points.pop(-3)

    summary = summarize_datalab(points)

    assert summary.complete is False
    assert summary.recent_observations == 6
    assert summary.direction == "unknown"


def test_datalab_zero_previous_mean_has_no_invented_percentage():
    summary = summarize_datalab(_dated_points(previous_value=0, recent_value=20))

    assert summary.percent_change is None
    assert summary.direction == "unknown"


def test_datalab_stale_complete_windows_are_not_treated_as_current():
    summary = summarize_datalab(
        _dated_points(),
        expected_end_date=date(2026, 9, 10),
        max_lag_days=2,
    )

    assert summary.recent_observations == 7
    assert summary.previous_observations == 28
    assert summary.stale is True
    assert summary.lag_days == 7
    assert summary.complete is False
    assert summary.direction == "unknown"


def test_datalab_freshness_allows_the_local_two_day_lag():
    summary = summarize_datalab(
        _dated_points(),
        expected_end_date="2026-09-05",
        max_lag_days=2,
    )

    assert summary.stale is False
    assert summary.lag_days == 2
    assert summary.complete is True
    assert summary.direction == "rising"


def test_datalab_freshness_validation_requires_dated_points_and_expected_end():
    with pytest.raises(ValueError, match="expected_end_date"):
        summarize_datalab(_dated_points(), max_lag_days=2)
    with pytest.raises(ValueError, match="period fields"):
        summarize_datalab(
            [{"ratio": 10}] * 35,
            expected_end_date=date(2026, 9, 3),
            max_lag_days=2,
        )


def test_datalab_rejects_duplicate_dates_and_bad_ratios():
    duplicate = _dated_points()
    duplicate.append(dict(duplicate[-1]))
    with pytest.raises(ValueError, match="duplicate"):
        summarize_datalab(duplicate)
    with pytest.raises(ValueError):
        summarize_datalab([{"period": "2026-09-03", "ratio": math.nan}])
    with pytest.raises((TypeError, ValueError)):
        summarize_datalab([{"period": "2026-09-03", "ratio": True}])
    with pytest.raises(ValueError, match="at most 100"):
        summarize_datalab([{"period": "2026-09-03", "ratio": 100.01}])


def test_strategy_recheck_and_confidence_stay_conservative():
    rising = summarize_datalab(_dated_points())
    stable = summarize_datalab(_dated_points(recent_value=10.5))
    assert assign_editorial_strategy(rising) == ("fast_trend", "24 hours")
    assert assign_editorial_strategy(stable) == ("recent_stable", "30 days")
    assert assign_editorial_strategy(None) == ("balanced", "7 days")

    exact_volume = monthly_volume_range(100, 200)
    sk = calculate_sk_range(100, exact_volume)
    supported = assess_opportunity(
        volume=exact_volume,
        sk=sk,
        trend=rising,
        youtube_signal=True,
    )
    assert supported.strategy == "fast_trend"
    assert supported.recheck_interval == "24 hours"
    assert supported.evidence_completeness == "complete"
    assert supported.confidence == "high"
    assert supported.validation_families == ("naver", "youtube")
    assert supported.popular_topic_eligible is True

    naver_only = assess_opportunity(
        volume=exact_volume,
        sk=sk,
        trend=rising,
        youtube_signal=None,
    )
    assert naver_only.confidence == "verification_pending"
    assert naver_only.popular_topic_eligible is False
    assert naver_only.missing_evidence == ("youtube",)

    negligible_naver_signal = assess_opportunity(
        volume=VolumeRange(1, 1, 1, False),
        sk=SupplyRatioRange(100, 100, 100),
        trend=None,
        youtube_signal=True,
    )
    assert negligible_naver_signal.validation_families == ("youtube",)
    assert negligible_naver_signal.popular_topic_eligible is False


def test_censoring_and_boundary_sensitivity_prevent_high_confidence():
    volume = VolumeRange(49, 50, 59, True)
    sk = calculate_sk_range(50, volume)
    boundary = detect_boundary_sensitivity(volume, sk)

    result = assess_opportunity(
        volume=volume,
        sk=sk,
        trend=summarize_datalab(_dated_points()),
        youtube_signal=True,
        boundary_sensitivity=boundary,
    )

    assert result.confidence == "low"
    assert result.boundary_sensitive is True


def test_explanations_are_evidence_bounded_and_surface_counter_evidence():
    volume = monthly_volume_range("<10", "<10")
    sk = calculate_sk_range(100, volume)
    trend = summarize_datalab(_dated_points()[:-1])
    boundary = detect_boundary_sensitivity(volume, sk)

    why_now = build_why_now(volume=volume, trend=trend, sk=sk)
    counter = build_counter_evidence(
        volume=volume,
        trend=trend,
        sk=sk,
        boundary_sensitivity=boundary,
        youtube_signal=None,
    )

    assert "가능한 범위" in why_now
    assert "누적 글 수" in why_now
    assert "순위" not in why_now
    assert "범위로 제공" in counter
    assert "충분히 채워지지 않아" in counter
    assert "YouTube" in counter
    assert "보장" not in why_now + counter


def test_explanations_do_not_round_across_editorial_boundaries():
    nearly_rising = summarize_datalab(_dated_points(recent_value=10.996))
    trend_text = build_why_now(
        volume=VolumeRange(100, 100, 100, False),
        trend=nearly_rising,
    )
    ratio_text = build_why_now(
        volume=VolumeRange(10_000, 10_000, 10_000, False),
        trend=None,
        sk=SupplyRatioRange(0.9996, 0.9996, 0.9996),
    )

    assert nearly_rising.direction == "stable"
    assert "비슷한 흐름" in trend_text
    assert "10.0%" not in trend_text
    assert "1배 미만" in ratio_text
    assert "1.00배" not in ratio_text


def test_result_models_are_immutable():
    result = monthly_volume_range("<10", 100)
    with pytest.raises(FrozenInstanceError):
        result.estimate = 999
