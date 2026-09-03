# Naver Blog Topic Opportunity Explorer

네이버 공식 API의 월간 검색량 추정치와 블로그 검색 결과 수를 비교해, 먼저 검토할 블로그 주제 후보를 좁히는 Streamlit 대시보드입니다. Google Trends 한국 RSS는 급상승 주제의 출발점으로 사용합니다.

`S_k`와 `E_k`는 네이버 공식 랭킹 점수나 상위 노출 확률이 아니라, 같은 실행 안에서 후보를 비교하기 위한 로컬 보조지표입니다.

## 주요 기능

| 모드 | 동작 | 기본 조회량 (슬라이더 최대) |
|---|---|---:|
| 기초 키워드 분석 | 입력어를 의도별 표현으로 확장한 뒤 Search Ads 수요와 Blog Search 결과 수를 확인 | 20개 (30개) |
| 한국 급상승 주제 | Google Trends 한국 RSS의 주제를 가져와 네이버 지표로 교차 확인 | 15개 (50개) |
| 니치 마켓 탐색 | Search Ads 연관 키워드를 수요순으로 정렬한 뒤 Blog Search로 검증 | 30개 (50개) |

- 외부 API 실패를 0으로 바꾸지 않고 해당 행을 제외합니다.
- Search Ads가 반환한 `< 10` 값은 범위 추정임을 표시하고 원문 값을 보존합니다.
- 월간 검색량 추정이 50 미만인 항목은 `근거 부족`으로 분류합니다.
- 인증·할당량 오류는 남은 호출을 즉시 중단하고, 같은 출처의 서버·네트워크 오류가 두 키워드에서 연속되면 중단합니다.
- 결과는 키워드 10분, 급상승 주제 5분 동안만 유효하며 조회 시각을 표시합니다.
- 공개 데모는 세션당 30초 간격과 프로세스 전체 시간당 10회의 분석 제한을 둡니다. 대규모 운영에는 로그인 또는 외부 저장소 기반 제한이 추가로 필요합니다.

## 설치

Python 3.12를 권장합니다.

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

## API 자격 증명

다음 값을 환경 변수, 로컬 `secrets.json`, 또는 Streamlit secrets에 설정합니다. 비밀 파일은 저장소에 커밋하지 않습니다.

```text
NAVER_AD_API_KEY
NAVER_AD_SECRET_KEY
NAVER_CUSTOMER_ID

NAVER_API_HUB_CLIENT_ID
NAVER_API_HUB_CLIENT_SECRET
```

기존 Naver Developers 검색 키도 유예 기간 동안 지원합니다.

```text
NAVER_CLIENT_ID
NAVER_CLIENT_SECRET
```

검색광고 키는 월간 검색량·연관 키워드용이고, API HUB 또는 기존 Developers 키는 블로그 검색 결과 수용입니다. 둘 다 있어야 세 분석 모드가 활성화됩니다.

- [Naver Search Ads API](https://naver.github.io/searchad-apidoc/)
- [NAVER API HUB](https://guide.ncloud-docs.com/docs/apihub-overview)
- [Naver Blog Search API](https://api.ncloud-docs.com/docs/naver-api-hub-search-blog)

## 실행

```bash
streamlit run src/app.py
```

CLI도 사용할 수 있습니다.

```bash
python -m src.main --seed "강남역 맛집" --limit 20
python -m src.trend_hunter --trend-limit 5 --keyword-limit 30
python -m src.niche_hunter --seed "미국 주식" --limit 30
```

CLI는 `reports/`에 Markdown 보고서를 생성합니다. 범위 추정 여부와 PC·모바일 원문 값도 함께 기록합니다.

## 검증

```bash
python -m compileall -q src tests
pytest -q
```

GitHub Actions가 Python 3.12에서 전체 회귀 테스트를 실행합니다. 실제 API 키 없이도 API 계약, 오류 처리, 세 Streamlit 모드, CLI 보고서를 모의 응답으로 검증합니다.

자세한 지표 정의와 한계는 [METHODOLOGY.md](METHODOLOGY.md)를 참고하세요.
