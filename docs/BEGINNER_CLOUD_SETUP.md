# Beginner cloud setup: Naver Blog SEO MCP

검토 기준일: **2026-08-05 (Asia/Seoul)**

이 문서는 Windows나 서버 지식이 없는 사용자가 `blog_seo`를 Railway에 24시간 실행하고 ChatGPT에서 사용하는 순서를 설명합니다. 최초 설정만 PC 웹브라우저에서 진행하면 이후에는 개인 PC를 켜 둘 필요가 없습니다.

## 먼저 이해할 네 가지

| 구성요소 | 쉬운 비유 | 실제 역할 |
|---|---|---|
| GitHub | 프로그램 보관함 | `blog_seo` 코드와 배포 파일을 보관 |
| Railway | 24시간 켜진 임대 컴퓨터 | Python MCP 서버와 터널을 계속 실행 |
| Secure MCP Tunnel | 잠긴 전용 전화선 | Railway 서버를 공개하지 않고 ChatGPT와 연결 |
| ChatGPT | 작업을 지시하는 화면 | MCP의 8개 도구를 선택해 조사·초안·검수를 수행 |

전체 데이터 흐름은 다음과 같습니다.

```text
나 → ChatGPT → OpenAI Secure MCP Tunnel → Railway의 blog_seo
                                          ├─ Naver API
                                          ├─ YouTube API
                                          └─ 허용된 커뮤니티 API
```

Railway에 공개 도메인을 만들지 않는 것이 중요합니다. 외부에서는 서버에 직접 들어올 수 없고, Railway 안의 `tunnel-client`가 OpenAI로 먼저 보안 연결을 만듭니다.

---

## 준비물

- GitHub 계정과 `PeterYYong/blog_seo` 저장소
- Railway 계정과 결제수단: Hobby 요금제 권장
- ChatGPT에서 Developer mode와 Tunnel 연결을 사용할 수 있는 계정
- OpenAI Platform에서 Tunnel을 만들 권한
- 다음 API 자격증명
  - NAVER API HUB Client ID/Secret
  - Naver Search Ads API key/secret/customer ID
  - YouTube Data API key

X, Reddit, Threads, Kakao 키는 처음부터 필요하지 않습니다. 먼저 Naver와 YouTube만 연결해 핵심 기능을 확인합니다.

---

## 0단계: Tunnel 메뉴가 보이는지 먼저 확인

Railway 결제와 배포를 하기 전에 이 단계를 확인합니다.

1. PC 브라우저에서 [OpenAI Platform Tunnels](https://platform.openai.com/settings/organization/tunnels)를 엽니다.
2. OpenAI Platform과 ChatGPT에 같은 계열의 계정으로 로그인합니다.
3. Tunnel 목록이나 `Create tunnel` 버튼이 보이는지 확인합니다.
4. ChatGPT 웹에서 `Settings → Security and login → Developer mode`를 켭니다.
5. [ChatGPT Plugins](https://chatgpt.com/plugins) 페이지에서 `+` 버튼이나 새 연결 생성 화면이 보이는지 확인합니다.

### 여기서 중단해야 하는 경우

- `Tunnels access required`가 표시됨
- Tunnel 메뉴 자체가 없음
- ChatGPT에서 Developer mode를 켤 수 없음
- 새 Plugin/App 연결을 만드는 `+` 버튼이 없음

이 경우 Railway부터 결제하지 않습니다. 계정 또는 Workspace 권한 문제이므로 해당 화면의 **키가 보이지 않는 부분만** 캡처해 확인을 요청합니다. API 키나 토큰은 캡처하지 않습니다.

---

## 1단계: OpenAI Secure MCP Tunnel 만들기

이 단계는 ChatGPT와 Railway 사이의 잠긴 전용 통로를 만듭니다.

1. [OpenAI Platform Tunnels](https://platform.openai.com/settings/organization/tunnels)에서 `Create tunnel`을 누릅니다.
2. 이름을 `naver-blog-seo`로 입력합니다.
3. 사용하려는 ChatGPT 개인 Workspace 또는 조직 Workspace를 연결 대상으로 포함합니다.
4. 생성 후 `tunnel_id`를 복사해 별도 메모장에 잠시 보관합니다.

정상적인 ID는 다음처럼 시작합니다.

```text
tunnel_...
```

5. [OpenAI Platform Runtime API keys](https://platform.openai.com/settings/organization/api-keys)를 엽니다. Tunnel ID가 속한 조직이 선택되어 있는지 확인한 뒤 터널 전용 Runtime API key를 만듭니다.
6. `CONTROL_PLANE_API_KEY`는 키 이름이 아니라 Railway에서 사용할 환경변수 이름입니다. 여기에 방금 만든 Runtime API key 값을 넣습니다.
7. 실행용 사용자/키에는 `Tunnels Read + Use` 권한이 필요합니다.
8. 생성된 키는 한 번만 보일 수 있으므로 안전한 비밀번호 관리자에 저장합니다.

주의:

- `OPENAI_ADMIN_KEY` 또는 조직 Admin key를 Railway에 넣지 않습니다.
- 일반 Project API key 화면이 아니라 위의 조직 Runtime API keys 화면에서 생성합니다.
- Runtime key는 ChatGPT 대화, GitHub 파일, 이메일에 붙여 넣지 않습니다.
- Runtime key는 다음 단계의 Railway `Variables` 화면에만 입력합니다.

이 단계에서 확보할 값은 정확히 두 개입니다.

```text
CONTROL_PLANE_TUNNEL_ID  → tunnel_... 형태
CONTROL_PLANE_API_KEY    → Runtime API key
```

---

## 2단계: 배포용 코드가 GitHub에 있는지 확인

Railway는 내 컴퓨터가 아니라 GitHub에서 코드를 가져갑니다. 따라서 다음 파일이 GitHub 저장소의 배포 브랜치에 보여야 합니다.

```text
Dockerfile
requirements-mcp.txt
deploy/start-cloud.sh
src/mcp_server.py
```

배포용 파일은 `feat/railway-private-mcp` 브랜치에 올립니다. 검증이 끝난 뒤 별도 승인으로 `main`에 합치면 Railway의 장기 운영이 더 단순해집니다.

이 네 파일 중 하나라도 GitHub 웹에서 보이지 않으면 Railway 배포를 시작하지 않습니다.

---

## 3단계: Railway 계정과 프로젝트 만들기

1. [Railway](https://railway.com/)에 접속합니다.
2. `Login`을 누르고 GitHub 계정으로 로그인합니다.
3. GitHub 연결 권한 요청이 나오면 `PeterYYong/blog_seo` 저장소 접근을 허용합니다.
4. 상시 운영에는 `Hobby` 요금제를 선택합니다.
5. [New Project](https://railway.com/new)를 누릅니다.
6. `Deploy from GitHub repo`를 선택합니다.
7. `PeterYYong/blog_seo`를 선택합니다.
8. 바로 배포하지 말고 가능하면 `Add Variables`를 선택합니다.

Railway가 저장소 루트의 `Dockerfile`을 자동으로 찾습니다. 별도 Python 설치나 명령어 입력은 필요하지 않습니다.

서비스의 `Settings → Source`에서 Railway가 연결한 브랜치에 위 `Dockerfile`이 실제로 존재하는지 확인합니다. `main.py` 또는 `streamlit`을 직접 실행하는 오래된 브랜치를 선택하면 MCP 배포가 되지 않습니다.

---

## 4단계: Railway에 비밀키 입력

Railway 프로젝트 안에서 생성된 `blog_seo` 서비스를 누른 다음 `Variables` 탭으로 이동합니다.

### 4-1. 필수 변수

`New Variable`을 눌러 한 줄씩 입력하거나 `RAW Editor`에서 입력합니다. 아래의 설명용 문구를 그대로 입력하지 말고 `=` 오른쪽을 실제 값으로 바꿉니다.

```dotenv
CONTROL_PLANE_TUNNEL_ID=tunnel_로_시작하는_실제_ID
CONTROL_PLANE_API_KEY=OpenAI_Platform에서_만든_Runtime_key

NAVER_API_HUB_CLIENT_ID=실제_Client_ID
NAVER_API_HUB_CLIENT_SECRET=실제_Client_Secret

NAVER_AD_API_KEY=실제_Search_Ads_API_key
NAVER_AD_SECRET_KEY=실제_Search_Ads_secret
NAVER_CUSTOMER_ID=실제_customer_ID

YOUTUBE_API_KEY=실제_YouTube_API_key
```

### 4-2. 처음에는 넣지 않는 변수

다음 기능은 나중에 추가합니다.

- `X_BEARER_TOKEN`
- `REDDIT_CLIENT_ID`, `REDDIT_CLIENT_SECRET`
- `THREADS_ACCESS_TOKEN`
- `KAKAO_REST_API_KEY`

Reddit과 Threads 활성화 플래그는 넣지 않거나 `false`로 둡니다.

```dotenv
REDDIT_API_APPROVED=false
THREADS_KEYWORD_SEARCH_ENABLED=false
```

### 4-3. 입력 후 확인

- 변수 이름의 앞뒤에 공백이 없어야 합니다.
- 따옴표는 넣지 않습니다.
- 값이 Railway 화면에서 점 또는 별표로 가려지는 것이 정상입니다.
- `Deploy` 또는 `Redeploy`를 눌러 적용합니다.

---

## 5단계: Railway 배포 상태 확인

1. 서비스의 `Deployments` 탭을 엽니다.
2. 최신 배포를 누른 뒤 `Build Logs`를 확인합니다.
3. 첫 빌드는 Python 패키지와 공식 OpenAI `tunnel-client`를 함께 준비하므로 몇 분 걸릴 수 있습니다.
4. 상태가 `Active`가 되면 `Deploy Logs`를 확인합니다.

정상일 때 로그에서 확인할 핵심 내용은 다음과 같습니다.

```text
Starting private Naver Blog SEO MCP server ...
MCP server is accepting local connections ...
Starting OpenAI Secure MCP Tunnel client.
```

`ERROR`, `required Railway variable ... is missing`, `401`, `403`이 반복되지 않아야 합니다.

### Railway 설정

서비스의 `Settings → Deploy`에서 다음처럼 설정합니다.

- Source branch: `Dockerfile`이 올라간 배포 브랜치
- Root Directory: 저장소 루트(비워 둠)
- Custom Build Command: 비워 둠
- Custom Start Command: 비워 둠
- Replicas: `1`
- Serverless: **꺼짐**
- Restart policy: 실패 시 재시작

Custom Start Command에 `python main.py` 또는 `streamlit run ...`이 들어 있으면 삭제합니다. 비워 두어야 `Dockerfile`의 `/app/deploy/start-cloud.sh`가 실행됩니다.

`Settings → Networking`에서 **Generate Domain을 누르지 않습니다.** 이 서버는 Secure MCP Tunnel을 사용하므로 공개 인터넷 주소가 필요하지 않습니다.

---

## 6단계: ChatGPT에 Tunnel 연결

1. PC 웹브라우저에서 ChatGPT를 엽니다.
2. `Settings → Security and login → Developer mode`가 켜져 있는지 확인합니다.
3. [ChatGPT Plugins](https://chatgpt.com/plugins)로 이동합니다.
4. `+` 버튼을 누릅니다.
5. 다음처럼 입력합니다.

```text
Name: Naver Blog SEO Research
Description: Naver, YouTube와 허용된 커뮤니티 근거로 글감을 찾고 초안과 SEO 감사를 수행합니다.
Connection: Tunnel
Tunnel: naver-blog-seo 선택 또는 tunnel_id 붙여넣기
```

6. `Create connection`을 누릅니다.
7. 서버에서 발견된 도구 목록을 검토합니다.

정상이면 다음 8개가 보여야 합니다.

1. `get_source_status`
2. `discover_community_topic_signals`
3. `youtube_trending_snapshot`
4. `discover_topic_opportunities`
5. `prepare_blog_draft_brief`
6. `audit_blog_draft`
7. `explain_blog_revision`
8. `get_naver_policy_baseline`

화면에 `Apps`, `Connectors`, `Scan Tools`라는 예전 또는 다른 명칭이 보이는 경우에도 원리는 같습니다. 연결 방식은 `Tunnel`, 대상은 앞에서 만든 `tunnel_id`, 최종 확인 대상은 8개 도구입니다.

---

## 7단계: 첫 연결 시험

새 대화를 만들고 도구 메뉴에서 `Naver Blog SEO Research`를 선택합니다. 첫 메시지로 다음을 입력합니다.

```text
get_source_status를 실행해서 현재 사용할 수 있는 데이터 출처와 빠진 출처를 표로 정리해줘. 비밀키 값은 절대 출력하지 마.
```

다음 세 출처가 `available=true`인지 확인합니다.

```text
naver_datalab_and_search
naver_search_ads
youtube_data_api
```

하나라도 `false`라면 ChatGPT 연결 문제가 아니라 해당 API 변수 또는 API 활성화 문제입니다.

두 번째 시험은 다음과 같습니다.

```text
내 블로그는 상황에 따라 주제를 정하는 일반 블로그야.
요즘 쓸 만한 한국어 글감 후보를 최대 5개만 찾아줘.
YouTube 한국 인기 영상에서 후보를 찾되, Naver 검색 수요와 최근 추세로 다시 검증해줘.
각 후보에 근거, 반대 근거, 조회 시각, 재검증 시점을 표시하고
빠른 트렌드·균형형·에버그린으로 구분해줘.
```

수치가 없는데 임의의 인기 키워드를 만들거나, 점수를 네이버 상위노출 확률이라고 표현하면 안 됩니다.

---

## 8단계: 실제 사용 순서

매번 복잡한 명령어를 기억할 필요 없이 한 대화에서 다음 순서로 요청합니다.

### A. 주제 추천

```text
Naver Blog SEO Research를 사용해서 지금 쓸 만한 주제 5개를 근거와 함께 추천해줘.
사용 가능한 커뮤니티 질문을 먼저 찾고 Naver와 YouTube로 재검증해줘.
빠른 트렌드·균형형·에버그린 전략을 모두 포함해줘.
```

### B. 하나 선택

```text
2번 주제로 진행할게. 독자의 핵심 질문, 검색 의도, 차별화할 실제 경험을 정리해줘.
```

### C. 실제 정보 확인

```text
초안을 쓰기 전에 내가 직접 확인해야 할 사실을 질문해줘. 방문·가격·맛·사진·협찬 여부를 추측하지 마.
```

### D. 초안과 검수

```text
내 답변만 사용해서 네이버 블로그 초안을 작성하고 audit_blog_draft로 검수해줘.
수정한 뒤 explain_blog_revision으로 무엇을 왜 바꿨는지 근거 등급별로 알려줘.
```

최종 발행은 자동으로 하지 않습니다. 사용자가 사실관계와 협찬 표시를 확인한 뒤 네이버 블로그에 직접 붙여 넣습니다.

---

## 문제 해결표

| 화면 또는 오류 | 뜻 | 해결 방법 |
|---|---|---|
| `ImportError: cannot import name 'fetch_metrics'` | Railway가 오래된 `main` 코드 또는 `python main.py` Start Command를 실행 중 | GitHub 배포 브랜치에 `Dockerfile`이 있는지 확인하고 Railway Source branch를 수정한 뒤 Custom Start Command를 비우고 Redeploy |
| Railway `required Railway variable ... is missing` | 필수 변수 누락 | Variables에서 해당 이름을 정확히 추가하고 Redeploy |
| Tunnel 로그 `401` | Runtime key 오류 | 키를 새로 만들고 Railway 값만 교체; Admin key 사용 금지 |
| Tunnel 로그 `403` | Tunnel 사용 권한 부족 | Platform에서 Tunnels Read + Use와 Workspace 연결 확인 |
| ChatGPT에 Tunnel이 안 보임 | Workspace 연결 불일치 | Tunnel 설정에서 대상 ChatGPT Workspace 포함 여부 확인 |
| 도구가 8개보다 적음 | 서버 이전 메타데이터를 보고 있음 | Railway Active 확인 후 ChatGPT 연결에서 Refresh/Scan Tools |
| `get_source_status`에서 Naver가 false | Naver 자격증명 누락 또는 종류 오류 | API HUB와 Search Ads 자격증명이 서로 별도인지 확인 |
| YouTube `403 quota` | 일일 할당량 소진 또는 API 미활성 | Google Cloud에서 YouTube Data API v3와 Quotas 확인 |
| Railway 서비스가 잠듦 | Serverless가 켜짐 | Settings → Deploy → Serverless 끄기 |
| Railway 서비스가 중단됨 | 비용 Hard limit 도달 가능 | Workspace Usage에서 Compute 사용량과 Hard limit 확인 |
| 빌드가 실패함 | Docker 빌드 또는 외부 패키지 문제 | 마지막 빨간 오류 20줄을 복사하되 비밀값은 제거하고 문의 |

---

## 비용과 안전 설정

- Railway Hobby, 서비스 1개, Replica 1개 사용
- Database와 Volume은 추가하지 않음
- Railway Agent는 사용하지 않음
- Compute 알림: `$7`
- Compute Hard limit: `$10`
- 예상 비용: 월 `$5~8`, 보수적 상한 `$10`

Hard limit에 도달하면 비용은 통제되지만 서비스가 중단됩니다.

## 절대 하지 말아야 할 것

- API 키를 ChatGPT 메시지에 붙여 넣기
- `.env` 또는 키가 들어 있는 파일을 GitHub에 업로드하기
- Railway에서 공개 Domain 만들기
- Runtime key 대신 조직 Admin key 사용하기
- 승인 전에 Reddit·Threads를 활성화하기
- 비용을 확인하지 않고 X API를 활성화하기
- 커뮤니티 게시물을 검증된 사실이나 전체 여론으로 표현하기

## 공식 근거

- [OpenAI: Secure MCP Tunnel](https://developers.openai.com/api/docs/guides/secure-mcp-tunnels)
- [OpenAI: Connect and test a plugin](https://developers.openai.com/plugins/deploy/connect-chatgpt)
- [OpenAI: Build an MCP server](https://developers.openai.com/plugins/build/mcp-server)
- [Railway: Deploy from GitHub](https://docs.railway.com/quick-start)
- [Railway: Variables](https://docs.railway.com/variables)
- [Railway: Services](https://docs.railway.com/services)
- [Railway: Cost control](https://docs.railway.com/pricing/cost-control)
