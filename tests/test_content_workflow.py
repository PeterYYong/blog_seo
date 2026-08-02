from src.content_audit import audit_draft
from src.draft_brief import FNB_REQUIRED, prepare_draft_brief
from src.rationale import explain_revision


def _check_codes(result):
    return {check["code"] for check in result["checks"]}


def test_sponsored_post_requires_opening_disclosure():
    result = audit_draft(
        title="성수 파스타 방문 후기",
        body="직접 방문했고 파스타를 먹어보니 고소했어요.",
        primary_keyword="성수 파스타",
        commercial_relationship="service_provided",
        verified_experience_facts=["2026-07-20 방문", "파스타 제공"],
    )

    assert "missing_economic_relationship_disclosure" in _check_codes(result)
    assert result["publish_ready"] is False


def test_specific_opening_disclosure_satisfies_disclosure_check():
    result = audit_draft(
        title="성수 파스타 방문 후기",
        body="이 글은 식사 서비스를 제공받아 작성했습니다.\n\n직접 방문해 메뉴를 확인했어요.",
        primary_keyword="성수 파스타",
        commercial_relationship="service_provided",
        verified_experience_facts=["2026-07-20 방문", "서비스 제공"],
    )

    assert "missing_economic_relationship_disclosure" not in _check_codes(result)


def test_self_paid_claim_cannot_hide_a_commercial_relationship():
    result = audit_draft(
        title="내돈내산 성수 파스타",
        body="협찬으로 방문했어요.",
        primary_keyword="성수 파스타",
        commercial_relationship="sponsored",
        verified_experience_facts=["협찬 방문"],
    )

    assert "misleading_self_paid_claim" in _check_codes(result)


def test_fnb_draft_waits_for_first_hand_facts():
    result = prepare_draft_brief("성수 맛집", "성수 저녁 맛집", facts={})

    assert result["ready_for_full_draft"] is False
    assert set(result["missing_required_facts"]) == set(FNB_REQUIRED)


def test_fnb_draft_is_ready_with_all_required_facts():
    facts = {field: f"verified {field}" for field in FNB_REQUIRED}

    result = prepare_draft_brief("성수 맛집", "성수 저녁 맛집", facts=facts)

    assert result["ready_for_full_draft"] is True
    assert not result["missing_required_facts"]


def test_revision_agent_explains_resolved_disclosure_finding():
    result = explain_revision(
        original_title="성수 파스타 후기",
        original_body="직접 방문했어요.",
        revised_title="성수 파스타 후기",
        revised_body="식사 서비스를 제공받아 작성했습니다.\n\n직접 방문했어요.",
        primary_keyword="성수 파스타",
        commercial_relationship="service_provided",
        verified_experience_facts=["직접 방문", "식사 제공"],
    )

    assert "missing_economic_relationship_disclosure" in result["resolved_findings"]
    entry = result["rationale_log"][0]
    assert entry["evidence_class"] == "legal_policy"
    assert entry["source_url"]
