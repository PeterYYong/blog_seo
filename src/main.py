import sys
import os
import pandas as pd
import argparse
from datetime import datetime

# --- 경로 설정 (가장 중요) ---
# 현재 파일(main.py)의 위치를 강제로 시스템 경로에 추가합니다.
# 이렇게 하면 "src." 같은 접두사 없이 그냥 파일 이름만 부르면 됩니다.
current_dir = os.path.dirname(os.path.abspath(__file__))
if not __package__ and current_dir not in sys.path:
    sys.path.append(current_dir)

try:
    if __package__:
        from .keyword_expander import expand_keyword
        from .data_fetcher import RealDataFetcher, fetch_keyword_data
        from .calculator import calculate_saturation, calculate_efficiency, filter_keywords
        from .seo_sources import SourceError, SourceFailureCircuitBreaker
    else:
        # Support ``python src/main.py`` without installing the package.
        from keyword_expander import expand_keyword
        from data_fetcher import RealDataFetcher, fetch_keyword_data
        from calculator import calculate_saturation, calculate_efficiency, filter_keywords
        from seo_sources import SourceError, SourceFailureCircuitBreaker
except ImportError as e:
    print(f"❌ 모듈 로딩 실패: {e}")
    print(f"현재 'src' 폴더 안에 다음 파일들이 있는지 확인해주세요:")
    print(f" - keyword_expander.py")
    print(f" - data_fetcher.py")
    print(f" - calculator.py")
    sys.exit(1)

def main() -> int:
    parser = argparse.ArgumentParser(description="Naver SEO Keyword Miner (Real Data Mode)")
    parser.add_argument("--seed", type=str, default="캠핑의자", help="Seed keyword for mining")
    parser.add_argument("--limit", type=int, default=30, help="Maximum keywords to verify (1-100)")
    args = parser.parse_args()

    print(f"🤖 [Legacy Keyword Ratio Tool] 시작...")
    print("   ⚠️ Sk/Ek are local heuristics, not Naver ranking scores or probabilities.")

    # 1. 시드 키워드 정의
    seed_keyword = args.seed.strip()
    if not seed_keyword:
        parser.error("--seed must not be empty")
    print(f"🎯 시드 키워드: {seed_keyword}")
    
    # 2. 키워드 확장 (브레인스토밍)
    print("   ↳ 키워드 확장 및 브레인스토밍 중...")
    keywords, sub_topics = expand_keyword(seed_keyword)
    generated_count = len(keywords)
    limit = max(1, min(args.limit, 100))
    keywords = keywords[:limit]
    
    if sub_topics:
        print(f"   ✨ [Auto-Brainstorming] 대주제 감지! -> {len(sub_topics)}개 하위 주제로 확장됨.")
        print(f"      {sub_topics}")
    if generated_count > len(keywords):
        print(f"   ℹ️ API 호출량 제한: 생성된 {generated_count}개 중 {len(keywords)}개 검증")
    
    # 3. 실제 데이터 수집 (REAL API)
    print(f"   📡 네이버 API 접속 중... (총 {len(keywords)}개 키워드)")
    data = []
    fetcher = RealDataFetcher()
    failure_guard = SourceFailureCircuitBreaker()
    source_failures = 0
    skipped_after_source_abort = 0
    for i, kw in enumerate(keywords):
        print(f"      [{i+1}/{len(keywords)}] '{kw}' 데이터 조회 중...", end=" ")
        try:
            metrics = fetch_keyword_data(kw, fetcher=fetcher)
            data.append(metrics)
            failure_guard.record_success()
            vol = metrics['Monthly_Search_Volume']
            docs = metrics['Blog_Doc_Count']
            print(f"👉 [검색량 추정: {vol:,} / 블로그 결과 수: {docs:,}]")
        except SourceError as exc:
            source_failures += 1
            print(f"제외됨 ({exc.source}, status={exc.status_code or 'unknown'})")
            if failure_guard.should_abort(exc):
                skipped_after_source_abort = len(keywords) - i - 1
                print(
                    "   ⛔ 인증·할당량 또는 연속 출처 장애로 남은 "
                    f"{skipped_after_source_abort}개 키워드 조회를 중단합니다."
                )
                break
        
    print("\n   ✅ 데이터 수집 완료.")
    
    if not data:
        print("❌ 수집된 데이터가 없습니다. secrets.json 설정을 확인해주세요.")
        return 1

    df = pd.DataFrame(data)
    
    # 4. 지표 계산 (변수명 매칭: Monthly_Search_Volume, Total_Docs)
    print("   🧮 알고리즘 계산 중 (Sk, Ek)...")
    try:
        df['Saturation_Index'] = df.apply(lambda row: calculate_saturation(row['Blog_Doc_Count'], row['Monthly_Search_Volume']), axis=1)
        df['Efficiency_Score'] = df.apply(lambda row: calculate_efficiency(row['Saturation_Index'], row['Monthly_Search_Volume']), axis=1)
    except KeyError as e:
        print(f"❌ 데이터 컬럼 이름 불일치 에러: {e}")
        print("data_fetcher.py가 반환하는 키 값(Key)을 확인하세요.")
        return 1
    
    # 5. 필터링 (Sk < 5.0)
    initial_count = len(df)
    df_filtered = filter_keywords(df) # calculator.py의 함수 사용
    dropped_count = initial_count - len(df_filtered)
    
    if dropped_count > 0:
        print(f"   🗑️ 공급비율 기준에서 {dropped_count}개 제외됨 (Sk >= 5.0 또는 수요 부족)")
    
    # 6. 정렬 (효율성 순)
    df_filtered = df_filtered.sort_values(by='Efficiency_Score', ascending=False)
    
    # 7. 리포트 생성
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    os.makedirs('reports', exist_ok=True)
    report_filename = f"reports/result_REAL_{timestamp}.md"
    
    # 보기 좋게 반올림
    display_df = df_filtered.copy()
    display_df['Saturation_Index'] = display_df['Saturation_Index'].round(2)
    display_df['Efficiency_Score'] = display_df['Efficiency_Score'].round(2)
    
    # Markdown 변환
    try:
        markdown_table = display_df[
            [
                'Keyword',
                'Monthly_Search_Volume',
                'Search_Volume_Censored',
                'Search_Volume_PC_Raw',
                'Search_Volume_Mobile_Raw',
                'Total_Docs',
                'Saturation_Index',
                'Efficiency_Score',
                'SmartBlock_Type',
            ]
        ].to_markdown(index=False)
    except ImportError:
        markdown_table = display_df.to_string()

    brainstorm_section = ""
    if sub_topics:
        brainstorm_section = f"""
> [!TIP]
> **Auto-Brainstorming Activated**
> 입력하신 대주제 **'{seed_keyword}'**에 대해 다음 세부 주제로 확장을 수행했습니다:
> {', '.join(sub_topics)}
"""

    report_content = f"""# SEO Keyword Analysis Report (REAL DATA)
**Timestamp:** {timestamp}
**Seed Keyword:** {seed_keyword}
{brainstorm_section}
## Analysis Summary
- **Total Keywords Analyzed:** {initial_count}
- **Keywords Passed Filter (Sk < 5.0):** {len(df_filtered)}
- **Drop Rate:** {dropped_count / initial_count * 100:.1f}%
- **Source failures observed:** {source_failures}
- **Skipped after source circuit breaker:** {skipped_after_source_abort}

## Legacy Candidate Keywords (Sorted by Efficiency Ek)

| Field | Meaning |
| --- | --- |
| **Sk (Saturation Ratio)** | Blog result count divided by estimated monthly search demand; a weak proxy only |
| **Ek (Legacy Efficiency)** | Local sorting heuristic; not an official Naver metric |
| **Censored volume** | If `Search_Volume_Censored` is `True`, monthly demand includes a midpoint estimate for a raw `<10` Search Ads value; inspect the PC/mobile raw columns instead of treating it as exact |

{markdown_table}

## Next Actions
- Re-check candidates with time-series and independent cross-source evidence.
- Inspect the actual search-result intent manually; no official API exposes SmartBlock eligibility.
"""
    
    with open(report_filename, "w", encoding="utf-8") as f:
        f.write(report_content)
        
    print(f"✅ 리포트 생성 완료: {report_filename}")
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
