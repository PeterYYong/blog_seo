import sys
import os
import argparse
import time
import pandas as pd
from datetime import datetime

# --- Path Setup ---
current_dir = os.path.dirname(os.path.abspath(__file__))
if current_dir not in sys.path:
    sys.path.append(current_dir)

try:
    from data_fetcher import RealDataFetcher
    from calculator import calculate_saturation, calculate_efficiency
except ImportError:
    sys.path.append(os.path.join(current_dir, ".."))
    from src.data_fetcher import RealDataFetcher
    from src.calculator import calculate_saturation, calculate_efficiency

def main():
    parser = argparse.ArgumentParser(description="Naver SEO Niche Hunter")
    parser.add_argument("--seed", type=str, required=True, help="Category/Topic to hunt (e.g. '미국 주식')")
    args = parser.parse_args()
    
    seed = args.seed
    print(f"🦈 [Niche Hunter] Hunting in category: '{seed}'")

    # 1. Get Related Keywords
    print("   📡 Fetching popular related keywords...")
    fetcher = RealDataFetcher()
    related_keywords = fetcher.get_related_keywords(seed)
    
    if not related_keywords:
        print("   ❌ No related keywords found or API error.")
        return
        
    print(f"   ✅ Found {len(related_keywords)} candidate keywords (Volume >= 100).")
    
    # 2. Analyze (Doc Count & Metrics)
    print("   📊 Analyzing competition (This may take a while)...")
    results = []
    
    total_kws = len(related_keywords)
    for i, item in enumerate(related_keywords):
        kw = item['keyword']
        vol = item['volume']
        
        # Progress bar surrogate
        print(f"      [{i+1}/{total_kws}] Checking '{kw}'...", end="\r")
        
        # Get Doc Count
        docs = fetcher.get_doc_count(kw)
        
        # Calculate Metrics
        try:
            sk = calculate_saturation(docs, vol)
            ek = calculate_efficiency(sk, vol)
            
            results.append({
                "Keyword": kw,
                "Monthly_Search_Volume": vol,
                "Total_Docs": docs,
                "Saturation_Index": sk,
                "Efficiency_Score": ek
            })
        except Exception:
            pass
            
    print("\n   ✅ Analysis Complete.")
    
    if not results:
        print("   ❌ No results to report.")
        return

    df = pd.DataFrame(results)
    
    # 3. Sections
    # Section 1: High Volume (Hot Topics)
    hot_topics = df.sort_values(by='Monthly_Search_Volume', ascending=False).head(20)
    
    # Section 2: Blue Ocean (Sk < 1.0)
    blue_ocean = df[df['Saturation_Index'] < 1.0].sort_values(by='Efficiency_Score', ascending=False)

    # 4. Reporting
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    os.makedirs('reports', exist_ok=True)
    report_file = f"reports/NICHE_{seed.replace(' ', '_')}_{timestamp}.md"
    
    # Formatting
    for d in [hot_topics, blue_ocean]:
        if not d.empty:
            d['Saturation_Index'] = d['Saturation_Index'].round(2)
            d['Efficiency_Score'] = d['Efficiency_Score'].round(2)

    report_content = f"""# 🦈 Niche Hunter Report: {seed}
**Timestamp:** {timestamp}
**Total Analyzed:** {len(df)} keywords

## 1. 🔥 화제의 키워드 (High Volume Top 20)
*People are searching for this right now.*

{hot_topics[['Keyword', 'Monthly_Search_Volume', 'Total_Docs', 'Saturation_Index', 'Efficiency_Score']].to_markdown(index=False)}

## 2. 💎 블루오션 기회 ($S_k < 1.0$)
*Good volume, Low content supply. Chance to rank!*

{blue_ocean[['Keyword', 'Monthly_Search_Volume', 'Total_Docs', 'Saturation_Index', 'Efficiency_Score']].to_markdown(index=False) if not blue_ocean.empty else "No Blue Ocean keywords found in this niche."}
"""

    with open(report_file, "w", encoding="utf-8") as f:
        f.write(report_content)
        
    print(f"   📝 Niche Report generated: {report_file}")

if __name__ == "__main__":
    main()
