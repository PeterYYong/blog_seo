import math

import pandas as pd
import pytest

from src.calculator import (
    calculate_efficiency,
    calculate_saturation,
    classify_keyword,
    filter_keywords,
)


def test_zero_volume_is_not_a_blue_ocean():
    assert math.isinf(calculate_saturation(0, 0))
    assert calculate_efficiency(math.inf, 0) == 0.0
    assert classify_keyword(math.inf, 0) == "insufficient_data"


def test_low_volume_stops_at_the_documented_threshold():
    assert calculate_efficiency(0.5, 49) == 0.0
    assert calculate_efficiency(0.5, 50) > 0.0


@pytest.mark.parametrize(
    ("saturation", "search_volume", "expected"),
    [
        (0.0, 49, "insufficient_data"),
        (math.inf, 50, "insufficient_data"),
        (0.999, 50, "low_supply_ratio"),
        (1.0, 50, "moderate_supply_ratio"),
        (4.999, 50, "moderate_supply_ratio"),
        (5.0, 50, "high_supply_ratio"),
    ],
)
def test_classification_boundaries(saturation, search_volume, expected):
    assert classify_keyword(saturation, search_volume) == expected


@pytest.mark.parametrize(
    ("doc_count", "search_volume"),
    [
        (-1, 100),
        (100, -1),
        (math.nan, 100),
        (100, math.nan),
        (math.inf, 100),
        (100, math.inf),
    ],
)
def test_saturation_rejects_negative_and_nonfinite_inputs(doc_count, search_volume):
    with pytest.raises(ValueError):
        calculate_saturation(doc_count, search_volume)


@pytest.mark.parametrize(
    ("saturation", "search_volume", "conversion_rate"),
    [
        (-0.1, 100, 0.05),
        (0.1, -100, 0.05),
        (math.nan, 100, 0.05),
        (-math.inf, 100, 0.05),
        (0.1, math.inf, 0.05),
        (0.1, 100, math.nan),
        (0.1, 100, 1.01),
    ],
)
def test_efficiency_rejects_invalid_numeric_boundaries(
    saturation,
    search_volume,
    conversion_rate,
):
    with pytest.raises(ValueError):
        calculate_efficiency(saturation, search_volume, conversion_rate)


@pytest.mark.parametrize("value", [True, "100", None])
def test_metric_functions_reject_non_numeric_types(value):
    with pytest.raises(TypeError):
        calculate_saturation(value, 100)
    with pytest.raises(TypeError):
        calculate_efficiency(0.5, value)


def test_filter_excludes_low_volume_even_with_low_ratio():
    frame = pd.DataFrame(
        [
            {"Keyword": "tiny", "Monthly_Search_Volume": 10, "Saturation_Index": 0.1},
            {"Keyword": "usable", "Monthly_Search_Volume": 100, "Saturation_Index": 0.8},
            {"Keyword": "crowded", "Monthly_Search_Volume": 1000, "Saturation_Index": 8.0},
        ]
    )

    result = filter_keywords(frame)

    assert result["Keyword"].tolist() == ["usable"]
