import sys
import os
import requests
from bs4 import BeautifulSoup
import pandas as pd
import time
from datetime import datetime

# --- Path Setup ---
current_dir = os.path.dirname(os.path.abspath(__file__))
if current_dir not in sys.path:
    sys.path.append(current_dir)

try:
    from keyword_expander import expand_keyword
    from data_fetcher import fetch_keyword_data
    from calculator import calculate_saturation, calculate_efficiency, filter_keywords
except ImportError:
    # Handle running from root
    sys.path.append(os.path.join(current_dir, ".."))
    from src.keyword_expander import expand_keyword
    from src.data_fetcher import fetch_keyword_data
    from src.calculator import calculate_saturation, calculate_efficiency, filter_keywords

def fetch_trending_keywords(limit: int = 5):
    """
    Scrapes trending keywords from Signal.bz.
    Returns Top N keywords.
    """
    url = "https://signal.bz/news"
    print(f"   📡 Scraping trends from {url}...")
    
    try:
        response = requests.get(url, timeout=10)
        response.raise_for_status()
        
        soup = BeautifulSoup(response.text, "html.parser")
        
        keywords = []
        rankings = soup.select(".ranking")
        
        for r in rankings:
            text = r.get_text(strip=True)
            # Remove leading numbers/dots (e.g., "1. Samsung")
            clean_text = ''.join([c for c in text if not c.isdigit() and c != '.']).strip()
            if clean_text and clean_text not in keywords:
                keywords.append(clean_text)
                
        if not keywords:
             print("   ⚠️ Scraper found empty list. Using fallback.")
             # Fallback
             return ["삼성전자", "손흥민", "비트코인", "날씨", "환율"][:limit]
            
        return keywords[:limit]
        
    except Exception as e:
        print(f"   ❌ Scraper Error: {e}")
        # Fallback
        return ["삼성전자", "손흥민", "비트코인", "날씨", "환율"][:limit]

def main():
    print("🌊 [Trend Deep Diver] Starting Analysis...")
    
    # 1. Crawl Top 5
    trends = fetch_trending_keywords(limit=5)
    print(f"   🔥 Identified Top 5 Trends: {trends}")
    
    # 2. Expand (Deep Dive)
    print("   🧠 Expanding trends into sub-topics...")
    all_targets = set()
    for trend in trends:
        # expand_keyword returns (list, sub_topics)
        expanded_list, _ = expand_keyword(trend)
        all_targets.update(expanded_list)
        
    unique_targets = list(all_targets)
    print(f"   🚀 Total Keywords to Analyze: {len(unique_targets)} (Duplicates removed)")
    
    # 3. Analyze (Real API)
    print(f"   📡 Connecting to Naver API...")
    data = []
    
    for i, kw in enumerate(unique_targets):
        print(f"      [{i+1}/{len(unique_targets)}] Analyzing '{kw}'...", end="\r")
        try:
            metrics = fetch_keyword_data(kw)
            if metrics:
                data.append(metrics)
        except Exception as e:
            # print(f"\n      ❌ Error: {e}")
            pass
        time.sleep(0.1) # Rate Limit
        
    print("\n   ✅ Data Collection Complete.")
    
    if not data:
        print("   ❌ No data available.")
        return

    df = pd.DataFrame(data)
    
    # 4. Calculation
    print("   🧮 Calculating Sk & Ek...")
    try:
        df['Saturation_Index'] = df.apply(lambda row: calculate_saturation(row['Total_Docs'], row['Monthly_Search_Volume']), axis=1)
        df['Efficiency_Score'] = df.apply(lambda row: calculate_efficiency(row['Saturation_Index'], row['Monthly_Search_Volume']), axis=1)
    except KeyError as e:
        print(f"   ❌ Calculation Error (Keys): {e}")
        return

    # 5. Filter (Blue Ocean only)
    # Using manual mask for clear variable names, or reuse filter_keywords if compatible
    blue_ocean = df[df['Saturation_Index'] < 5.0].copy()
    
    # Sort
    blue_ocean = blue_ocean.sort_values(by='Efficiency_Score', ascending=False)
    
    # 6. Reporting
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    os.makedirs('reports', exist_ok=True)
    report_file = f"reports/DEEP_DIVE_{timestamp}.md"
    
    # Rounding
    if not blue_ocean.empty:
        blue_ocean['Saturation_Index'] = blue_ocean['Saturation_Index'].round(2)
        blue_ocean['Efficiency_Score'] = blue_ocean['Efficiency_Score'].round(2)

    try:
        table_md = blue_ocean[['Keyword', 'Monthly_Search_Volume', 'Total_Docs', 'Saturation_Index', 'Efficiency_Score', 'SmartBlock_Type']].to_markdown(index=False)
    except ImportError:
        table_md = blue_ocean.to_string()
    except KeyError:
         # Fallback if columns missing
         table_md = blue_ocean.to_markdown()

    report_content = f"""# 🌊 실시간 트렌드 딥 다이브 리포트
**Timestamp:** {timestamp}
**Source:** Signal.bz -> Naver API

## 1. 🔍 Analysis Context
- **Base Trends:** {', '.join(trends)}
- **Total Keywords Scanned:** {len(unique_targets)}
- **Blue Ocean Found:** {len(blue_ocean)}

## 2. 🏆 Blue Ocean Opportunities ($S_k < 5.0$)
*Sorted by Efficiency Score ($E_k$). Higher is better.*

{table_md if not blue_ocean.empty else "No Blue Ocean keywords found (All highly competitive)."}

## 3. 💡 Strategy
- Pick the top keywords from the list above.
- Ensure content addresses the specific intent (e.g. 'Review', 'How-to' implied by suffixes).
- If list is empty, the trends are currently 'Red Ocean'. Consider targeting niche sub-questions not yet covered.
"""

    with open(report_file, "w", encoding="utf-8") as f:
        f.write(report_content)
        
    print(f"   📝 Deep Dive Report generated: {report_file}")

if __name__ == "__main__":
    main()
