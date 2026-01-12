import sys
import os
import pandas as pd
from datetime import datetime
from src.keyword_expander import expand_keyword
from src.data_fetcher import fetch_metrics
from src.calculator import calculate_saturation, calculate_efficiency, filter_keywords

import argparse

def main():
    parser = argparse.ArgumentParser(description="Naver SEO Keyword Miner")
    parser.add_argument("--seed", type=str, default="캠핑의자", help="Seed keyword for mining")
    args = parser.parse_args()

    print("Initializing Naver Search Ecology Architect Agent...")
    
    # 1. Define Seed Keyword
    seed_keyword = args.seed
    print(f"Seed Keyword: {seed_keyword}")
    
    # 2. Expand Keywords
    print("Expanding keywords (Long-tail mining)...")
    keywords, sub_topics = expand_keyword(seed_keyword)
    
    if sub_topics:
        print(f"*** Auto-Brainstorming Mode Active! ***")
        print(f"Input Broad Topic: '{seed_keyword}' -> Expanded Sub-topics: {sub_topics}")
    
    # 3. Fetch Data (Mock)
    print("Fetching metrics from (Mock) Naver DataLab & Search API...")
    data = []
    for kw in keywords:
        metrics = fetch_metrics(kw)
        data.append(metrics)
        
    df = pd.DataFrame(data)
    
    # 4. Calculate Scores
    print("Calculating Saturation Index (Sk) and Efficiency Score (Ek)...")
    df['saturation_index'] = df.apply(lambda row: calculate_saturation(row['doc_count'], row['search_volume']), axis=1)
    df['efficiency_score'] = df.apply(lambda row: calculate_efficiency(row['saturation_index'], row['search_volume']), axis=1)
    
    # 5. Filter (Constraint: Sk < 5.0)
    print("Filtering keywords (Constraint: Sk < 5.0)...")
    initial_count = len(df)
    df_filtered = filter_keywords(df)
    dropped_count = initial_count - len(df_filtered)
    print(f"Dropped {dropped_count} keywords due to high saturation.")
    
    # 6. Sort by Efficiency (Priority)
    df_filtered = df_filtered.sort_values(by='efficiency_score', ascending=False)
    
    # 7. Generate Report
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    report_filename = f"reports/result_{timestamp}.md"
    
    # Format for readability
    display_df = df_filtered.copy()
    display_df['saturation_index'] = display_df['saturation_index'].round(2)
    display_df['efficiency_score'] = display_df['efficiency_score'].round(2)
    
    markdown_table = display_df[['keyword', 'search_volume', 'doc_count', 'saturation_index', 'efficiency_score', 'smart_block_type']].to_markdown(index=False)
    
    brainstorm_section = ""
    if sub_topics:
        brainstorm_section = f"""
> [!TIP]
> **Auto-Brainstorming Activated**
> You entered a broad topic **'{seed_keyword}'**. System automatically expanded it to:
> {sub_topics}
"""

    report_content = f"""# SEO Keyword Analysis Report
**Timestamp:** {timestamp}
**Seed Keyword:** {seed_keyword}
{brainstorm_section}
## Analysis Summary
- **Total Keywords Analyzed:** {initial_count}
- **Keywords Passed Filter (Sk < 5.0):** {len(df_filtered)}
- **Drop Rate:** {dropped_count / initial_count * 100:.1f}%

## Recommended Keywords (Sorted by Efficiency Ek)

| Note |
| --- |
| **Sk (Saturation Index)** | `< 0.5` Blue Ocean, `0.5 ~ 1.0` Good, `1.0 ~ 5.0` Competitive |
| **Ek (Efficiency Score)** | Higher is better. Balancing volume, conversion, and competition. |

{markdown_table}

## Next Actions
- Select top 3 keywords with high `Ek` and `Sk < 1.0`.
- Create content targeting the identified `SmartBlock Type`.
"""
    
    os.makedirs('reports', exist_ok=True)
    with open(report_filename, "w", encoding="utf-8") as f:
        f.write(report_content)
        
    print(f"Report generated successfully: {report_filename}")

if __name__ == "__main__":
    main()
