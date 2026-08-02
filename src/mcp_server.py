"""ChatGPT Work-compatible MCP server for evidence-first Naver Blog planning.

Run from the project root:
    python -m src.mcp_server

The streamable HTTP endpoint is exposed at ``/mcp`` (port 8000 by default).
"""

from __future__ import annotations

import os
from datetime import datetime
from typing import Any
from zoneinfo import ZoneInfo

from mcp.server.fastmcp import FastMCP
from mcp.types import ToolAnnotations

from .community_sources import CommunitySignalEngine, SUPPORTED_PLATFORMS
from .content_audit import audit_draft
from .draft_brief import prepare_draft_brief
from .opportunity import OpportunityEngine
from .policy_baseline import get_policy_baseline
from .rationale import explain_revision
from .seo_sources import NaverClient, SourceError, YouTubeClient


READ_EXTERNAL = ToolAnnotations(
    readOnlyHint=True,
    destructiveHint=False,
    openWorldHint=True,
)
READ_LOCAL = ToolAnnotations(
    readOnlyHint=True,
    destructiveHint=False,
    openWorldHint=False,
)


mcp = FastMCP(
    "naver-blog-seo-evidence",
    instructions=(
        "For current-topic requests, inspect source status, call discover_community_topic_signals "
        "to collect current questions and vocabulary, then validate at most five synthesized candidates "
        "with discover_topic_opportunities. Community posts are idea signals, never fact sources. Never "
        "compare raw engagement across platforms or call the opportunity score a ranking probability. Before drafting "
        "experiential content, call prepare_blog_draft_brief and wait for missing user facts. After "
        "drafting, call audit_blog_draft and explain changes by evidence class. Do not invent visits, "
        "prices, tastes, photos, or API results."
    ),
    json_response=True,
    stateless_http=True,
    host=os.getenv("FASTMCP_HOST", "0.0.0.0"),
    port=int(os.getenv("FASTMCP_PORT", "8000")),
)


@mcp.tool(
    title="Check SEO data source status",
    description=(
        "Use this when starting a Naver Blog research workflow to see which official API sources "
        "are configured and which evidence will be missing."
    ),
    annotations=READ_LOCAL,
)
def get_source_status() -> dict[str, Any]:
    naver = NaverClient()
    youtube = YouTubeClient()
    community = CommunitySignalEngine()
    statuses = [*naver.status(), youtube.status(), *community.status()]
    return {"sources": [status.__dict__ for status in statuses]}


@mcp.tool(
    title="Discover current community and social topic signals",
    description=(
        "Use this before Naver/YouTube opportunity scoring when the user wants timely blog ideas, "
        "real questions, objections, comparison language, or cross-community evidence. It can query "
        "Naver Cafe, Knowledge iN, Daum Cafe, Bluesky, Reddit, X, Threads, Hacker News, and Stack "
        "Exchange through documented APIs. Missing approvals or credentials are reported, never "
        "converted to zero. Treat results as topic signals only, synthesize no more than five "
        "candidates, and validate those candidates with discover_topic_opportunities."
    ),
    annotations=READ_EXTERNAL,
)
def discover_community_topic_signals(
    query: str,
    platforms: list[str] | None = None,
    days: int = 7,
    max_results_per_source: int = 12,
    language: str | None = "ko",
    reddit_subreddits: list[str] | None = None,
    hacker_news_feeds: list[str] | None = None,
    stackexchange_site: str = "stackoverflow",
) -> dict[str, Any]:
    """Return privacy-minimised, linked community evidence for topic ideation.

    Supported platform identifiers are exposed in the result and include:
    ``naver_cafe``, ``naver_kin``, ``daum_cafe``, ``bluesky``, ``reddit``,
    ``x``, ``threads``, ``hacker_news``, and ``stackexchange``.
    """

    result = CommunitySignalEngine().discover(
        query=query,
        platforms=platforms,
        days=days,
        max_results_per_source=max_results_per_source,
        language=language,
        reddit_subreddits=reddit_subreddits,
        hacker_news_feeds=hacker_news_feeds,
        stackexchange_site=stackexchange_site,
    )
    result["supported_platforms"] = list(SUPPORTED_PLATFORMS)
    return result


@mcp.tool(
    title="Get Korean YouTube popular-video snapshot",
    description=(
        "Use this when the user asks what is popular now and no candidate keywords exist yet. "
        "It returns YouTube's official KR mostPopular chart as candidate evidence, not Naver demand. "
        "Extract only themes relevant to the user's blog, then validate them with discover_topic_opportunities."
    ),
    annotations=READ_EXTERNAL,
)
def youtube_trending_snapshot(
    max_results: int = 25,
    region_code: str = "KR",
    video_category_id: str | None = None,
) -> dict[str, Any]:
    youtube = YouTubeClient()
    try:
        videos = youtube.trending_snapshot(
            max_results=max_results,
            region_code=region_code,
            video_category_id=video_category_id,
        )
    except SourceError as exc:
        return {
            "retrieved_at": datetime.now(ZoneInfo("Asia/Seoul")).isoformat(),
            "source_error": {"source": exc.source, "message": str(exc), "status_code": exc.status_code},
            "videos": [],
        }
    return {
        "retrieved_at": datetime.now(ZoneInfo("Asia/Seoul")).isoformat(),
        "region_code": region_code,
        "chart": "YouTube videos.list chart=mostPopular",
        "videos": videos,
        "limit": "YouTube popularity is a cross-platform signal and must be validated against Naver intent.",
        "source_url": "https://developers.google.com/youtube/v3/docs/videos/list",
    }


@mcp.tool(
    title="Discover evidence-backed blog topic opportunities",
    description=(
        "Use this when the user wants blog topics likely to be timely now. It combines Naver Search Ads "
        "demand, DataLab momentum, Blog API supply proxies, and recent YouTube view velocity. Provide a "
        "seed and optionally model-generated candidate keywords. The score is relative within the run."
    ),
    annotations=READ_EXTERNAL,
)
def discover_topic_opportunities(
    seed: str,
    candidate_keywords: list[str] | None = None,
    max_candidates: int = 8,
    trend_days: int = 56,
    youtube_days: int = 30,
    region_code: str = "KR",
) -> dict[str, Any]:
    return OpportunityEngine().discover(
        seed=seed,
        candidate_keywords=candidate_keywords,
        max_candidates=max_candidates,
        trend_days=trend_days,
        youtube_days=youtube_days,
        region_code=region_code,
    )


@mcp.tool(
    title="Prepare a fact-gated Naver Blog draft brief",
    description=(
        "Use this after selecting a topic and before writing the draft. It identifies missing first-hand "
        "facts, builds an outline, applies the supplied F&B tone/template when requested, and blocks "
        "invented experience."
    ),
    annotations=READ_LOCAL,
)
def prepare_blog_draft_brief(
    primary_keyword: str,
    topic: str,
    content_type: str = "fnb_review",
    audience: str = "네이버 검색 사용자",
    search_intent: str = "experience_and_information",
    facts: dict[str, Any] | None = None,
    commercial_relationship: str = "none",
) -> dict[str, Any]:
    return prepare_draft_brief(
        primary_keyword=primary_keyword,
        topic=topic,
        content_type=content_type,
        audience=audience,
        search_intent=search_intent,
        facts=facts,
        commercial_relationship=commercial_relationship,
    )


@mcp.tool(
    title="Audit a Naver Blog draft and explain every change",
    description=(
        "Use this after drafting or revising a post. It separates official Naver/FTC policy findings "
        "from supplied tone preferences and editorial advice, and returns a reason and fix for each item."
    ),
    annotations=READ_LOCAL,
)
def audit_blog_draft(
    title: str,
    body: str,
    primary_keyword: str,
    commercial_relationship: str = "none",
    verified_experience_facts: list[str] | None = None,
    ai_virtual_person: bool = False,
    ai_generated_testimonial: bool = False,
) -> dict[str, Any]:
    return audit_draft(
        title=title,
        body=body,
        primary_keyword=primary_keyword,
        commercial_relationship=commercial_relationship,
        verified_experience_facts=verified_experience_facts,
        ai_virtual_person=ai_virtual_person,
        ai_generated_testimonial=ai_generated_testimonial,
    )


@mcp.tool(
    title="Explain why a blog draft was revised",
    description=(
        "Use this after revising a draft when the user asks why changes were made. It compares the "
        "before/after policy audits and returns resolved, remaining, and newly introduced findings "
        "with evidence classes and source links. It does not claim that a change guarantees ranking."
    ),
    annotations=READ_LOCAL,
)
def explain_blog_revision(
    original_title: str,
    original_body: str,
    revised_title: str,
    revised_body: str,
    primary_keyword: str,
    commercial_relationship: str = "none",
    verified_experience_facts: list[str] | None = None,
) -> dict[str, Any]:
    return explain_revision(
        original_title=original_title,
        original_body=original_body,
        revised_title=revised_title,
        revised_body=revised_body,
        primary_keyword=primary_keyword,
        commercial_relationship=commercial_relationship,
        verified_experience_facts=verified_experience_facts,
    )


@mcp.tool(
    title="Read the verified Naver SEO policy baseline",
    description=(
        "Use this when drafting, auditing, or explaining SEO decisions. It returns dated official-policy "
        "principles, reconciles the supplied 2026 guide, and lists claims that must not be presented as facts."
    ),
    annotations=READ_LOCAL,
)
def get_naver_policy_baseline() -> dict[str, Any]:
    return get_policy_baseline()


if __name__ == "__main__":
    mcp.run(transport="streamable-http")
