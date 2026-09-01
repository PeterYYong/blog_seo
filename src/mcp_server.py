"""Naver Blog SEO MCP server with a WebMCP demonstration page."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from mcp.server.fastmcp import FastMCP
from starlette.applications import Starlette
from starlette.responses import FileResponse, JSONResponse
from starlette.routing import Mount, Route

from .seo_service import KeywordInput, MetricsInput, calculate_metrics, configuration_status, envelope, error_envelope, expand


mcp = FastMCP(
    "naver-blog-seo",
    instructions="Analyze Naver Blog keywords. Outputs include timestamps, evidence, and sources.",
    stateless_http=True,
    json_response=True,
    streamable_http_path="/",
)


@mcp.tool()
def expand_keywords(keyword: str) -> dict[str, Any]:
    """Expand one normalized seed into deterministic long-tail keyword candidates."""
    return expand(KeywordInput(keyword=keyword))


@mcp.tool()
def calculate_seo_metrics(keyword: str, monthly_search_volume: int, total_documents: int) -> dict[str, Any]:
    """Calculate saturation and efficiency from user-supplied Naver measurements."""
    return calculate_metrics(MetricsInput(keyword=keyword, monthly_search_volume=monthly_search_volume, total_documents=total_documents))


@mcp.tool()
def analyze_keyword(keyword: str, monthly_search_volume: int, total_documents: int) -> dict[str, Any]:
    """Analyze and classify one keyword using supplied measurements without a paid API call."""
    result = calculate_metrics(MetricsInput(keyword=keyword, monthly_search_volume=monthly_search_volume, total_documents=total_documents))
    result["tool"] = "analyze_keyword"
    return result


@mcp.tool()
def analyze_keyword_batch(items: list[dict[str, Any]]) -> dict[str, Any]:
    """Analyze up to 50 keyword measurement objects and rank valid opportunities by efficiency."""
    if not 1 <= len(items) <= 50:
        return error_envelope("analyze_keyword_batch", "INVALID_BATCH_SIZE", "items must contain 1 to 50 records")
    rows = [calculate_metrics(MetricsInput(**item))["data"] for item in items]
    rows.sort(key=lambda row: row["efficiency_score"], reverse=True)
    return envelope("analyze_keyword_batch", {"results": rows, "count": len(rows)},
                    [{"name": "Project scoring methodology", "url": "METHODOLOGY.md"}],
                    {"ranking": "efficiency_score descending", "live_data": False})


@mcp.tool()
def get_related_keywords(keyword: str) -> dict[str, Any]:
    """Report availability for Naver Ads related-keyword lookup; never fabricates live data."""
    KeywordInput(keyword=keyword)
    status = configuration_status()["data"]
    if not status["naver_ads_ready"]:
        return error_envelope("get_related_keywords", "NAVER_ADS_NOT_CONFIGURED", "Set the documented NAVER Ads environment variables")
    return error_envelope("get_related_keywords", "LIVE_LOOKUP_DISABLED", "Use the existing authenticated deployment for live lookup")


@mcp.tool()
def get_trending_keywords(limit: int = 5) -> dict[str, Any]:
    """Report the safe state of the optional public trend integration."""
    if not 1 <= limit <= 20:
        return error_envelope("get_trending_keywords", "INVALID_LIMIT", "limit must be between 1 and 20")
    return error_envelope("get_trending_keywords", "LIVE_LOOKUP_DISABLED", "Public trend scraping is disabled in the challenge demo")


@mcp.tool()
def get_configuration_status() -> dict[str, Any]:
    """Show whether integrations are configured without returning any secret values."""
    return configuration_status()


@mcp.tool()
def health_check() -> dict[str, Any]:
    """Return a timestamped server readiness result."""
    return envelope("health_check", {"status": "ready", "protocols": ["MCP streamable HTTP", "WebMCP"]}, [], {"live_data": False})


WEB_ROOT = Path(__file__).resolve().parents[1] / "web"


async def homepage(request: Any) -> FileResponse:
    return FileResponse(WEB_ROOT / "index.html")


async def health(request: Any) -> JSONResponse:
    return JSONResponse({"status": "ok"})


mcp_app = mcp.streamable_http_app()
app = Starlette(
    routes=[Route("/", homepage), Route("/healthz", health), Mount("/mcp", app=mcp_app)],
    lifespan=mcp_app.lifespan,
)
