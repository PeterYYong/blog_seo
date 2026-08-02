"""Explain which policy or editorial findings a revision resolved."""

from __future__ import annotations

from typing import Any

try:
    from content_audit import audit_draft
except ImportError:  # pragma: no cover - package import path
    from .content_audit import audit_draft


def explain_revision(
    original_title: str,
    original_body: str,
    revised_title: str,
    revised_body: str,
    primary_keyword: str,
    commercial_relationship: str = "none",
    verified_experience_facts: list[str] | None = None,
) -> dict[str, Any]:
    """Compare audits and return a source-linked change rationale log."""

    shared = {
        "primary_keyword": primary_keyword,
        "commercial_relationship": commercial_relationship,
        "verified_experience_facts": verified_experience_facts,
    }
    before = audit_draft(title=original_title, body=original_body, **shared)
    after = audit_draft(title=revised_title, body=revised_body, **shared)
    before_by_code = {item["code"]: item for item in before["checks"]}
    after_by_code = {item["code"]: item for item in after["checks"]}
    resolved_codes = sorted(before_by_code.keys() - after_by_code.keys())
    new_codes = sorted(after_by_code.keys() - before_by_code.keys())
    remaining_codes = sorted(before_by_code.keys() & after_by_code.keys())

    rationale = [
        {
            "change": f"Resolved audit finding: {code}",
            "why": before_by_code[code]["why"],
            "recommended_action": before_by_code[code]["suggested_fix"],
            "evidence_class": before_by_code[code]["evidence_class"],
            "source_url": before_by_code[code].get("source_url"),
        }
        for code in resolved_codes
    ]

    return {
        "before_publish_ready": before["publish_ready"],
        "after_publish_ready": after["publish_ready"],
        "resolved_findings": resolved_codes,
        "remaining_findings": remaining_codes,
        "new_findings": new_codes,
        "change_summary": {
            "title_changed": original_title.strip() != revised_title.strip(),
            "body_changed": original_body.strip() != revised_body.strip(),
            "original_length": len(original_body.strip()),
            "revised_length": len(revised_body.strip()),
        },
        "rationale_log": rationale,
        "remaining_checks": [after_by_code[code] for code in remaining_codes + new_codes],
        "note": (
            "A resolved local audit finding explains the guardrail that changed. "
            "It does not prove a future search-position improvement."
        ),
    }
