# 🧪 Naver Search Ecology Architect (닥터스톤 SEO 에이전트)

**2026년 네이버 검색 환경(SmartBlock, AiRSearch)**에 최적화된 자율형 키워드 발굴 에이전트입니다.  
단순 검색량이 아닌 **시장 포화도($S_k$)**와 **키워드 효율성($E_k$)** 수식을 기반으로, 경쟁이 적고 검색 니즈가 확실한 **'블루오션'** 토픽을 과학적으로 발굴합니다.

---

## 🚀 주요 기능 (Key Features)

### 1. 🧠 Auto-Brainstorming (자율 확장)
- 사용자가 "맛집" 같은 대주제만 던져도, 에이전트가 알아서 **"데이트 코스", "현지인 맛집", "가성비 오마카세"** 등으로 세부 주제를 확장합니다.
- 상황별 최적의 접미사(Suffix)를 조합하여 롱테일 키워드를 생성합니다.

### 2. 🌊 Trend Deep Diver (실시간 트렌드 분석)
- **`src/trend_hunter.py`**
- 실시간 급상승 검색어(Signal.bz)를 크롤링하여 트렌드를 파악합니다.
- 해당 트렌드 키워드를 시드로 삼아 심층 분석(Deep Dive)을 수행, 당장 글을 써야 할 '핫한' 주제를 선별합니다.

### 3. 🦈 Niche Hunter (니치 마켓 발굴)
- **`src/niche_hunter.py`**
- 특정 관심사(예: "미국 주식")를 입력하면, 네이버 연관 검색어 API를 통해 **1,000개 이상의 관련 키워드**를 싹쓸이합니다.
- 대량의 데이터 속에서 문서 발행량 대비 검색량이 높은 **숨겨진 보석(Blue Ocean)**을 찾아냅니다.

### 4. 🧮 Scientific Scoring (과학적 지표)
모든 분석은 닥터스톤만의 고유 공식을 따릅니다.
- **$S_k$ (Saturation Index, 포화도):** $\frac{\text{총 문서수}}{\text{월간 검색량}}$
  - $0.1 \le S_k < 1.0$: **💎 블루오션 (강력 추천)**
  - $S_k \ge 5.0$: **💀 레드오션 (진입 금지)**
- **$E_k$ (Efficiency Score, 효율성):** 검색 규모와 전환율을 고려한 최종 점수.

---

## 🛠️ 설치 및 설정 (Setup)

### 1. 필수 라이브러리 설치
```bash
pip install requests pandas tabulate beautifulsoup4 lxml
```

### 2. API 키 설정 (`secrets.json`)
네이버 검색광고 API와 검색(Search) API 키가 필요합니다. 프로젝트 루트에 `secrets.json` 파일을 생성하세요.

**`secrets.json` 형식:**
```json
{
  "NAVER_AD_API_KEY": "YOUR_AD_API_KEY",
  "NAVER_AD_SECRET_KEY": "YOUR_AD_SECRET_KEY",
  "NAVER_CUSTOMER_ID": "YOUR_CUSTOMER_ID",
  "NAVER_CLIENT_ID": "YOUR_SEARCH_CLIENT_ID",
  "NAVER_CLIENT_SECRET": "YOUR_SEARCH_CLIENT_SECRET"
}
```

---

## 💻 사용 방법 (Usage)

### 1️⃣ 기본 키워드 분석 (Basic Agent)
특정 키워드 하나에 대해 아이디어를 확장하고 분석합니다.
```bash
python src/main.py --seed "강남역 맛집"
```

### 2️⃣ 실시간 트렌드 사냥 (Trend Hunter)
지금 뜨고 있는 이슈 중 블루오션 키워드를 찾습니다.
```bash
python src/trend_hunter.py
```

### 3️⃣ 분야별 대량 채굴 (Niche Hunter)
특정 카테고리를 입력하면 관련 키워드 수백~수천 개를 분석하여 리포트를 만듭니다. (시간 소요됨)
```bash
### 4️⃣ 웹 대시보드 (Streamlit)
웹 브라우저에서 편리하게 분석할 수 있습니다.
```bash
streamlit run src/app.py
```
- **Mode A:** 단일 키워드 분석
- **Mode B:** 실시간 트렌드 딥 다이브
- **Mode C:** 니치 마켓 헌터 (카테고리 채굴)

---

## 📂 파일 구조 (File Structure)

```
📂 루트 (Topic/)
├── 📄 main.py                # (Legacy) 구형 진입점
├── 📄 secrets.json           # API 키 저장소 (필수)
├── 📄 README.md              # 프로젝트 설명서
│
├── 📂 src/                   # 핵심 소스 코드
│   ├── 📄 main.py            # [메인] 기본 에이전트 실행 파일
│   ├── 📄 trend_hunter.py    # [모듈] 실시간 트렌드 분석기
│   ├── 📄 niche_hunter.py    # [모듈] 대량 연관검색어 채굴기
│   ├── 📄 data_fetcher.py    # Naver API 연동 및 데이터 수집
│   ├── 📄 calculator.py      # Sk, Ek 지표 계산 로직
│   └── 📄 keyword_expander.py# 브레인스토밍 및 키워드 확장 로직
│
└── 📂 reports/               # 분석 결과 리포트 저장소 (.md)
    ├── 📄 result_REAL_...    # 기본 분석 결과
    ├── 📄 TREND_HUNT_...     # 트렌드 분석 결과
    └── 📄 NICHE_...          # 니치 마켓 분석 결과
```

---

**Tip:** 생성된 Markdown 리포트(`reports/*.md`)는 VS Code나 Obsidian 등에서 열어보면 깔끔한 표 형태로 확인할 수 있습니다.
