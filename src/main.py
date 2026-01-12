import sys
import os
import json
import pandas as pd
import argparse
from datetime import datetime
import time

# --- 경로 설정 (가장 중요) ---
# 현재 파일(main.py)의 위치를 강제로 시스템 경로에 추가합니다.
# 이렇게 하면 "src." 같은 접두사 없이 그냥 파일 이름만 부르면 됩니다.
current_dir = os.path.dirname(os.path.abspath(__file__))
if current_dir not in sys.path:
    sys.path.append(current_dir)

try:
    # 같은 폴더(src)에 있는 모듈들을 직접 호출
    from keyword_expander import expand_keyword
    from data_fetcher import fetch_keyword_data
    from calculator import calculate_saturation, calculate_efficiency, filter_keywords
except ImportError as e:
    print(f"❌ 모듈 로딩 실패: {e}")
    print(f"현재 'src' 폴더 안에 다음 파일들이 있는지 확인해주세요:")
    print(f" - keyword_expander.py")
    print(f" - data_fetcher.py")
    print(f" - calculator.py")
    sys.exit(1)

def main():
    parser = argparse.ArgumentParser(description="Naver SEO Keyword Miner (Real Data Mode)")
    parser.add_argument("--seed", type=str, default="캠핑의자", help="Seed keyword for mining")
    args = parser.parse_args()

    print(f"🤖 [닥터스톤 Real-Data 에이전트] 가동 시작...")

    # 1. 시드 키워드 정의
    seed_keyword = args.seed
    print(f"🎯 시드 키워드: {seed_keyword}")
    
    # 2. 키워드 확장 (브레인스토밍)
    print("   ↳ 키워드 확장 및 브레인스토밍 중...")
    keywords, sub_topics = expand_keyword(seed_keyword)
    
    if sub_topics:
        print(f"   ✨ [Auto-Brainstorming] 대주제 감지! -> {len(sub_topics)}개 하위 주제로 확장됨.")
        print(f"      {sub_topics}")
    
    # 3. 실제 데이터 수집 (REAL API)
    print(f"   📡 네이버 API 접속 중... (총 {len(keywords)}개 키워드)")
    data = []
    
    # for i, kw in enumerate(keywords):
    #     print(f"      [{i+1}/{len(keywords)}] '{kw}' 데이터 조회 중...", end="\r")
    #     try:
    #         # fetch_keyword_data는 내부적으로 secrets.json을 로드합니다.
    #         metrics = fetch_keyword_data(kw)
    #         if metrics:
    #             data.append(metrics)
    #     except Exception as e:
    #         print(f"\n      ❌ Error fetching '{kw}': {e}")
        
    #     # API 과부하 방지 (살짝 텀을 줌)
    #     time.sleep(0.1) 
    for i, kw in enumerate(keywords):
            print(f"      [{i+1}/{len(keywords)}] '{kw}' 데이터 조회 중...", end=" ") # end="\r" 제거
            try:
                metrics = fetch_keyword_data(kw)
                if metrics:
                    data.append(metrics)
                    
                    # [🔥 검증 코드 추가] : 이 부분이 핵심입니다!
                    vol = metrics['Monthly_Search_Volume']
                    docs = metrics['Total_Docs']
                    print(f"👉 [검색량: {vol:,} / 문서수: {docs:,}]")  
                    
            except Exception as e:
                print(f"\n      ❌ Error fetching '{kw}': {e}")
            
            time.sleep(0.1)
        
    print("\n   ✅ 데이터 수집 완료.")
    
    if not data:
        print("❌ 수집된 데이터가 없습니다. secrets.json 설정을 확인해주세요.")
        return

    df = pd.DataFrame(data)
    
    # 4. 지표 계산 (변수명 매칭: Monthly_Search_Volume, Total_Docs)
    print("   🧮 알고리즘 계산 중 (Sk, Ek)...")
    try:
        df['Saturation_Index'] = df.apply(lambda row: calculate_saturation(row['Total_Docs'], row['Monthly_Search_Volume']), axis=1)
        df['Efficiency_Score'] = df.apply(lambda row: calculate_efficiency(row['Saturation_Index'], row['Monthly_Search_Volume']), axis=1)
    except KeyError as e:
        print(f"❌ 데이터 컬럼 이름 불일치 에러: {e}")
        print("data_fetcher.py가 반환하는 키 값(Key)을 확인하세요.")
        return
    
    # 5. 필터링 (Sk < 5.0)
    initial_count = len(df)
    df_filtered = filter_keywords(df) # calculator.py의 함수 사용
    dropped_count = initial_count - len(df_filtered)
    
    if dropped_count > 0:
        print(f"   🗑️ 레드오션 키워드 {dropped_count}개 제거됨 (Sk >= 5.0)")
    
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
        markdown_table = display_df[['Keyword', 'Monthly_Search_Volume', 'Total_Docs', 'Saturation_Index', 'Efficiency_Score', 'SmartBlock_Type']].to_markdown(index=False)
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
    
    with open(report_filename, "w", encoding="utf-8") as f:
        f.write(report_content)
        
    print(f"✅ 리포트 생성 완료: {report_filename}")

if __name__ == "__main__":
    main()