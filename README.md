# Naver Blog Topic Opportunity Explorer

네이버 공식 API의 월간 검색량 추정치, 블로그 검색 결과 수, DataLab 검색 추세를 함께 확인해 먼저 검토할 블로그 주제 후보를 좁히는 Streamlit 대시보드입니다. Google Trends 한국 RSS는 급상승 주제의 출발점으로만 사용합니다.

화면의 `수요 대비 글 수`는 블로그 검색 결과 수를 월간 검색량으로 나눈 약한 공급 대리값이며, 네이버 공식 랭킹 점수나 상위 노출 확률이 아닙니다. Streamlit 분석은 레거시 `E_k`를 계산하거나 정렬에 사용하지 않으며 화면과 CSV에도 내보내지 않습니다. 기존 CLI에는 하위 호환성을 위해 `E_k`가 남아 있을 수 있습니다.

## 주요 기능

| 모드 | 동작 | 기본 조회량 (슬라이더 최대) |
|---|---|---:|
| 기초 키워드 분석 | 입력어에 대해 Search Ads가 실제 반환한 연관어를 목록 내 검색량이 높은·중간·낮은 그룹에서 고른 뒤 Blog Search와 DataLab으로 검증 | 20개 (30개) |
| 한국 급상승 주제 | Google Trends 한국 RSS 주제별로 Search Ads 연관어를 찾고 Naver 지표로 교차 확인 | 주제 5개 × 연관어 3개 (주제 10개 × 5개) |
| 니치 마켓 탐색 | Search Ads 연관어를 목록 내 검색량이 높은·중간·낮은 그룹에서 균형 있게 선택해 검증 | 30개 (50개) |

- 임의의 고정 접미사를 붙이지 않고, Search Ads가 반환한 실제 연관어만 후보로 사용합니다.
- 검색량순 목록을 `목록 내 높은 그룹`, `목록 내 중간 그룹`, `목록 내 낮은 그룹`으로 나눠 순환 선택합니다. 이 이름은 해당 응답 목록 안의 상대 구간이며 실제 롱테일 여부나 절대 수요 등급을 뜻하지 않습니다.
- DataLab은 `0~100` 범위의 상대 관심 지수만 받아 최근 7일 평균을 직전 28일 평균과 비교합니다. 최신 기준일이 요청 종료일보다 2일을 초과해 오래되면 현재 흐름으로 사용하지 않습니다.
- DataLab은 키워드를 최대 5개씩 호출합니다. 한 배치가 실패해도 앞서 확인한 배치 결과는 보존하고, 실패·미조회 항목을 따로 표시합니다.
- 먼저 볼 추천 카드는 최대 5개이며 독자 질문, 글의 방향, 지금 볼 이유, 반대 근거, 재확인 시점을 함께 표시합니다.
- 추천 카드는 가능한 월간 검색량의 최솟값이 50 이상이고 가능한 `수요 대비 글 수`의 최댓값이 5 미만인 후보만 대상으로 합니다.
- 추천 순서는 보수적 기준 충족 여부, 범위에 따라 판단이 바뀌지 않는지, DataLab 흐름, `수요 대비 글 수`의 보수적 최댓값, 검색량 순입니다. 이 값들이 모두 같으면 원래 후보 순서를 유지합니다. 의사 정밀한 종합 점수는 사용하지 않습니다.
- 외부 API 실패나 누락값을 0으로 바꾸지 않습니다. 근거가 불완전하면 그 상태를 표시하고 추천 확정을 보류합니다.
- Search Ads가 반환한 `< 10` 같은 검열값은 가능한 검색량 범위, PC·모바일 원문, `수요 대비 글 수` 범위로 표시합니다. 범위에 따라 해석이 달라지면 `범위에 따라 달라짐`으로 알립니다.
- 월간 검색량 추정이 50 미만인 항목은 `판단 자료 부족`으로 해석합니다. 이 기준을 포함한 모든 해석 경계는 네이버 공식 기준이 아닙니다.
- 인증·할당량 오류는 남은 호출을 즉시 중단하고, 같은 출처의 서버·네트워크 오류가 두 키워드에서 연속되면 중단합니다.
- Naver 지표는 10분, Google Trends 주제는 5분, DataLab 시계열은 15분 동안 캐시합니다. 추천 카드와 표에 분석 시각(KST)과 검색 관심 최신 기준일을 구분해 표시합니다.
- YouTube 교차 검증은 아직 연결하지 않았습니다. 카드에는 `외부 확인 상태: YouTube 관심 신호 미확인`이라고 표시하며 독립 출처가 확인된 인기 주제로 단정하지 않습니다.
- 저장되는 `naver_evidence_complete` 상태는 이번 실행의 Search Ads·Blog Search·DataLab 근거가 모두 확인됐는지만 뜻합니다. YouTube 교차 검증 완료를 뜻하지 않으며, 외부 출처 상태는 별도로 계속 확인 전입니다.

## 설치

Python 3.12를 권장합니다.

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

## 비공개 접근 설정

앱은 `APP_PASSWORD`가 없거나 허용 형식이 아니면 분석 화면이나 API 클라이언트를 만들기 전에 잠기는 fail-closed 방식입니다. 허용 형식은 **숫자 4자리 PIN** 또는 **20~256자 비밀번호**입니다. 값을 아는 세션만 들어갈 수 있으며, 사이드바의 `로그아웃` 버튼으로 세션 인증을 해제할 수 있습니다.

Streamlit Community Cloud의 앱 설정에서 **Secrets**에 다음 값을 추가합니다. 실제 비밀번호/PIN은 채팅이나 저장소에 올리지 말고 직접 설정하세요.

```toml
APP_PASSWORD = "4827"  # 형식 예시일 뿐이며 이 값을 그대로 사용하지 마세요.
```

배포 환경에서는 Streamlit Secrets를 우선 사용합니다. 같은 키가 프로세스 환경에도 있으면 Secrets 값이 우선하므로 비밀번호 교체가 오래된 환경 변수에 가로막히지 않습니다. 저장 후 앱을 재시작하고 다음을 직접 확인하세요.

PIN은 반드시 따옴표로 감싼 문자열로 입력하세요. 예를 들어 `0123`을 따옴표 없이 쓰면 앞의 `0`이 보존되지 않고 유효한 PIN으로 인식되지 않습니다. 숫자 4자리가 아닌 짧은 값, 전각 숫자, 앞뒤 공백은 거부됩니다. 보안이 더 중요하면 20자 이상의 고유한 비밀번호를 사용하세요.

1. `APP_PASSWORD`가 없거나 허용 형식이 아닐 때 잠금 화면만 보이는지 확인합니다.
2. 시크릿을 설정한 뒤 새 시크릿 창에서 로그인 화면이 먼저 보이고 분석 UI가 노출되지 않는지 확인합니다.
3. 잘못된 비밀번호는 거부되고 설정한 비밀번호만 통과하는지 확인합니다.
4. 로그아웃하면 분석 결과와 인증 상태가 지워지고 로그인 화면으로 돌아오는지 확인합니다.

로컬 실행도 저장소에서 제외되는 `.streamlit/secrets.toml`에 같은 TOML 값을 넣는 방식을 권장합니다. `.env`, `.env.*`, `.streamlit/`, `.streamlit/secrets.toml`, `secrets.json`은 Git에서 제외됩니다. 환경 변수 방식도 지원하지만 셸 명령 기록에 비밀번호가 남을 수 있으므로 문서에서는 직접 입력 명령을 제공하지 않습니다.

비밀번호/PIN은 세션 상태나 로그에 평문으로 저장하지 않습니다. 인증 세션에는 서버 메모리 키로 서명된 자격 증명 버전과 인증 시각만 저장하며 최대 12시간 뒤 만료됩니다. `APP_PASSWORD`를 교체하거나 서버의 서명 키가 바뀌면 기존 세션은 무효화됩니다. 한 세션에서 5회 연속 실패하면 5분 동안 로그인이 잠깁니다.

> **4자리 PIN의 한계:** 가능한 조합이 10,000개뿐이고 실패 제한도 현재 브라우저 세션 단위이므로, 새 세션을 반복 생성하는 공격까지 막지는 못합니다. 따라서 PIN은 개인용 도구의 가벼운 접근 방지용입니다. 엄밀하게 본인만 접근해야 하거나 API 할당량 보호가 중요하면 20자 이상의 비밀번호 또는 Cloudflare Access/OIDC 같은 외부 인증을 사용하세요.

## API 자격 증명

다음 값을 환경 변수, 로컬 `secrets.json`, 또는 Streamlit Secrets에 설정합니다. 비밀 파일은 저장소에 커밋하지 않습니다.

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

검색광고 키는 월간 검색량·연관 키워드용이고, API HUB 또는 기존 Developers 키는 블로그 검색 결과 수와 DataLab 검색 추세용입니다. 둘 다 있어야 세 분석 모드가 활성화됩니다.

- [Naver Search Ads API](https://naver.github.io/searchad-apidoc/)
- [NAVER API HUB](https://guide.ncloud-docs.com/docs/apihub-overview)
- [Naver Blog Search API](https://api.ncloud-docs.com/docs/naver-api-hub-search-blog)
- [Naver DataLab Search Trend API](https://api.ncloud-docs.com/docs/naver-api-hub-search-trend)

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

CLI는 `reports/`에 Markdown 보고서를 생성합니다. 범위 추정 여부와 PC·모바일 원문 값도 함께 기록합니다. Streamlit의 새 추천 카드와 DataLab 교차 검증은 웹 UI에 적용됩니다.

## 이전 버전 백업과 복구

이번 개선 전 `main`은 [`backup/pre-recommendation-v2-20260904`](https://github.com/PeterYYong/blog_seo/tree/backup/pre-recommendation-v2-20260904) 브랜치에 보존되어 있습니다. 백업 기준 커밋은 `7e001085a119e7c9069fae690c14496276c7d560`입니다.

> **보안 경고:** 이 정확한 백업 버전에는 비밀번호 보호가 없습니다. 로컬 참고·비교용으로만 사용하고 공개 URL이나 Streamlit Community Cloud에 그대로 배포하지 마세요.

이전 버전을 별도 브랜치에서 확인하거나 실행하려면 다음처럼 체크아웃합니다.

```bash
git fetch origin
git switch -c restore-pre-recommendation-v2 origin/backup/pre-recommendation-v2-20260904
streamlit run src/app.py --server.address 127.0.0.1
```

운영 기능을 되돌려야 한다면 백업 전체를 공개 배포하지 말고 필요한 코드만 선택적으로 복구하되 현재 비밀번호 보호를 유지하세요. 전체 복구가 꼭 필요하면 동등한 접근 제어를 먼저 다시 적용하고 테스트한 복구 브랜치를 Pull Request로 반영합니다. 강제 푸시는 사용하지 않습니다.

## 검증

```bash
python -m compileall -q src tests
pytest -q
```

GitHub Actions가 Python 3.12에서 전체 회귀 테스트를 실행합니다. 실제 API 키 없이도 API 계약, 오류 처리, 비밀번호 접근 제어, 세 Streamlit 모드, 후보 구간 선택, DataLab 추세와 불확실성 계산, CLI 보고서를 모의 응답으로 검증합니다.

자세한 지표 정의와 한계는 [METHODOLOGY.md](METHODOLOGY.md)를 참고하세요.
