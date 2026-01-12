import pandas as pd
import math

def calculate_saturation(doc_count: int, search_volume: int) -> float:
    """
    Calculates the Market Saturation Index (Sk).
    Formula: Sk = Total Docs / Monthly Search Vol
    
    [Safety Logic]
    1. Cut-off: If Search Volume < 50, return 0.0 (Statistically insignificant).
    2. Smoothing: If Search Volume is 0, return 999.0 (High Saturation/Error).
    """
    # 1. Volume Cut-off
    if search_volume < 50:
        return 0.0
        
    # 2. Prevent Division by Zero
    if search_volume == 0:
        return 999.0
        
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
    # 1. Volume Cut-off
    if search_volume < 50:
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
    Filters out keywords where Sk >= 5.0.
    Also handles the case where Sk is 0.0 due to low volume (optional, but strictly kept < 5.0 per user rule).
    
    Expects 'saturation_index' or 'Saturation_Index' column.
    """
    target_col = 'saturation_index'
    if 'Saturation_Index' in df.columns:
        target_col = 'Saturation_Index'
    elif 'saturation_index' not in df.columns:
        # Fallback
        # If no column exists, we can't filter. Return original or raise error.
        # Assuming DataFetcher always provides it via main.py loop.
        raise ValueError("DataFrame must contain 'Saturation_Index' column")
    
    # Filter: Keep only where Sk < 5.0
    # Note: If Sk == 0.0 (Low Volume), it passes this filter.
    # Users should sort by Efficiency to push 0.0 scores to the bottom.
    filtered_df = df[df[target_col] < 5.0].copy()
    
    return filtered_df
