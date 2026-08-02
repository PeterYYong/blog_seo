# Community source review

검토 기준일: **2026-08-03 (Asia/Seoul)**

이 문서는 “글감 발굴에 쓸 수 있는가”와 “자동 수집을 정당하게 운영할 수 있는가”를 함께 평가합니다. 공개 페이지가 보인다는 사실만으로 자동 수집 권한이 생기지 않으므로, 범용 공식 API·승인 절차·비용·시간 필터·데이터 최소화를 우선했습니다.

## 구현한 소스

| 소스 | 공식 접근 | 구현 상태 | 글감 가치 | 운영상 주의 |
|---|---|---|---|---|
| Naver 카페 | NAVER API HUB Search API 또는 유예기간의 Developer Center API | 기본 어댑터 | 한국어 지역·상품·취미 표현 | 게시 시각·반응 수 미제공; 실시간 인기라고 표현 금지 |
| Naver 지식iN | NAVER API HUB Search API 또는 유예기간의 Developer Center API | 기본 어댑터 | 실제 질문형 검색 의도 | 게시 시각·반응 수 미제공 |
| Daum 카페 | Kakao Daum Search API | 키 입력 시 | 국내 카페 보완, 게시 시각 제공 | 최신순이지만 서버 측 기간 필터 없음 |
| Bluesky | AT Protocol public AppView | 기본 어댑터 | 공개 SNS 대화, 키 없이 시작 | `searchPosts`는 서비스 구현에 따라 인증을 요구할 수 있음 |
| Reddit | Reddit Data API OAuth | 승인+키 입력 시 | 긴 질문·불만·구매 비교 | 2026 Responsible Builder Policy상 API 접근 전 명시적 승인 필요; 삭제/제거/NSFW 제외 |
| X | X API v2 recent search | bearer token 입력 시 | 속도가 빠른 이슈·표현 | 최근 검색은 7일, pay-per-use; 현재 가격은 개발자 콘솔에서 확인 |
| Threads | Meta Threads `GET /keyword_search` | 권한+토큰+명시적 enable 시 | 생활·소비·F&B 대화 | `threads_keyword_search` 권한 필요; 공개 글 반응 합계는 검색 응답에 없으므로 추정 금지 |
| Hacker News | 공식 Firebase API | 기본 어댑터 | 기술·AI·스타트업 질문 | 공식 검색 endpoint가 없어 최근 feed 최대 40개를 로컬 필터; 저재현율 |
| Stack Exchange | API v2.3 advanced search | 기본 어댑터 | 기술·사용법·오류 해결 질문 | F&B·일반 소비 트렌드에는 부적합; key 없이는 낮은 쿼터 |

## 기본에서 제외하거나 보류한 소스

| 소스 | 결정 | 이유 | 대안 |
|---|---|---|---|
| DCInside, Blind, 클리앙, 루리웹, 뽐뿌 | 자동 연결 제외 | 검토 시점에 범용 공식 공개 검색 API를 확인하지 못함 | 수동 웹 조사 후 원문 링크를 약한 보조 근거로만 사용 |
| Mastodon | 2단계 보류 | 검색 가능 범위와 전문 검색 지원이 인스턴스마다 달라 일관된 전체 대화 검색이 어려움 | 특정 인스턴스·해시태그 목록을 사용자가 지정하면 별도 어댑터 검토 |
| TikTok | 기본 제외 | Research API는 자격을 갖춘 연구자 중심이라 일반 블로그 리서치 기본 연결로 부적합 | YouTube Data API 또는 승인된 상용 소셜 리스닝 서비스 |
| Google Trends API | 2단계 보류 | 공식 API가 제한적 alpha 접근 단계 | Naver DataLab + YouTube + 추후 alpha 승인 시 추가 |
| GitHub Issues/Discussions | MCP 내부 기본 제외 | 일반 블로그에는 편향이 크고, ChatGPT Work의 GitHub 플러그인으로 기술 분야에서 선택 조회 가능 | 기술·AI 전략에서 Work가 GitHub 플러그인을 보조 호출 |
| Product Hunt | 2단계 보류 | 제품/스타트업 분야에만 유효하고 별도 토큰·쿼터가 필요 | 사용 분야가 SaaS/제품 리뷰로 확정되면 추가 |
| 비공식 통합 스크레이퍼 | 기본 제외 | 약관·로그인·개인정보·endpoint 안정성 위험을 한 번에 떠안음 | 공식 API가 없고 사업상 필요할 때 법무/약관 검토 후 별도 선택 |

## 왜 하나의 소셜 점수로 합치지 않았나

X의 impressions, Reddit의 score, Hacker News의 points, Stack Exchange의 views, Bluesky의 likes는 생성 방식과 노출 모수가 다릅니다. 이 수치를 그대로 더하거나 플랫폼 간 백분위로 바꾸면 정밀해 보이지만 의미가 없습니다. 구현은 다음 계층을 분리합니다.

1. **대화 발견**: 질문 카드, 반복 단어, 불만·비교 표현, 링크를 찾습니다.
2. **교차 확인**: 정확히 같은 문구의 복제를 표시하고, 서로 다른 플랫폼에서 서로 다른 대화가 있는지 봅니다.
3. **검색 수요 검증**: 최대 5개 후보만 Naver Search Ads·DataLab·Blog Search와 YouTube로 검증합니다.
4. **작성 게이트**: 체험 사실과 협찬 관계를 사용자에게 확인한 뒤 초안을 만듭니다.

커뮤니티에서 많이 말한다는 사실은 사실 정확성, 전체 여론, Naver 검색 수요, 상위 노출 가능성 가운데 어느 것도 직접 증명하지 않습니다.

## ChatGPT Work 연결 형태

이 기능은 범용 문서 검색 커넥터가 아니라 주제 신호를 분석하는 **tool-only MCP**입니다. 따라서 company knowledge용 표준 `search`/`fetch`를 흉내 내지 않고, 한 목적의 읽기 전용 도구 `discover_community_topic_signals`를 제공합니다.

- 입력: query, 플랫폼 목록, 기간, 소스별 표본 수, 언어, 선택 subreddit/HN feed/Stack Exchange site
- 출력: 소스 상태·오류, 표본 메타데이터, 질문/대화 카드, 반복어, 익명화한 작성자 수, 원문 링크, 해석 금지사항
- 다음 도구: `discover_topic_opportunities`
- 최종 단계: `prepare_blog_draft_brief` → 작성 → `audit_blog_draft` → `explain_blog_revision`

별도 위젯은 넣지 않았습니다. ChatGPT Work가 표와 초안을 대화에 직접 렌더링하고, 모든 도구가 읽기 전용이어서 UI가 작업을 materially 개선하지 않기 때문입니다.

현재 서버에는 최종 사용자 인증 계층이 없으므로 ChatGPT Work 연결 기본값은 Secure MCP Tunnel입니다. 공개 URL로 노출하면 읽기 도구만 있어도 유료 X 크레딧과 API 쿼터가 남용될 수 있습니다. 공개 운영은 MCP 인증·사용자별 rate/cost limit·secret manager를 추가한 별도 배포 단계로 취급합니다.

## 기술 분야에서 GitHub 플러그인 함께 쓰기

GitHub Issues/Discussions가 유용한 주제에서만 다음처럼 두 기능을 조합합니다.

```text
AI 개발 도구 분야의 최근 질문을 커뮤니티 MCP에서 먼저 찾아줘.
그다음 GitHub 플러그인으로 관련 공개 저장소의 최근 Issues/Discussions를 확인하되,
재현 가능한 사용자 문제만 후보에 추가해줘. 최대 5개를 Naver·YouTube로 재검증하고
각 후보에 원문 링크와 반대 근거를 붙여줘.
```

GitHub 결과도 기술 사용자 표본일 뿐 일반 대중의 관심을 대표하지 않으며, 저장소 issue의 주장 자체를 사실로 확정하지 않습니다.

## 공식 문서

- [NAVER API HUB migration notice](https://developers.naver.com/notice/article/32530)
- [Naver Cafe Search API](https://api.ncloud-docs.com/docs/naver-api-hub-search-cafearticle)
- [Naver Knowledge iN Search API](https://api.ncloud-docs.com/docs/naver-api-hub-search-kin)
- [Kakao Daum Cafe Search API](https://developers.kakao.com/docs/ko/daum-search/dev-guide#search-cafe)
- [Bluesky searchPosts lexicon](https://docs.bsky.app/docs/api/app-bsky-feed-search-posts)
- [Reddit Responsible Builder Policy](https://support.reddithelp.com/hc/en-us/articles/42728983564564-Responsible-Builder-Policy)
- [Reddit Data API Wiki](https://support.reddithelp.com/hc/en-us/articles/16160319875092-Reddit-Data-API-Wiki)
- [X recent search integration](https://docs.x.com/x-api/posts/search/integrate/overview)
- [X API pricing](https://docs.x.com/x-api/getting-started/pricing)
- [Threads keyword search](https://developers.facebook.com/documentation/threads/keyword-search)
- [Hacker News API](https://github.com/HackerNews/API)
- [Stack Exchange advanced search](https://api.stackexchange.com/docs/advanced-search)
- [Mastodon search API](https://docs.joinmastodon.org/methods/search/)
- [TikTok Research API](https://developers.tiktok.com/products/research-api/)
- [Google Trends API](https://developers.google.com/search/apis/trends)
