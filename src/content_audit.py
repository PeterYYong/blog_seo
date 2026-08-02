"""Policy-aware audit for Naver Blog drafts.

Official policy checks and editorial preferences are intentionally separated.
The audit never claims that a word count, keyword density, photo count, or
template guarantees exposure.
"""

from __future__ import annotations

import re
from collections import Counter
from typing import Any


NAVER_CONTENT_GUIDE = "https://searchadvisor.naver.com/guide/content-basic"
NAVER_SPAM_GUIDE = "https://searchadvisor.naver.com/guide/content-abusing"
NAVER_BLOG_LIMITS = "https://help.naver.com/service/5626/contents/22928?lang=ko"
FTC_DISCLOSURE_GUIDE = (
    "https://www.ftc.go.kr/www/selectBbsNttView.do?bordCd=3&key=12&nttSn=47547"
)

COMMERCIAL_RELATIONSHIPS = {
    "sponsored",
    "product_provided",
    "service_provided",
    "affiliate",
    "employee_or_owner",
    "discounted",
}

DISCLOSURE_MARKERS = (
    "광고",
    "협찬",
    "원고료",
    "제품을 제공",
    "서비스를 제공",
    "무료로 제공",
    "할인 혜택",
    "경제적 대가",
    "파트너스 활동",
    "제휴 링크",
)

TONE_GUIDE_PHRASES = (
    "결론적으로",
    "요약하자면",
    "살펴보겠습니다",
    "알아보았습니다",
    "좋은 선택일 것입니다",
)


def _check(
    severity: str,
    code: str,
    message: str,
    why: str,
    fix: str,
    evidence_class: str,
    source_url: str | None = None,
) -> dict[str, Any]:
    return {
        "severity": severity,
        "code": code,
        "message": message,
        "why": why,
        "suggested_fix": fix,
        "evidence_class": evidence_class,
        "source_url": source_url,
    }


def audit_draft(
    title: str,
    body: str,
    primary_keyword: str,
    commercial_relationship: str = "none",
    verified_experience_facts: list[str] | None = None,
    ai_virtual_person: bool = False,
    ai_generated_testimonial: bool = False,
) -> dict[str, Any]:
    """Audit a draft and explain each requested change.

    ``commercial_relationship`` supports ``none``, ``self_paid``, and the
    values in ``COMMERCIAL_RELATIONSHIPS``.
    """

    title = title.strip()
    body = body.strip()
    keyword = " ".join(primary_keyword.split())
    relationship = commercial_relationship.strip().lower()
    verified_experience_facts = [
        fact.strip() for fact in (verified_experience_facts or []) if fact.strip()
    ]
    checks: list[dict[str, Any]] = []
    combined = f"{title}\n{body}"
    first_part = body[:400]

    if not title:
        checks.append(
            _check(
                "error",
                "missing_title",
                "제목이 없습니다.",
                "검색 사용자와 검색 시스템 모두 글의 핵심 주제를 제목에서 파악합니다.",
                "실제 본문을 정확히 요약하는 고유한 제목을 작성하세요.",
                "official_policy",
                NAVER_CONTENT_GUIDE,
            )
        )
    if keyword and keyword.lower() not in title.lower():
        checks.append(
            _check(
                "info",
                "topic_not_explicit_in_title",
                "주요 주제가 제목에 명확히 드러나지 않습니다.",
                "네이버는 간결하고 정확한 제목을 권장하지만 특정 문구의 강제 삽입이나 반복을 요구하지 않습니다.",
                "문장이 자연스러울 때만 주요 주제 또는 동의어를 한 번 포함하세요.",
                "official_policy",
                NAVER_CONTENT_GUIDE,
            )
        )

    if keyword:
        exact_count = combined.lower().count(keyword.lower())
        word_count = max(1, len(re.findall(r"\S+", combined)))
        allowed = max(4, word_count // 120 + 2)
        if exact_count > allowed:
            checks.append(
                _check(
                    "warning",
                    "possible_keyword_stuffing",
                    f"동일 핵심 문구가 {exact_count}회 반복됩니다.",
                    "네이버는 제목·본문의 의도적인 동일 키워드 반복과 남용을 스팸 사례로 안내합니다. 이 기준은 공식 밀도 공식이 아닌 보수적 문장 검수입니다.",
                    "반복 문구를 대명사·동의어·구체 정보로 바꾸고, 각 문단이 독자 질문에 답하는지 확인하세요.",
                    "official_policy_plus_editorial_threshold",
                    NAVER_SPAM_GUIDE,
                )
            )

    duplicate_title_tokens = [
        token
        for token, count in Counter(re.findall(r"[가-힣A-Za-z0-9]+", title.lower())).items()
        if count >= 3 and len(token) >= 2
    ]
    if duplicate_title_tokens:
        checks.append(
            _check(
                "warning",
                "repetitive_title",
                f"제목에서 같은 단어가 과도하게 반복됩니다: {', '.join(duplicate_title_tokens)}",
                "관련 없는 인기어 삽입과 같은 단어 반복은 품질 평가에 불리하거나 어뷰징 의심을 받을 수 있습니다.",
                "핵심 주제, 구체적 효용, 실제 맥락만 남겨 제목을 줄이세요.",
                "official_policy",
                NAVER_CONTENT_GUIDE,
            )
        )

    if len(title) > 60:
        checks.append(
            _check(
                "info",
                "long_title",
                f"제목이 {len(title)}자로 길어 모바일에서 핵심이 늦게 보일 수 있습니다.",
                "이는 네이버 공식 순위 기준이 아니라 모바일 가독성을 위한 편집 판단입니다.",
                "중복 수식어를 줄이고 핵심 장소·대상·효용을 앞부분에 두세요.",
                "editorial_preference",
            )
        )

    paragraphs = [paragraph.strip() for paragraph in re.split(r"\n\s*\n", body) if paragraph.strip()]
    long_paragraphs = [index + 1 for index, paragraph in enumerate(paragraphs) if len(paragraph) > 220]
    if long_paragraphs:
        checks.append(
            _check(
                "info",
                "mobile_readability",
                f"모바일에서 길게 보일 수 있는 문단: {long_paragraphs}",
                "짧은 문단 선호는 첨부 톤앤매너 가이드에 따른 편집 규칙이며 검색 순위 공식은 아닙니다.",
                "한 문단에 한 가지 정보만 남기고 자연스럽게 나누세요.",
                "user_style_guide",
            )
        )

    used_tone_phrases = [phrase for phrase in TONE_GUIDE_PHRASES if phrase in body]
    if used_tone_phrases:
        checks.append(
            _check(
                "info",
                "tone_guide_mismatch",
                f"첨부 톤 가이드의 금지 표현이 포함되었습니다: {', '.join(used_tone_phrases)}",
                "이는 사용자가 제공한 F&B 문체 규칙이며 네이버 알고리즘 정책이 아닙니다.",
                "상투적 요약 문구를 실제 경험을 말하는 자연스러운 해요체로 바꾸세요.",
                "user_style_guide",
            )
        )

    needs_disclosure = relationship in COMMERCIAL_RELATIONSHIPS
    disclosure_present = any(marker in first_part for marker in DISCLOSURE_MARKERS)
    claims_self_paid = "내돈내산" in combined.replace(" ", "")
    if needs_disclosure and not disclosure_present:
        checks.append(
            _check(
                "error",
                "missing_economic_relationship_disclosure",
                "경제적 이해관계가 있지만 글 첫 부분에서 명확한 표시를 찾지 못했습니다.",
                "공정위 지침은 소비자가 쉽게 인식하도록 제목 또는 게시물 첫 부분 등 가까운 위치에 경제적 이해관계를 명확히 표시하도록 요구합니다.",
                "실제 관계를 구체적으로 밝히는 문구를 제목 또는 본문 첫 부분에 눈에 띄게 배치하세요.",
                "legal_policy",
                FTC_DISCLOSURE_GUIDE,
            )
        )
    if needs_disclosure and claims_self_paid:
        checks.append(
            _check(
                "error",
                "misleading_self_paid_claim",
                "경제적 관계가 있는데 '내돈내산' 표현이 포함되어 서로 모순됩니다.",
                "대가 관계를 숨기거나 오인시키는 표현은 소비자 기만 위험이 있습니다.",
                "'내돈내산'을 삭제하고 실제 제공·협찬·제휴 관계를 구체적으로 표시하세요.",
                "legal_policy",
                FTC_DISCLOSURE_GUIDE,
            )
        )

    if relationship not in {"none", "self_paid", *COMMERCIAL_RELATIONSHIPS}:
        checks.append(
            _check(
                "warning",
                "unknown_commercial_relationship",
                f"인식할 수 없는 경제적 관계 값입니다: {commercial_relationship}",
                "관계를 잘못 분류하면 필수 표시 검사가 누락될 수 있습니다.",
                "none, self_paid, sponsored, product_provided, service_provided, affiliate, employee_or_owner, discounted 중 하나로 지정하세요.",
                "workflow_rule",
            )
        )

    placeholders = sorted(set(re.findall(r"\{\{[^}]+\}\}|\[(?:확인|입력|자료|사실)[^\]]*\]", body)))
    if placeholders:
        checks.append(
            _check(
                "warning",
                "unresolved_placeholders",
                f"게시 전 확인해야 할 자리표시자가 남아 있습니다: {', '.join(placeholders[:8])}",
                "주소·가격·운영시간 같은 미확인 정보를 추측해 채우면 사용자 혼동과 신뢰 저하를 일으킬 수 있습니다.",
                "직접 확인하거나 공식 출처로 검증한 뒤 채우고, 확인할 수 없으면 삭제하세요.",
                "official_policy",
                NAVER_SPAM_GUIDE,
            )
        )

    experience_words = re.search(r"(먹어보|방문했|다녀왔|바삭|고소|향이|식감|웨이팅|주차했)", body)
    if experience_words and not verified_experience_facts:
        checks.append(
            _check(
                "warning",
                "experience_claims_need_user_confirmation",
                "직접 경험을 나타내는 문장이 있지만 검증된 경험 사실 목록이 비어 있습니다.",
                "네이버는 실제 경험과 고유한 관점을 권장하며, AI가 감각·방문 사실을 만들어내면 허위 콘텐츠가 됩니다.",
                "방문일, 주문 메뉴, 가격, 대기시간, 주차, 장단점처럼 사용자가 확인한 사실을 먼저 입력하세요.",
                "official_policy_and_hallucination_guardrail",
                NAVER_CONTENT_GUIDE,
            )
        )

    if ai_virtual_person or ai_generated_testimonial:
        checks.append(
            _check(
                "error",
                "ai_generated_endorsement_disclosure_required",
                "AI 가상 인물 또는 AI 생성 체험·추천 표현이 사용되었습니다.",
                "2026년 6월 시행 공정위 개정 지침은 실제와 구분하기 어려운 AI 가상 추천인과 AI 생성 체험 표현의 오인 방지를 강화했습니다.",
                "가상·AI 생성 사실을 명확히 표시하고 실제 체험처럼 보이는 허위 before/after 또는 후기를 사용하지 마세요.",
                "legal_policy",
                FTC_DISCLOSURE_GUIDE,
            )
        )

    if not body:
        checks.append(
            _check(
                "error",
                "missing_body",
                "본문이 없습니다.",
                "제목만으로는 검색 사용자에게 실질적 가치를 제공할 수 없습니다.",
                "직접 경험·검증 정보·독자 질문에 대한 답을 포함해 본문을 작성하세요.",
                "official_policy",
                NAVER_CONTENT_GUIDE,
            )
        )

    severity_counts = Counter(check["severity"] for check in checks)
    publish_ready = severity_counts["error"] == 0 and severity_counts["warning"] == 0
    return {
        "publish_ready": publish_ready,
        "summary": {
            "errors": severity_counts["error"],
            "warnings": severity_counts["warning"],
            "info": severity_counts["info"],
        },
        "checks": checks,
        "verified_experience_facts": verified_experience_facts,
        "explanation_contract": [
            "official_policy: an official Naver or government source supports the principle",
            "official_policy_plus_editorial_threshold: official risk, locally chosen conservative trigger",
            "user_style_guide: supplied writing preference, not a ranking rule",
            "editorial_preference: readability suggestion, not an algorithm claim",
        ],
        "policy_sources": [
            NAVER_CONTENT_GUIDE,
            NAVER_SPAM_GUIDE,
            NAVER_BLOG_LIMITS,
            FTC_DISCLOSURE_GUIDE,
        ],
    }
