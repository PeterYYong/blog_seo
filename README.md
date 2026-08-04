# Evidence-first Naver Blog SEO MCP

네이버·YouTube의 공식 API와 커뮤니티/SNS 대화 신호를 모아 “요즘 쓸 만한 주제”를 비교하고, 실제 경험을 확인한 뒤 초안을 설계하며, 네이버 공식 정책·공정위 표시 원칙·사용자 문체 가이드를 구분해 검수하는 ChatGPT Work용 MCP 서버입니다.

이 프로젝트의 점수는 **후보끼리 비교하는 편집 우선순위**입니다. 네이버 내부 점수나 상위 노출 확률이 아닙니다.

## 무엇이 달라졌나

- Naver Search Ads 월간 수요, DataLab 최근 모멘텀, Blog Search 문서량 보조지표, YouTube 최근 조회 속도를 한 근거 카드에 담습니다.
- Naver 카페·지식iN, Daum 카페, Bluesky, Reddit, X, Threads, Hacker News, Stack Exchange에서 질문·불만·비교 표현을 수집해 후보 글감을 만듭니다.
- Reddit은 API 접근 승인, X는 유료 API 토큰, Threads는 `threads_keyword_search` 권한이 있을 때만 켜집니다. 무단 웹 스크래핑은 사용하지 않습니다.
- 플랫폼별 좋아요·댓글·조회·점수는 단위가 다르므로 서로 합산하거나 순위를 매기지 않습니다.
- YouTube `mostPopular`는 주제 후보를 찾는 출발점으로만 쓰고, 네이버 수요·검색 의도와 다시 교차 검증합니다.
- Naver의 여러 API는 한 출처군으로 계산하며, YouTube까지 함께 지지해야 “교차 검증된 인기 주제”로 표시합니다.
- API 실패를 0으로 바꾸거나 예시 인기어를 실제 데이터처럼 반환하지 않습니다.
- 음식점 후기는 방문일·주문 메뉴·가격·맛 기록·장단점 등이 없으면 완성형 체험 문장을 생성하지 않습니다.
- 공식 정책, 로컬 검수 기준, 첨부 톤앤매너, 편집 제안을 별도 등급으로 표시합니다.
- 수정 전후를 비교해 무엇을 왜 바꿨는지 출처와 함께 설명합니다.
- 소스별 승인·비용·분야 적합성을 보여 주고, 특정 커뮤니티를 포함하거나 제외한 이유까지 Rationale Agent가 설명합니다.

## MCP 도구

| 도구 | 역할 |
|---|---|
| `get_source_status` | 설정된 API와 빠진 근거 확인 |
| `discover_community_topic_signals` | SNS·카페·Q&A에서 질문과 반복 표현을 찾아 링크 근거로 반환 |
| `youtube_trending_snapshot` | 한국 YouTube 인기 영상에서 후보 주제 탐색 |
| `discover_topic_opportunities` | 네이버·YouTube 근거 카드와 상대 점수 생성 |
| `prepare_blog_draft_brief` | 실제 경험 정보 확인, 초안 작성 가능 여부 판정 |
| `audit_blog_draft` | 네이버 정책·협찬 표시·문체·허위 체험 위험 검수 |
| `explain_blog_revision` | 수정 전후의 해결·잔존·신규 이슈와 변경 이유 설명 |
| `get_naver_policy_baseline` | 날짜가 기록된 공식 정책 기준과 비보장 항목 반환 |

자세한 실행 순서는 [Agent workflow](docs/AGENT_WORKFLOW.md), 판단식과 한계는 [Methodology](METHODOLOGY.md), 소스별 접근·비용·보류 이유는 [Community source review](docs/COMMUNITY_SOURCE_REVIEW.md), 키 발급 절차는 [API credential setup](docs/API_CREDENTIAL_SETUP.md)을 참고하세요.

PC를 켜 두지 않는 Railway + Secure MCP Tunnel 방식은 [Beginner cloud setup](docs/BEGINNER_CLOUD_SETUP.md)에 화면 순서와 오류 해결법까지 정리되어 있습니다.

## 빠른 시작

Python 3.10 이상을 권장합니다.

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
```

`.env`에 사용할 키를 입력한 뒤 환경 변수로 불러오고 서버를 시작합니다.

```bash
set -a
source .env
set +a
python -m src.mcp_server
```

기본 Streamable HTTP 엔드포인트는 `http://localhost:8000/mcp`입니다. 개인/Workspace 테스트에는 API 키를 노출하지 않는 **Secure MCP Tunnel**을 우선 사용하세요. 공개 HTTPS로 운영하려면 MCP 인증, 사용자별 호출 제한, 비밀 관리가 먼저 필요합니다. 구체적인 연결법은 [ChatGPT Work setup](docs/CHATGPT_WORK_SETUP.md)에 있습니다.

## 필요한 API 키

| 키 | 제공 근거 | 필수 여부 |
|---|---|---|
| `NAVER_AD_API_KEY`, `NAVER_AD_SECRET_KEY`, `NAVER_CUSTOMER_ID` | 연관 키워드·월간 검색량 | 강력 권장 |
| `NAVER_API_HUB_CLIENT_ID`, `NAVER_API_HUB_CLIENT_SECRET` | 검색어 트렌드·블로그/뉴스/카페/지식iN 검색 | 현재 신규 설정에 필수 |
| `NAVER_CLIENT_ID`, `NAVER_CLIENT_SECRET` | 같은 기능의 기존 Developer Center 인증 | 2026-07-31 이전 발급 키에만 선택 |
| `YOUTUBE_API_KEY` | 최근 영상 조회 속도·한국 인기 영상 | 인기 주제 기능에 권장 |
| `KAKAO_REST_API_KEY` | Daum 카페 최신순 검색 | 한국어 커뮤니티 보강 시 선택 |
| `REDDIT_API_APPROVED=true` + Reddit OAuth 3종 | Reddit 최신 글 검색 | Reddit 승인 후 선택 |
| `X_BEARER_TOKEN` | X 최근 7일 게시물 검색 | 유료 사용 시 선택 |
| `THREADS_KEYWORD_SEARCH_ENABLED=true` + 토큰 | Threads 공개 키워드 검색 | 권한 승인 후 선택 |
| `STACKEXCHANGE_KEY` | Stack Exchange 질문 검색 쿼터 상향 | 선택; 익명 호출 가능 |

출처 하나가 없어도 나머지 결과는 반환하지만, 누락 출처와 낮아진 근거 완성도를 함께 표시합니다. NAVER API HUB 키와 기존 Developer Center 키가 모두 있으면 HUB를 우선 사용합니다.

2026-07-31 이후 Search API와 Search Trend의 신규 신청은 NAVER API HUB에서만 가능합니다. 기존 Developer Center 키는 2027-06-30까지 유예 지원되므로 그 전에 이관해야 합니다. 이 프로젝트는 두 인증 방식을 자동 판별합니다. Bluesky·Hacker News·Stack Exchange는 기본 공개 API를 사용할 수 있습니다. Naver 카페·지식iN은 두 인증 방식 중 설정된 키를 쓰며, 게시 시각과 반응 수를 반환하지 않으므로 “실시간 인기”가 아닌 한국어 질문·표현 근거로만 사용합니다.

## 검증

```bash
python -m compileall src tests
pytest -q
```

## 기존 Streamlit 화면

```bash
streamlit run src/app.py
```

기존 `S_k`·`E_k` 화면은 하위 호환용입니다. 해당 비율은 네이버 공식 지표가 아니며, 최종 주제 추천에는 MCP의 다중 출처 근거를 사용하세요. Signal.bz 기능도 제3자 크롤러이므로 공식 실시간 네이버 검색어로 표현하지 않습니다.

## 기본 안전 원칙

- 검색 순위, 유입, 노출을 보장하지 않습니다.
- 방문·구매·맛·가격·대기시간·사진을 생성하지 않습니다.
- 협찬·제품/서비스 제공·제휴 등 경제적 관계는 제목 또는 글 첫 부분에서 구체적으로 밝히도록 검사합니다.
- `.env`, `secrets.json`, Streamlit secrets는 Git에 포함하지 않습니다.
- 발행은 사람의 최종 승인 단계로 남겨 둡니다.
