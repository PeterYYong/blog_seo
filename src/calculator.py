import pandas as pd
import math


MIN_MEANINGFUL_VOLUME = 50

def calculate_saturation(doc_count: int, search_volume: int) -> float:
    """
    Calculate the legacy document-count/search-volume ratio.

    This is a weak content-supply proxy, not a Naver ranking score.  A zero or
    missing search volume must never become a perfect (zero) saturation score.
    """
    if search_volume <= 0:
        return math.inf
    return doc_count / search_volume

def calculate_efficiency(saturation: float, search_volume: int, conversion_rate: float = 0.05) -> float:
    """
    Calculates the Efficiency Score (Ek).
    Formula: Ek = (Conversion Rate / (Sk + 1.0)) * log10(Search Vol)
    
    [Safety Logic]
    1. Cut-off: If Search Volume < 50, return 0.0.
    2. Smoothing: Denominator uses (Sk + 1.0) to prevent division by zero if Sk=0.
    3. Log Safety: Uses math.log10(max(search_volume, 1)).
    """
    if search_volume < MIN_MEANINGFUL_VOLUME or not math.isfinite(saturation):
        return 0.0
        
    # 3. Log Safety & Formula Application
    # Ek = (CR / (Sk + 1.0)) * log10(Vol)
    try:
        log_val = math.log10(max(search_volume, 1))
        score = (conversion_rate / (saturation + 1.0)) * log_val
        return score
    except Exception:
        return 0.0

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

    filtered_df = df[
        (df[volume_col] >= MIN_MEANINGFUL_VOLUME)
        & df[target_col].map(math.isfinite)
        & (df[target_col] < 5.0)
    ].copy()
    
    return filtered_df
