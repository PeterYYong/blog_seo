from typing import List, Tuple

# 대주제 매핑 (브레인스토밍용)
BROAD_TOPIC_MAP = {
    "의료 AI": ["루닛", "뷰노", "JLK", "딥노이드", "뇌졸중 진단 AI", "의료 영상 AI"],
    "주식": ["미국 배당주", "ISA 계좌", "나스닥 100", "SCHD", "토스증권", "삼성전자", "엔비디아"],
    "블로그": ["블로그 수익화", "체험단 신청", "애드포스트 현실", "지수 올리기"],
    "맛집": ["데이트 코스", "현지인 맛집", "가성비 오마카세", "혼밥 추천"],
    "여행": ["일본 여행", "다낭 여행", "환율 우대", "해외여행 준비물"]
}

def expand_keyword(seed_keyword: str) -> Tuple[List[str], List[str]]:
    """
    키워드 성격에 따라 적절한 접미사(Suffix)를 붙여 확장합니다.
    """
    
    # 1. 기본 쇼핑/리뷰형 접미사 (맛집, 제품 등)
    base_suffixes = ["추천", "비교", "후기", "방법", "내돈내산", "가격", "장단점"]
    
    # 2. 투자/뉴스/트렌드형 접미사 (주식, 코인, 경제 이슈 등)
    # 닥터스톤님의 관심사(주식/경제)에 최적화
    news_suffixes = ["주가", "전망", "관련주", "배당금", "시세", "이유", "분석", "실적", "ETF"]
    
    # 3. 정보성/How-to형 접미사
    info_suffixes = ["하는법", "신청", "조회", "사이트", "사용법"]

    expanded_list = []
    expanded_list.append(seed_keyword) # 원본 포함

    # 대주제(Broad Topic) 확인
    sub_topics = BROAD_TOPIC_MAP.get(seed_keyword, [])
    targets = sub_topics if sub_topics else [seed_keyword]

    for target in targets:
        # 간단한 키워드 성격 추론 로직
        # (단어에 특정 글자가 포함되어 있으면 뉴스형 접미사 우선 적용)
        if any(x in target for x in ["주식", "전자", "코인", "비트", "에코프로", "환율", "금리", "AI", "테크", "반도체"]):
            target_suffixes = news_suffixes + info_suffixes # 투자+정보 위주
        elif any(x in target for x in ["맛집", "여행", "제품", "리뷰", "크림", "청소기"]):
            target_suffixes = base_suffixes + info_suffixes # 리뷰+정보 위주
        else:
            # 잘 모를 땐 다 섞어서 (가장 강력함)
            target_suffixes = list(set(base_suffixes + news_suffixes + info_suffixes))

        for suffix in target_suffixes:
            expanded_list.append(f"{target} {suffix}")
            
    return list(set(expanded_list)), sub_topics