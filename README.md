# Naver Blog SEO MCP · WebMCP Challenge

Naver 블로그 키워드의 포화도(`Sk`)와 효율성(`Ek`)을 계산하고, 같은 8개 기능을 **MCP Streamable HTTP**와 브라우저의 **WebMCP** 인터페이스로 제공하는 실행 가능한 데모입니다. 라이브 데이터가 없을 때는 값을 추측하지 않고 명시적인 구조화 오류를 반환합니다.

## 핵심 기능

- `navigator.modelContext.registerTool()`로 등록되는 8개 브라우저 도구
- MCP `tools/list`에서 동일한 이름으로 노출되는 8개 서버 도구
- 모든 성공 결과에 `retrieved_at`, `evidence`, `sources`; 모든 오류에 안정적인 `code`, `message`, `retryable`
- 명시적 문자열 길이, 수치 범위, 배치 크기 검증
- 비밀값 자체가 아닌 환경 변수 설정 여부만 노출
- X, Reddit, Threads는 비용/권한 없는 연동을 시도하지 않고 `not configured`로 표시

## 도구 목록

| 도구 | 역할 | 라이브 API 필요 |
|---|---|---:|
| `expand_keywords` | 규칙 기반 롱테일 후보 확장 | 아니요 |
| `calculate_seo_metrics` | 제공한 측정값으로 Sk/Ek 계산 | 아니요 |
| `analyze_keyword` | 단일 키워드 분류 | 아니요 |
| `analyze_keyword_batch` | 최대 50개 분석 및 순위화 | 아니요 |
| `get_related_keywords` | Naver Ads 연동의 안전한 가용성 응답 | 예 |
| `get_trending_keywords` | 선택적 트렌드 연동의 안전한 상태 응답 | 예 |
| `get_configuration_status` | 비밀 노출 없는 설정 상태 | 아니요 |
| `health_check` | 전송 계층 준비 상태 | 아니요 |

## 로컬 실행

```bash
python -m venv .venv
. .venv/bin/activate
pip install -r requirements.txt
uvicorn src.mcp_server:app --host 0.0.0.0 --port 8000
```

- WebMCP 데모: <http://localhost:8000/>
- MCP Streamable HTTP: `http://localhost:8000/mcp/`
- 헬스 체크: <http://localhost:8000/healthz>

WebMCP가 활성화된 지원 브라우저에서는 헤더가 `8 tools registered`로 바뀝니다. 그 외 브라우저에서도 동일 계산을 직접 체험할 수 있지만 에이전트 등록은 되지 않습니다.

## MCP 클라이언트 예시

```json
{
  "mcpServers": {
    "naver-blog-seo": {
      "url": "http://localhost:8000/mcp/"
    }
  }
}
```

기존 Secure MCP Tunnel에는 공개 URL 대신 현재 내부 서비스의 `/mcp/` 경로를 지정합니다. 저장소에는 Tunnel ID나 토큰을 기록하지 않습니다.

## 선택적 환경 변수

```dotenv
NAVER_AD_API_KEY=example
NAVER_AD_SECRET_KEY=example
NAVER_CUSTOMER_ID=example
NAVER_CLIENT_ID=example
NAVER_CLIENT_SECRET=example
```

실제 값은 커밋하지 마세요. Challenge 데모의 계산·확장 도구는 키 없이 작동합니다. 현재 공개 데모 서버는 운영 배포를 보호하기 위해 라이브 조회를 의도적으로 수행하지 않습니다.

## Docker

```bash
docker build -t naver-blog-seo-webmcp .
docker run --rm -p 8000:8000 naver-blog-seo-webmcp
curl --fail http://localhost:8000/healthz
```

## 테스트

```bash
pytest -q
python -m compileall -q src tests
```

구현 구조, 공식 요구사항 매핑, 3분 데모와 제출 전 체크리스트는 [`CHALLENGE_SUBMISSION.md`](CHALLENGE_SUBMISSION.md)를 참고하세요. 기존 Streamlit 분석 화면은 `streamlit run src/app.py`로 계속 실행할 수 있습니다.

## 데이터 해석 주의

검색량 50 미만은 통계적으로 불충분한 값으로 분류합니다. 계산 결과는 콘텐츠 기획 보조 지표이며 검색 노출을 보장하지 않습니다. 자세한 수식은 [`METHODOLOGY.md`](METHODOLOGY.md)에 있습니다.
