import math

import pandas as pd

from src.calculator import calculate_saturation, filter_keywords


def test_zero_volume_is_not_a_blue_ocean():
    assert math.isinf(calculate_saturation(0, 0))


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
