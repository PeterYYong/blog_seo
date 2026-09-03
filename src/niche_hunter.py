import sys
import os
import argparse
import time
import pandas as pd
from datetime import datetime

# --- Path Setup ---
current_dir = os.path.dirname(os.path.abspath(__file__))
if not __package__ and current_dir not in sys.path:
    sys.path.append(current_dir)

if __package__:
    from .data_fetcher import RealDataFetcher
    from .calculator import calculate_saturation, calculate_efficiency
    from .seo_sources import SourceError, SourceFailureCircuitBreaker
else:
    from data_fetcher import RealDataFetcher
    from calculator import calculate_saturation, calculate_efficiency
    from seo_sources import SourceError, SourceFailureCircuitBreaker

def main() -> int:
    parser = argparse.ArgumentParser(description="Naver SEO Niche Hunter")
    parser.add_argument("--seed", type=str, required=True, help="Category/Topic to hunt (e.g. '미국 주식')")
    parser.add_argument("--limit", type=int, default=30, help="Maximum related keywords to verify (1-100)")
    args = parser.parse_args()
    
    seed = args.seed.strip()
    if not seed:
        parser.error("--seed must not be empty")
    limit = max(1, min(args.limit, 100))
    print(f"🦈 [Niche Hunter] Hunting in category: '{seed}'")

    # 1. Get Related Keywords
    print("   📡 Fetching popular related keywords...")
    fetcher = RealDataFetcher()
    try:
        related_keywords = fetcher.get_related_keywords(seed)[:limit]
    except SourceError as exc:
        print(f"   ❌ Source unavailable: {exc.source} (status={exc.status_code or 'unknown'})")
        return 1
    
    if not related_keywords:
        print("   ❌ No related keywords found or API error.")
        return 1
        
    print(f"   ✅ Found {len(related_keywords)} candidate keywords (Volume >= 100).")
    
    # 2. Analyze (Doc Count & Metrics)
    print("   📊 Analyzing competition (This may take a while)...")
    results = []
    failure_guard = SourceFailureCircuitBreaker()
    source_failures = 0
    skipped_after_source_abort = 0
    
    total_kws = len(related_keywords)
    for i, item in enumerate(related_keywords):
        kw = item['keyword']
        vol = item['volume']
        
        # Progress bar surrogate
        print(f"      [{i+1}/{total_kws}] Checking '{kw}'...", end="\r")
        
        # Get Doc Count
        try:
            docs = fetcher.get_doc_count(kw)
        except SourceError as exc:
            source_failures += 1
            print(f"excluded ({exc.source}, status={exc.status_code or 'unknown'})")
            if failure_guard.should_abort(exc):
                skipped_after_source_abort = total_kws - i - 1
                print(
                    "   ⛔ 인증·할당량 또는 연속 출처 장애로 남은 "
                    f"{skipped_after_source_abort}개 키워드 조회를 중단합니다."
                )
                break
            continue
        failure_guard.record_success()
        
        # Calculate Metrics
        try:
            sk = calculate_saturation(docs, vol)
            ek = calculate_efficiency(sk, vol)
            
            results.append({
                "Keyword": kw,
                "Monthly_Search_Volume": vol,
                "Search_Volume_Censored": item["volume_censored"],
                "Search_Volume_PC_Raw": item["pc_raw"],
                "Search_Volume_Mobile_Raw": item["mobile_raw"],
                "Total_Docs": docs,
                "Blog_Doc_Count": docs,
                "Saturation_Index": sk,
                "Efficiency_Score": ek
            })
        except (TypeError, ValueError) as exc:
            print(f"excluded (invalid numeric response: {exc})")
            continue
            
    print("\n   ✅ Analysis Complete.")
    
    if not results:
        print("   ❌ No results to report.")
        return 1

    df = pd.DataFrame(results)
    
    # 3. Sections
    # Section 1: High Volume (Hot Topics)
    hot_topics = df.sort_values(by='Monthly_Search_Volume', ascending=False).head(20)
    
    # Section 2: Low legacy supply ratio (Sk < 1.0)
    blue_ocean = df[df['Saturation_Index'] < 1.0].sort_values(by='Efficiency_Score', ascending=False)

    # 4. Reporting
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    os.makedirs('reports', exist_ok=True)
    report_file = f"reports/niche_report_{timestamp}.md"
    
    # Formatting
    for d in [hot_topics, blue_ocean]:
        if not d.empty:
            d['Saturation_Index'] = d['Saturation_Index'].round(2)
            d['Efficiency_Score'] = d['Efficiency_Score'].round(2)

    report_content = f"""# 🦈 Niche Hunter Report: {seed}
**Timestamp:** {timestamp}
**Total Analyzed:** {len(df)} keywords
**Source failures observed:** {source_failures}
**Skipped after source circuit breaker:** {skipped_after_source_abort}

## 1. 🔥 화제의 키워드 (High Volume Top 20)
*People are searching for this right now.*

{hot_topics[['Keyword', 'Monthly_Search_Volume', 'Search_Volume_Censored', 'Search_Volume_PC_Raw', 'Search_Volume_Mobile_Raw', 'Total_Docs', 'Saturation_Index', 'Efficiency_Score']].to_markdown(index=False)}

## 2. 낮은 레거시 공급비율 후보 ($S_k < 1.0$)
*Good volume, Low content supply. Chance to rank!*

{blue_ocean[['Keyword', 'Monthly_Search_Volume', 'Search_Volume_Censored', 'Search_Volume_PC_Raw', 'Search_Volume_Mobile_Raw', 'Total_Docs', 'Saturation_Index', 'Efficiency_Score']].to_markdown(index=False) if not blue_ocean.empty else "No keyword met the local low-supply-ratio threshold."}

> If `Search_Volume_Censored` is `True`, the monthly estimate includes a midpoint for a raw `<10` Search Ads value. Use the PC/mobile raw columns to retain that uncertainty.
"""

    with open(report_file, "w", encoding="utf-8") as f:
        f.write(report_content)
        
    print(f"   📝 Niche Report generated: {report_file}")
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
