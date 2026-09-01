"""Validated, transport-independent SEO operations used by MCP and WebMCP."""

from __future__ import annotations

import os
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

from .calculator import calculate_efficiency, calculate_saturation
from .keyword_expander import expand_keyword


NAVER_AD_SOURCE = "https://naver.github.io/searchad-apidoc/#/guides"
NAVER_BLOG_SOURCE = "https://developers.naver.com/docs/serviceapi/search/blog/blog.md"
SIGNAL_SOURCE = "https://signal.bz/"
METHODOLOGY_SOURCE = "METHODOLOGY.md"


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


@dataclass(frozen=True)
class KeywordInput:
    keyword: str

    def __post_init__(self) -> None:
        if not isinstance(self.keyword, str):
            raise TypeError("keyword must be a string")
        value = " ".join(self.keyword.split())
        if not 1 <= len(value) <= 100:
            raise ValueError("keyword must contain 1 to 100 characters")
        object.__setattr__(self, "keyword", value)


@dataclass(frozen=True)
class MetricsInput:
    keyword: str
    monthly_search_volume: int
    total_documents: int

    def __post_init__(self) -> None:
        object.__setattr__(self, "keyword", KeywordInput(self.keyword).keyword)
        for name in ("monthly_search_volume", "total_documents"):
            value = getattr(self, name)
            if isinstance(value, bool) or not isinstance(value, int):
                raise TypeError(f"{name} must be an integer")
            if not 0 <= value <= 2_147_483_647:
                raise ValueError(f"{name} must be between 0 and 2147483647")


def envelope(tool: str, data: Any, sources: list[dict[str, str]], evidence: dict[str, Any]) -> dict[str, Any]:
    return {
        "ok": True,
        "tool": tool,
        "retrieved_at": utc_now(),
        "data": data,
        "evidence": evidence,
        "sources": sources,
    }


def error_envelope(tool: str, code: str, message: str, *, retryable: bool = False) -> dict[str, Any]:
    return {
        "ok": False,
        "tool": tool,
        "retrieved_at": utc_now(),
        "error": {"code": code, "message": message, "retryable": retryable},
        "data": None,
        "evidence": {},
        "sources": [],
    }


def calculate_metrics(payload: MetricsInput) -> dict[str, Any]:
    saturation = calculate_saturation(payload.total_documents, payload.monthly_search_volume)
    efficiency = calculate_efficiency(saturation, payload.monthly_search_volume)
    classification = "insufficient-volume" if payload.monthly_search_volume < 50 else (
        "blue-ocean" if saturation < 1 else "competitive" if saturation < 5 else "red-ocean"
    )
    return envelope(
        "calculate_seo_metrics",
        {
            "keyword": payload.keyword,
            "monthly_search_volume": payload.monthly_search_volume,
            "total_documents": payload.total_documents,
            "saturation_index": round(saturation, 6),
            "efficiency_score": round(efficiency, 6),
            "classification": classification,
            "recommended": classification == "blue-ocean",
        },
        [{"name": "Project scoring methodology", "url": METHODOLOGY_SOURCE}],
        {"formula": "Sk=documents/volume; Ek=(0.05/(Sk+1))*log10(volume)", "live_data": False},
    )


def expand(payload: KeywordInput) -> dict[str, Any]:
    keywords, topics = expand_keyword(payload.keyword)
    ordered = sorted(set(keywords), key=lambda item: (item != payload.keyword, item))
    return envelope(
        "expand_keywords",
        {"seed": payload.keyword, "keywords": ordered, "sub_topics": topics, "count": len(ordered)},
        [{"name": "Project expansion rules", "url": "src/keyword_expander.py"}],
        {"method": "deterministic suffix expansion", "live_data": False},
    )


def configuration_status() -> dict[str, Any]:
    names = [
        "NAVER_AD_API_KEY", "NAVER_AD_SECRET_KEY", "NAVER_CUSTOMER_ID",
        "NAVER_CLIENT_ID", "NAVER_CLIENT_SECRET",
    ]
    configured = {name: bool(os.getenv(name)) for name in names}
    return envelope(
        "configuration_status",
        {"naver_ads_ready": all(configured[name] for name in names[:3]),
         "naver_search_ready": all(configured[name] for name in names[3:]),
         "variables": configured,
         "unsupported_integrations": {"x": "not configured", "reddit": "not configured", "threads": "not configured"}},
        [],
        {"secret_values_exposed": False},
    )
