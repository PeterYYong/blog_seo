"""Deterministic selection helpers for Search Ads keyword candidates.

Search Ads returns related-keyword rows ordered by monthly search estimate.
Taking a simple prefix from those rows over-represents only the highest-volume
queries.  This module keeps that source order, splits the valid unique rows
into three ordinal volume tiers, and samples the tiers in round-robin order.

The helpers here do not score keywords or make exposure/ranking claims.
"""

from __future__ import annotations

import math
import unicodedata
from collections.abc import Iterable, Mapping
from numbers import Real
from typing import Any


VOLUME_TIERS = ("high", "mid", "long_tail")


def canonical_keyword_key(value: str) -> str:
    """Return the shared key for formatting-insensitive exact matching."""

    if not isinstance(value, str):
        raise TypeError("value must be a string")
    return "".join(unicodedata.normalize("NFKC", value).split()).casefold()


def _is_valid_volume(value: object) -> bool:
    """Return whether *value* can be treated as a Search Ads estimate."""

    return (
        isinstance(value, Real)
        and not isinstance(value, bool)
        and math.isfinite(float(value))
        and value >= 0
    )


def _valid_unique_rows(
    rows: Iterable[Mapping[str, Any]],
) -> list[tuple[str, dict[str, Any]]]:
    """Copy valid canonical rows and remove formatting-equivalent duplicates."""

    if isinstance(rows, (str, bytes)):
        raise TypeError("rows must be an iterable of mappings")

    try:
        iterator = iter(rows)
    except TypeError as exc:
        raise TypeError("rows must be an iterable of mappings") from exc

    output: list[tuple[str, dict[str, Any]]] = []
    seen: set[str] = set()
    for row in iterator:
        if not isinstance(row, Mapping):
            continue

        keyword = row.get("keyword")
        volume = row.get("monthly_search_estimate")
        if not isinstance(keyword, str) or not keyword.strip():
            continue
        if not _is_valid_volume(volume):
            continue

        normalised = canonical_keyword_key(keyword)
        if normalised in seen:
            continue
        seen.add(normalised)
        output.append((normalised, dict(row)))

    return output


def _tier_sizes(row_count: int) -> tuple[int, int, int]:
    """Split ordered rows into three contiguous, near-equal tiers.

    Any remainder is assigned from the high-volume tier down.  This makes the
    boundaries deterministic while retaining every row.  With fewer than
    three rows, naturally one or more tiers are empty.
    """

    base, remainder = divmod(row_count, len(VOLUME_TIERS))
    return (
        base + (1 if remainder >= 1 else 0),
        base + (1 if remainder >= 2 else 0),
        base,
    )


def select_related_keyword_candidates(
    rows: Iterable[Mapping[str, Any]],
    limit: int,
    *,
    seed_keyword: str | None = None,
) -> list[dict[str, Any]]:
    """Select a volume-stratified subset of ordered Search Ads rows.

    Parameters
    ----------
    rows:
        Canonical Search Ads rows, already ordered from highest to lowest
        ``monthly_search_estimate``.  Invalid rows and formatting-equivalent
        duplicate keywords are skipped.  Every field on a selected row is
        copied, so parent/source provenance and censoring metadata survive.
    limit:
        Maximum number of rows to return.  Zero returns an empty list.
    seed_keyword:
        When supplied, an exact formatting-normalised match from ``rows`` is
        placed first and removed from the later round-robin pass.  No row is
        fabricated when Search Ads did not return a valid exact match.

    Returns
    -------
    list[dict[str, Any]]
        Fresh row dictionaries annotated with ``volume_tier`` (``high``,
        ``mid``, or ``long_tail``).  The input rows are never mutated.
    """

    if isinstance(limit, bool) or not isinstance(limit, int):
        raise TypeError("limit must be an integer")
    if limit < 0:
        raise ValueError("limit must be non-negative")
    if seed_keyword is not None and not isinstance(seed_keyword, str):
        raise TypeError("seed_keyword must be a string or None")
    if seed_keyword is not None and not seed_keyword.strip():
        raise ValueError("seed_keyword must not be empty")
    if limit == 0:
        return []

    valid_rows = _valid_unique_rows(rows)
    tier_sizes = _tier_sizes(len(valid_rows))
    tiered_rows: list[list[tuple[str, dict[str, Any]]]] = []
    offset = 0
    for tier_name, size in zip(VOLUME_TIERS, tier_sizes):
        tier: list[tuple[str, dict[str, Any]]] = []
        for normalised, source_row in valid_rows[offset : offset + size]:
            selected_row = dict(source_row)
            selected_row["volume_tier"] = tier_name
            tier.append((normalised, selected_row))
        tiered_rows.append(tier)
        offset += size

    selected: list[dict[str, Any]] = []
    selected_keys: set[str] = set()

    if seed_keyword is not None:
        seed_key = canonical_keyword_key(seed_keyword)
        for tier in tiered_rows:
            for normalised, row in tier:
                if normalised == seed_key:
                    selected.append(row)
                    selected_keys.add(normalised)
                    break
            if selected:
                break

    tier_positions = [0] * len(tiered_rows)
    while len(selected) < limit:
        added_this_round = False
        for tier_index, tier in enumerate(tiered_rows):
            while tier_positions[tier_index] < len(tier):
                normalised, row = tier[tier_positions[tier_index]]
                tier_positions[tier_index] += 1
                if normalised in selected_keys:
                    continue
                selected.append(row)
                selected_keys.add(normalised)
                added_this_round = True
                break
            if len(selected) >= limit:
                break
        if not added_this_round:
            break

    return selected


def build_reader_topic_angle(keyword: str) -> dict[str, str]:
    """Build a conservative Korean reader question and editorial angle.

    The wording deliberately promises only a structured explanation.  It does
    not imply popularity, ranking potential, first-hand experience, or facts
    that have not yet been checked.
    """

    if not isinstance(keyword, str):
        raise TypeError("keyword must be a string")
    cleaned = " ".join(keyword.split())
    if not cleaned:
        raise ValueError("keyword must not be empty")

    return {
        "reader_question": (
            f"{cleaned}에 대해 알아볼 때 먼저 확인해야 할 정보는 무엇일까?"
        ),
        "topic_angle": (
            f"{cleaned}에 관심 있는 독자가 배경, 확인할 정보, 주의점을 "
            "차례로 이해할 수 있도록 정리한다."
        ),
    }
