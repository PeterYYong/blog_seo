import streamlit as st
import pandas as pd
import sys
import os
import time

# --- Path Setup ---
# Add 'src' to sys.path if running from root
current_dir = os.path.dirname(os.path.abspath(__file__))
if current_dir not in sys.path:
    sys.path.append(current_dir)

# Import internal modules
try:
    from keyword_expander import expand_keyword
    from data_fetcher import fetch_keyword_data, RealDataFetcher
    from calculator import calculate_saturation, calculate_efficiency, filter_keywords
    from trend_hunter import fetch_trending_keywords 
except ImportError:
    # Handle direct execution from src folder or different structure
    sys.path.append(os.path.join(current_dir, ".."))
    from src.keyword_expander import expand_keyword
    from src.data_fetcher import fetch_keyword_data, RealDataFetcher
    from src.calculator import calculate_saturation, calculate_efficiency, filter_keywords
    from src.trend_hunter import fetch_trending_keywords

st.set_page_config(page_title="네이버 SEO 아키텍트", page_icon="🧬", layout="wide")

st.title("🧬 네이버 블로그 주제 기회 탐색기")
st.markdown("""
검색량과 블로그 문서 수를 비교하는 기존 대시보드입니다.
`S_k`와 `E_k`는 네이버 공식 순위 지표가 아니며, 추천 판단에는 MCP의 DataLab·YouTube 교차 근거를 함께 사용하세요.
""")

# --- Sidebar Mode Selection ---
mode = st.sidebar.selectbox("분석 모드 선택", ["모드 A: 기초 키워드 분석", "모드 B: 실시간 트렌드 딥다이브", "모드 C: 니치 마켓 헌터"])

if mode == "모드 A: 기초 키워드 분석":
    st.header("🔍 기초 키워드 분석 (Basic)")
    st.info("하나의 시드 키워드를 입력하면, 관련 세부 주제로 확장하여 분석합니다.")
    
    seed = st.text_input("시드 키워드 입력", value="광주 맛집")
    
    if st.button("키워드 분석 시작"):
        with st.status("분석 진행 중...", expanded=True):
            st.write("🧠 키워드 브레인스토밍 및 확장 중...")
            keywords, sub_topics = expand_keyword(seed)
            if sub_topics:
                st.success(f"⚡ 자동 브레인스토밍 발동! 다음 주제로 확장됨: {sub_topics}")
            else:
                st.info(f"총 {len(keywords)}개 파생 키워드 분석 시작.")
            
            st.write("📡 네이버 실제 데이터 수집 중...")
            data = []
            progress_bar = st.progress(0)
            
            for i, kw in enumerate(keywords):
                metrics = fetch_keyword_data(kw)
                if metrics:
                    data.append(metrics)
                progress_bar.progress((i + 1) / len(keywords))
                time.sleep(0.1)
                
            if not data:
                st.error("데이터 수집 실패. API 키나 검색어를 확인해주세요.")
            else:
                df = pd.DataFrame(data)
                
                st.write("🧮 지표($S_k, E_k$) 계산 중...")
                df['Saturation_Index'] = df.apply(lambda row: calculate_saturation(row['Total_Docs'], row['Monthly_Search_Volume']), axis=1)
                df['Efficiency_Score'] = df.apply(lambda row: calculate_efficiency(row['Saturation_Index'], row['Monthly_Search_Volume']), axis=1)
                
                # Show Result
                st.subheader("📊 분석 결과")
                
                # Highlight Blue Ocean
                def highlight_blue_ocean(val):
                    color = '#d4edda' if val < 1.0 else ''
                    return f'background-color: {color}'

                display_df = df[['Keyword', 'Monthly_Search_Volume', 'Total_Docs', 'Saturation_Index', 'Efficiency_Score']].sort_values(by='Efficiency_Score', ascending=False)
                
                st.dataframe(display_df.style.map(highlight_blue_ocean, subset=['Saturation_Index']), use_container_width=True)
                
                csv = display_df.to_csv(index=False).encode('utf-8-sig')
                st.download_button("결과 CSV 다운로드", csv, "keyword_analysis.csv", "text/csv")


elif mode == "모드 B: 실시간 트렌드 딥다이브":
    st.header("🌊 실시간 트렌드 딥 다이브")
    st.info("Signal.bz를 사용하는 레거시 보조 기능입니다. 공식 실시간 네이버 검색어 API가 아니며 결과를 재검증해야 합니다.")
    
    if st.button("트렌드 헌팅 시작"):
        with st.status("트렌드 추적 중...", expanded=True) as status:
            st.write("📡 Signal.bz 크롤링 중...")
            trends = fetch_trending_keywords(limit=5)
            if not trends:
                st.error("트렌드 출처를 확인할 수 없습니다. 예시 키워드를 실제 인기어로 대체하지 않습니다.")
                status.update(label="근거 데이터 없음", state="error")
                st.stop()
            st.write(f"🔥 포착된 트렌드: {trends}")
            
            st.write("🧠 확장 및 심층 분석 중...")
            all_targets = set()
            for t in trends:
                exp, _ = expand_keyword(t)
                all_targets.update(exp)
            
            unique_targets = list(all_targets)
            st.write(f"🚀 총 {len(unique_targets)}개 키워드 분석 대상")
            
            data = []
            progress_bar = st.progress(0)
            
            for i, kw in enumerate(unique_targets):
                metrics = fetch_keyword_data(kw)
                if metrics:
                    data.append(metrics)
                progress_bar.progress((i + 1) / len(unique_targets))
                time.sleep(0.1)
                
            if data:
                df = pd.DataFrame(data)
                df['Saturation_Index'] = df.apply(lambda row: calculate_saturation(row['Total_Docs'], row['Monthly_Search_Volume']), axis=1)
                df['Efficiency_Score'] = df.apply(lambda row: calculate_efficiency(row['Saturation_Index'], row['Monthly_Search_Volume']), axis=1)
                
                st.subheader("낮은 레거시 공급비율 후보 ($S_k < 1.0$)")
                blue_ocean = df[df['Saturation_Index'] < 1.0].sort_values(by='Efficiency_Score', ascending=False)
                st.dataframe(blue_ocean, use_container_width=True)
                
                st.subheader(r"높은 레거시 공급비율 ($S_k \ge 5.0$)")
                red_ocean = df[df['Saturation_Index'] >= 5.0].sort_values(by='Saturation_Index', ascending=False)
                st.dataframe(red_ocean, use_container_width=True)
                
                status.update(label="분석 완료", state="complete")
            else:
                st.error("데이터가 없습니다.")

elif mode == "모드 C: 니치 마켓 헌터":
    st.header("🦈 니치 마켓 헌터")
    st.info("특정 분야(카테고리)의 연관 검색어를 대량으로 수집하여 기회를 포착합니다.")
    
    seed = st.text_input("분야/주제 입력", value="미국 주식")
    
    if st.button("니치 마켓 발굴 시작"):
        fetcher = RealDataFetcher()
        with st.status("발굴 진행 중...", expanded=True) as status:
            st.write("📡 연관 검색어 수집 중...")
            related = fetcher.get_related_keywords(seed)
            
            if not related:
                st.error("연관 검색어를 찾을 수 없습니다.")
            else:
                st.success(f"{len(related)}개의 후보 키워드 발견. 상위 100개(또는 전체) 분석 시작...")
                
                # Limit to 100 for web demo speed
                target_list = related[:100] 
                
                results = []
                progress_bar = st.progress(0)
                
                for i, item in enumerate(target_list):
                    kw = item['keyword']
                    vol = item['volume']
                    
                    docs = fetcher.get_doc_count(kw)
                    sk = calculate_saturation(docs, vol)
                    ek = calculate_efficiency(sk, vol)
                    
                    results.append({
                        "Keyword": kw,
                        "Monthly_Search_Volume": vol,
                        "Total_Docs": docs,
                        "Saturation_Index": sk,
                        "Efficiency_Score": ek
                    })
                    progress_bar.progress((i + 1) / len(target_list))
                    
                if results:
                    df = pd.DataFrame(results)
                    
                    col1, col2 = st.columns(2)
                    
                    with col1:
                        st.subheader("월간 검색 수요 상위 20")
                        st.dataframe(df.sort_values(by='Monthly_Search_Volume', ascending=False).head(20), use_container_width=True)
                        
                    with col2:
                        st.subheader("낮은 레거시 공급비율 후보 ($S_k < 1.0$)")
                        blue_ocean = df[df['Saturation_Index'] < 1.0].sort_values(by='Efficiency_Score', ascending=False)
                        st.dataframe(blue_ocean, use_container_width=True)
                    
                    csv = df.to_csv(index=False).encode('utf-8-sig')
                    st.download_button("전체 리포트 CSV 다운로드", csv, f"niche_hunt_{seed}.csv", "text/csv")
                    
                status.update(label="발굴 완료", state="complete")

# Footer
st.markdown("---")
st.markdown("© 2026 Naver Search Ecology Architect | Powered by Streamlit")
