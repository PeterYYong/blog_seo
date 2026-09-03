import math
from numbers import Real
from typing import Literal

import pandas as pd


MIN_MEANINGFUL_VOLUME = 50
LOW_SUPPLY_RATIO_THRESHOLD = 1.0
HIGH_SUPPLY_RATIO_THRESHOLD = 5.0

KeywordClassification = Literal[
    "insufficient_data",
    "low_supply_ratio",
    "moderate_supply_ratio",
    "high_supply_ratio",
]


def _nonnegative_number(
    value: Real,
    name: str,
    *,
    allow_positive_infinity: bool = False,
) -> float:
    """Validate a numeric metric without accepting booleans or NaN values."""

    if isinstance(value, bool) or not isinstance(value, Real):
        raise TypeError(f"{name} must be a real number")

    numeric = float(value)
    if math.isnan(numeric) or numeric == -math.inf:
        raise ValueError(f"{name} must be finite")
    if numeric == math.inf and not allow_positive_infinity:
        raise ValueError(f"{name} must be finite")
    if numeric < 0:
        raise ValueError(f"{name} must be nonnegative")
    return numeric



def calculate_saturation(doc_count: Real, search_volume: Real) -> float:
    """
    Calculate the legacy document-count/search-volume ratio.

    This is a weak content-supply proxy, not a Naver ranking score.  A zero or
    missing search volume must never become a perfect (zero) saturation score.
    """
    documents = _nonnegative_number(doc_count, "doc_count")
    volume = _nonnegative_number(search_volume, "search_volume")
    if volume == 0:
        return math.inf
    return documents / volume


def calculate_efficiency(
    saturation: Real,
    search_volume: Real,
    conversion_rate: Real = 0.05,
) -> float:
    """
    Calculate the backwards-compatible local exploration score ``Ek``.

    ``conversion_rate`` is a historical scaling constant retained for API
    compatibility. It is not an observed conversion rate and must not be
    interpreted as one. The score only ranks rows within the same run.
    """
    ratio = _nonnegative_number(
        saturation,
        "saturation",
        allow_positive_infinity=True,
    )
    volume = _nonnegative_number(search_volume, "search_volume")
    rate = _nonnegative_number(conversion_rate, "conversion_rate")
    if rate > 1:
        raise ValueError("conversion_rate must be between 0 and 1")

    if volume < MIN_MEANINGFUL_VOLUME or math.isinf(ratio):
        return 0.0

    return (rate / (ratio + 1.0)) * math.log10(volume)


def classify_keyword(
    saturation: Real,
    search_volume: Real,
) -> KeywordClassification:
    """Classify the legacy ratio without presenting it as a ranking outcome."""

    ratio = _nonnegative_number(
        saturation,
        "saturation",
        allow_positive_infinity=True,
    )
    volume = _nonnegative_number(search_volume, "search_volume")

    if volume < MIN_MEANINGFUL_VOLUME or math.isinf(ratio):
        return "insufficient_data"
    if ratio < LOW_SUPPLY_RATIO_THRESHOLD:
        return "low_supply_ratio"
    if ratio < HIGH_SUPPLY_RATIO_THRESHOLD:
        return "moderate_supply_ratio"
    return "high_supply_ratio"


def filter_keywords(df: pd.DataFrame) -> pd.DataFrame:
    """
    Apply the legacy heuristic while excluding low/unknown-demand rows.

    The threshold is retained for backwards compatibility only.  Use the
    evidence-first opportunity workflow for recommendations.
    """
    target_col = 'saturation_index'
    if 'Saturation_Index' in df.columns:
        target_col = 'Saturation_Index'
    elif 'saturation_index' not in df.columns:
        # Fallback
        # If no column exists, we can't filter. Return original or raise error.
        # Assuming DataFetcher always provides it via main.py loop.
        raise ValueError("DataFrame must contain 'Saturation_Index' column")
    
    volume_col = None
    for candidate in ("Monthly_Search_Volume", "monthly_search_volume"):
        if candidate in df.columns:
            volume_col = candidate
            break
    if volume_col is None:
        raise ValueError("DataFrame must contain a monthly search-volume column")

    classifications = [
        classify_keyword(saturation, volume)
        for saturation, volume in zip(df[target_col], df[volume_col])
    ]
    keep = [
        classification in {"low_supply_ratio", "moderate_supply_ratio"}
        for classification in classifications
    ]
    filtered_df = df.loc[keep].copy()
    
    return filtered_df
