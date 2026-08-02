"""Build a fact-gated content brief before any prose is generated."""

from __future__ import annotations

from typing import Any


FNB_REQUIRED = (
    "place_name",
    "location",
    "visit_date",
    "visit_context",
    "ordered_items",
    "prices",
    "taste_and_texture_notes",
    "one_strength",
    "one_limitation",
)

FNB_OPTIONAL = (
    "parking",
    "public_transport",
    "waiting_time",
    "noise_and_atmosphere",
    "seating",
    "restroom",
    "business_hours_source",
    "return_intent",
    "photo_inventory",
)


def _has_value(value: Any) -> bool:
    if value is None:
        return False
    if isinstance(value, str):
        return bool(value.strip())
    if isinstance(value, (list, tuple, set, dict)):
        return bool(value)
    return True


def prepare_draft_brief(
    primary_keyword: str,
    topic: str,
    content_type: str = "fnb_review",
    audience: str = "네이버 검색 사용자",
    search_intent: str = "experience_and_information",
    facts: dict[str, Any] | None = None,
    commercial_relationship: str = "none",
) -> dict[str, Any]:
    """Return a brief that prevents the writer from inventing user experience."""

    facts = dict(facts or {})
    if content_type == "fnb_review":
        required = FNB_REQUIRED
        optional = FNB_OPTIONAL
        sections = [
            "제목 후보 3개: 장소·지역·구체 효용을 자연스럽게 표현",
            "경제적 이해관계 표시: 해당 시 제목 또는 본문 첫 부분",
            "짧은 도입: 방문 계기와 독자가 얻을 정보",
            "위치·이동·주차·웨이팅: 확인된 사실만",
            "매장 분위기: 소음·좌석·이용 목적 등 관찰 사실",
            "주문 메뉴·가격·맛: 사용자가 제공한 감각 기록만",
            "먹는 팁: 직접 시도한 조합만",
            "장점과 아쉬운 점: 각각 구체적 근거 포함",
            "재방문 조건과 3줄 핵심 정보",
            "사진 배치 제안: 실제 보유 사진 목록에만 연결",
        ]
        tone = {
            "style": "친근한 해요체와 자연스러운 구어체",
            "mobile": "한 문단 한 정보, 긴 문단은 3~4줄 수준으로 분할",
            "avoid": [
                "결론적으로",
                "요약하자면",
                "살펴보겠습니다",
                "알아보았습니다",
                "과도한 접속사·느낌표·이모지",
            ],
            "note": "첨부 F&B 톤 가이드에 따른 문체 선호이며 검색 순위 공식이 아님",
        }
    else:
        required = ("problem_or_question", "verified_key_points", "sources", "one_limitation")
        optional = ("examples", "comparison", "images", "update_date")
        sections = [
            "정확한 제목과 한 문장 답변",
            "독자가 이 글에서 해결할 문제",
            "검증된 핵심 정보와 출처",
            "구체적 예시 또는 비교",
            "한계·예외·적용 조건",
            "실행 가능한 마무리",
        ]
        tone = {
            "style": "쉽고 직접적인 한국어",
            "mobile": "소제목과 짧은 문단으로 핵심 정보를 빠르게 찾도록 구성",
            "avoid": ["근거 없는 단정", "낚시성 제목", "키워드 반복", "출처 없는 최신 수치"],
            "note": "사용자 가치·정확성 중심 편집 원칙",
        }

    missing_required = [field for field in required if not _has_value(facts.get(field))]
    available_optional = [field for field in optional if _has_value(facts.get(field))]
    relationship_requires_disclosure = commercial_relationship not in {"none", "self_paid"}

    return {
        "topic": topic.strip(),
        "primary_keyword": " ".join(primary_keyword.split()),
        "content_type": content_type,
        "audience": audience,
        "search_intent": search_intent,
        "ready_for_full_draft": not missing_required,
        "missing_required_facts": missing_required,
        "verified_facts": {key: value for key, value in facts.items() if _has_value(value)},
        "available_optional_facts": available_optional,
        "commercial_relationship": commercial_relationship,
        "disclosure_required": relationship_requires_disclosure,
        "outline": sections,
        "tone": tone,
        "writer_rules": [
            "Do not invent a visit, purchase, taste, texture, price, waiting time, address, or photo.",
            "Mark unresolved details as [확인 필요] in a planning brief; do not leave them in publish-ready prose.",
            "Use the primary keyword only where natural; never target a fixed density.",
            "Distinguish official policy, API evidence, user experience, and editorial suggestion.",
            "Keep one meaningful limitation instead of writing a uniformly positive advertisement.",
            "If price was not recorded, mark it as unverified and omit it; never guess.",
            "If no limitation was observed, state that in the brief and do not manufacture one.",
            "After drafting, run the policy audit and attach a change-rationale log.",
        ],
        "draft_gate": (
            "Full draft may be generated from verified facts."
            if not missing_required
            else "Generate only an outline and ask for the missing facts before experiential prose."
        ),
    }
