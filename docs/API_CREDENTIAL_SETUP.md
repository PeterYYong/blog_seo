# API credential setup

검토 기준일: **2026-08-03 (Asia/Seoul)**

키는 ChatGPT 대화나 MCP 도구 인수에 붙여 넣지 않습니다. 로컬에서는 `.env`, 배포 환경에서는 secret manager에만 넣고 저장소에는 커밋하지 않습니다.

## 최소 권장 구성

현재 워크플로우의 권장 조합은 다음 세 묶음입니다.

1. NAVER API HUB: 검색어 트렌드와 블로그·뉴스·카페·지식iN 검색
2. Naver Search Ads API: 연관 키워드와 월간 검색량
3. YouTube Data API v3: 한국 인기 영상과 최근 영상 조회 속도

사용자가 이미 “Naver API”를 보유했더라도 Search Ads 세 자격증명은 별도입니다. Naver Developers/HUB 키만으로는 월간 검색량을 조회할 수 없습니다.

## 1. NAVER API HUB

2026-07-31 이후 Search API와 Search Trend API 신규 신청은 Naver Developers Center가 아니라 NAVER Cloud Platform의 **NAVER API HUB**에서만 받습니다.

1. [NAVER Cloud Platform console](https://console.ncloud.com/)에 가입·로그인합니다.
2. `All Services > Application Services > NAVER API HUB`에서 이용 신청을 합니다.
3. `Application`에서 새 애플리케이션을 등록하고 Search API와 Search Trend API를 선택합니다.
4. `Application Management > API 관리 > 인증 정보`에서 Client ID와 Client Secret을 복사합니다.
5. `.env`에 다음처럼 저장합니다.

```dotenv
NAVER_API_HUB_CLIENT_ID=...
NAVER_API_HUB_CLIENT_SECRET=...
```

공식 문서: [NAVER API HUB overview](https://api.ncloud-docs.com/docs/naver-api-hub-overview), [migration guide](https://guide.ncloud-docs.com/docs/apihub-migration), [migration notice](https://developers.naver.com/notice/article/32530)

### 기존 Naver Developers 키가 있는 경우

2026-07-31 전에 Search/Search Trend 이용 신청을 마친 기존 키는 2027-06-30까지 유예 지원됩니다. 당장은 아래 기존 변수로 사용할 수 있지만 종료 전에 HUB로 이관합니다.

```dotenv
NAVER_CLIENT_ID=...
NAVER_CLIENT_SECRET=...
```

두 쌍을 모두 넣으면 코드가 NAVER API HUB를 우선 사용합니다. 쇼핑·책·전문자료 검색 API는 2026-07-31에 별도 대체 없이 종료됐으며 이 워크플로우는 사용하지 않습니다.

## 2. Naver Search Ads API

1. [Naver Search Advertiser Center](https://searchad.naver.com/)에 가입하고 광고주 계정을 준비합니다.
2. [Search Ads management](https://manage.searchad.naver.com/)에서 `Tools > API Manager`로 이동합니다.
3. API License를 생성하고 API key/license, secret key, customer ID를 확인합니다.
4. `.env`에 각각 매핑합니다.

```dotenv
NAVER_AD_API_KEY=...
NAVER_AD_SECRET_KEY=...
NAVER_CUSTOMER_ID=...
```

이 자격증명은 광고를 생성하는 데 쓰지 않고 읽기 전용 `GET /keywordstool` 호출에만 사용합니다. 공식 서비스 주소는 `https://api.searchad.naver.com`입니다. [Search Ads API guide](https://naver.github.io/searchad-apidoc/)

## 3. YouTube Data API v3

1. [Google Cloud console](https://console.cloud.google.com/)에서 전용 프로젝트를 만들거나 선택합니다.
2. `APIs & Services > Library`에서 **YouTube Data API v3**를 활성화합니다.
3. `Credentials > Create credentials > API key`로 키를 만듭니다.
4. 키의 API restriction을 YouTube Data API v3로 제한합니다. 서버 IP가 고정돼 있다면 application restriction도 서버 IP로 제한합니다.
5. `.env`에 저장합니다.

```dotenv
YOUTUBE_API_KEY=...
```

현재 구현은 공개 영상만 읽으므로 OAuth 동의 화면이나 사용자 로그인이 필요하지 않습니다. 검색 호출량은 Google Cloud의 quota 화면에서 모니터링합니다. 후보를 최대 5개로 제한한 이유 중 하나가 검색 쿼터와 비용 통제입니다. 공식 문서: [getting started](https://developers.google.com/youtube/v3/getting-started), [search.list](https://developers.google.com/youtube/v3/docs/search/list)

## 4. 선택 소스

- Bluesky·Hacker News·Stack Exchange: 기본 공개 API를 사용하므로 시작 단계에서 새 키가 필요하지 않습니다. Stack Exchange 키는 쿼터 상향용입니다.
- Daum Cafe: 한국어 커뮤니티 폭을 넓히려면 Kakao Developers 앱의 REST API key를 `KAKAO_REST_API_KEY`로 추가합니다.
- Reddit: 앱 키보다 먼저 Data API 접근 승인이 필요합니다. 승인 전에는 `REDDIT_API_APPROVED=false`로 둡니다.
- X: 최근 검색은 유료 사용 조건을 확인한 뒤 bearer token을 추가합니다.
- Threads: 앱에 `threads_keyword_search` 권한이 승인된 뒤에만 토큰과 enable 플래그를 설정합니다.

Naver와 YouTube만 설정해도 핵심 기회 검증은 동작합니다. 선택 SNS가 없으면 도구는 수치를 0으로 만들지 않고 `not_configured`와 빠진 근거를 표시합니다.

## 5. 연결 확인

```bash
set -a
source .env
set +a
python -m src.mcp_server
```

ChatGPT Work에서 `get_source_status`를 먼저 호출합니다. `naver_datalab_and_search`, `naver_search_ads`, `youtube_data_api`가 `available=true`인지 확인한 뒤 실제 키워드 조회를 한 번 실행합니다. 키를 로그로 출력하거나 화면 캡처에 포함하지 않습니다.
