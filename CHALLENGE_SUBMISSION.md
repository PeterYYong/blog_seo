# The WebMCP Challenge 제출 문서

## 1. 제출 개요

**Naver Blog SEO MCP**는 사람이 폼을 조작하는 데모에 그치지 않습니다. 브라우저 에이전트가 페이지에서 SEO 기능을 발견하고 실행할 수 있도록 8개 도구를 WebMCP로 직접 등록하며, 원격 MCP 클라이언트에는 같은 도구를 Streamable HTTP로 제공합니다.

> 공식 자료: [WebMCP 제안 저장소](https://github.com/webmachinelearning/webmcp), [WebMCP 사양 초안](https://webmachinelearning.github.io/webmcp/), [Challenge 규정](https://webmcp.devpost.com/rules). 제출 직전 마감일, 참가 자격, 영상/공개 URL 요건은 공식 페이지에서 다시 확인해야 합니다. 현재 실행 환경은 외부 공식 페이지 요청이 차단되어 2026-09-01에 원문을 재수집하지 못했습니다.

## 2. 요구사항 체크리스트

| 요구사항 | 상태 | 구현 증거 |
|---|---|---|
| 실제 웹 경험 | 충족 | `/`의 반응형 입력·결과 UI |
| 명령형 WebMCP 도구 | 충족 | `navigator.modelContext.registerTool()` 8회 등록 |
| 설명과 JSON 입력 스키마 | 충족 | 각 도구의 `name`, `description`, `inputSchema` |
| 실행 가능한 도구 | 충족 | 브라우저 내 계산·확장·상태 실행 함수 |
| 사용자에게 보이는 대체 경험 | 충족 | 미지원 브라우저에서도 계산 버튼 작동 |
| 안전/투명성 | 충족 | 라이브 값 미조작, 오류 코드, 조회 시각, 근거/출처 |
| 접근 가능한 데모 URL | 배포 필요 | 로컬 및 Docker 검증 후 별도 승인으로 배포 |
| 제출 영상/설명/소스 링크 | 승인 필요 | 아래 3분 시나리오와 본 문서 준비 완료 |
| 참가 자격·마감 준수 | 재확인 필요 | 제출 직전 공식 규정 원문 확인 |

## 3. 아키텍처

```text
Browser agent ─ WebMCP ─ web/index.html (8 tools)
Human        ─ UI fallback ┘

MCP client ─ Streamable HTTP /mcp/ ─ FastMCP (8 tools)
                                      │
                                      └─ seo_service.py
                                         ├─ explicit input validation
                                         ├─ calculator.py
                                         └─ keyword_expander.py
```

브라우저 데모의 즉시 실행 계산은 네트워크나 API 키를 요구하지 않습니다. 서버 구현은 같은 수식과 응답 계약을 사용합니다. Naver 라이브 데이터가 필요한 도구는 설정/권한이 없으면 구조화된 `NAVER_ADS_NOT_CONFIGURED` 또는 `LIVE_LOOKUP_DISABLED`를 반환합니다.

## 4. 심사 기준별 근거

### 유용성과 독창성

- 한국어 Naver Blog 생태계에 특화된 Sk/Ek 분석을 에이전트 도구로 전환했습니다.
- 하나의 키워드부터 50개 배치까지 순위화하며, 저검색량을 기회로 오인하지 않습니다.

### WebMCP 활용도

- 페이지 로드 시 도구 8개가 명령형 WebMCP API에 등록됩니다.
- 각 도구는 좁고 명확한 목적, 설명, JSON Schema, 구조화 결과를 가집니다.
- WebMCP 미지원 환경을 명확히 표시하면서 인간용 기능은 유지합니다.

### 완성도와 신뢰성

- 모바일 대응 UI, 오류 상태, UTC 조회 시각, 계산 근거, 출처를 포함합니다.
- 단위 테스트, 실제 MCP 초기화/`tools/list`/호출, 컨테이너 헬스 체크를 검증 대상으로 둡니다.
- 비밀값 파일은 `.gitignore` 및 `.dockerignore`에서 제외합니다.

## 5. 3분 이내 데모 시나리오

1. **0:00–0:25** — 첫 화면에서 문제(검색량만으로는 경쟁도를 알 수 없음)와 `WebMCP · 8 tools registered` 배지를 보여줍니다.
2. **0:25–0:55** — `서울 캠핑`, 검색량 `2400`, 문서 수 `1200`으로 계산해 `Sk=0.5`, `blue-ocean`, 출처와 조회 시각을 보여줍니다.
3. **0:55–1:35** — 브라우저 에이전트에 “서울 캠핑 SEO 지표를 계산하고 추천 여부를 설명해 줘”라고 요청해 `calculate_seo_metrics` 호출을 보여줍니다.
4. **1:35–2:05** — `expand_keywords`를 호출하고 롱테일 후보를 확인합니다.
5. **2:05–2:30** — `get_configuration_status`로 비밀값 없이 연동 상태만 반환되는 장면을 보여줍니다.
6. **2:30–2:50** — 미설정 라이브 도구가 데이터를 꾸며내지 않고 명확한 오류를 반환함을 보여줍니다.
7. **2:50–3:00** — MCP `/mcp/`와 동일한 8개 도구, 오픈소스 저장소 링크로 마무리합니다.

## 6. 검증 명령

```bash
pytest -q
python -m compileall -q src tests
docker build -t naver-blog-seo-webmcp .
docker run --rm -d --name naver-seo-demo -p 8000:8000 naver-blog-seo-webmcp
curl --fail http://localhost:8000/healthz
```

MCP Inspector 또는 SDK 클라이언트에서 `http://localhost:8000/mcp/`에 연결해 `tools/list`가 정확히 8개인지 확인하고 `health_check`, `calculate_seo_metrics`를 호출합니다.

## 7. 제한점과 비용

- WebMCP는 실험적 브라우저 기능이므로 지원 빌드/플래그 또는 프로그램 참여 권한이 필요할 수 있습니다.
- Challenge 규정 원문은 제출 직전에 네트워크 가능한 환경에서 재확인해야 합니다.
- Naver Search Ads/Search API의 계정, 할당량 및 약관은 사용자가 관리합니다. 이 데모는 유료 소셜 API를 추가하지 않습니다.
- 로컬 실행 비용은 무료입니다. 공개 데모는 선택한 호스팅의 컴퓨트 비용, 라이브 조회는 Naver 측 정책/할당량에 따릅니다.

## 8. 제출 전 승인 필요 작업

- 공개 저장소/데모 URL 확정 및 브랜치 push
- 공식 규정의 최신 마감·자격·필수 제출물 재확인
- 3분 영상 녹화 및 공개 업로드
- Challenge 폼의 실제 제출
- 운영 Railway 또는 Secure Tunnel 설정 변경(현재 변경하지 않음)
