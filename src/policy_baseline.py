"""Versioned policy baseline returned by the MCP server."""

from __future__ import annotations

from typing import Any


VERIFIED_ON = "2026-08-02"


def get_policy_baseline() -> dict[str, Any]:
    return {
        "verified_on": VERIFIED_ON,
        "officially_supported_principles": [
            {
                "principle": "Write for user value with real expertise and first-hand experience.",
                "application": "Collect the author's verified facts before writing experiential prose.",
                "source_url": "https://searchadvisor.naver.com/guide/content-basic",
            },
            {
                "principle": "Use concise, accurate titles; unrelated popular terms and repeated words can be harmful.",
                "application": "Keep the title faithful to the body and audit unnatural repetition.",
                "source_url": "https://searchadvisor.naver.com/guide/content-basic",
            },
            {
                "principle": "AI assistance alone is not the issue; low-value mass generation, scraping, and unchanged AI output are risks.",
                "application": "Require human experience, original judgement, citations, and a final policy audit.",
                "source_url": "https://searchadvisor.naver.com/guide/content-abusing",
            },
            {
                "principle": "D.I.A. evaluates document-level intent and experience signals; C-Rank considers source/topic credibility.",
                "application": "Match one clear search intent and maintain topical consistency, without pretending to know secret weights.",
                "source_url": "https://help.naver.com/service/5626/contents/22926?lang=ko",
                "additional_source_url": "https://help.naver.com/service/5626/contents/22927?lang=ko",
            },
            {
                "principle": "AI Briefing and AI search can cite useful source documents, increasing the value of explicit, verifiable answers.",
                "application": "Put concrete answers, dates, prices, conditions, and source links in text rather than images alone.",
                "source_url": "https://help.naver.com/service/5626/contents/24120?lang=ko",
            },
            {
                "principle": "Economic relationships in endorsements must be clearly disclosed near the recommendation.",
                "application": "Place a specific disclosure in the title or opening when sponsorship, provision, affiliate payment, or discount exists.",
                "source_url": "https://www.ftc.go.kr/www/selectBbsNttView.do?bordCd=3&key=12&nttSn=47547",
            },
        ],
        "supplied_guide_reconciliation": [
            {
                "claim": "D.I.A.+ is the official 2026 algorithm name.",
                "status": "not_verified_as_official",
                "decision": "Use the official help-center term D.I.A.; do not present the plus suffix as fact.",
            },
            {
                "claim": "Sensory details and receipt/waiting-ticket photos prove ranking quality.",
                "status": "partially_supported",
                "decision": "Specific first-hand details support authenticity; photos are supporting evidence, not a guaranteed ranking factor.",
            },
            {
                "claim": "SmartBlock types A/B/C are official categories.",
                "status": "editorial_taxonomy_only",
                "decision": "Keep them as planning labels for review/information/situation intent, not Naver's published taxonomy.",
            },
            {
                "claim": "Photo placement raises dwell time and therefore C-Rank.",
                "status": "not_verified_as_official",
                "decision": "Recommend photos for comprehension and evidence only; do not promise a C-Rank effect.",
            },
            {
                "claim": "A fixed keyword density, length, or photo count improves ranking.",
                "status": "unsupported",
                "decision": "Do not encode fixed SEO formulas; audit only obvious repetition, missing facts, and poor readability.",
            },
        ],
        "non_guarantees": [
            "No score produced by this project is Naver's internal score.",
            "No API reveals SmartBlock eligibility or guarantees search position.",
            "Search Ads volume, DataLab ratios, Blog API totals, and YouTube views measure different behaviors.",
            "A recommendation must retain its retrieval timestamp, source errors, and recheck interval.",
        ],
    }
