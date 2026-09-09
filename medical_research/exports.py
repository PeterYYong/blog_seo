"""Standalone, provenance-preserving exports of medical literature exploration."""

from __future__ import annotations

import csv
import io
import json
import re
from typing import Any, Mapping


def to_json(result: Mapping[str, Any]) -> str:
    return json.dumps(result, ensure_ascii=False, indent=2, allow_nan=False)


def _md(value: Any) -> str:
    return str(value if value is not None else "확인 실패").replace("|", "\\|").replace("\n", " ")


def _search_markdown(name: str, search: Mapping[str, Any]) -> list[str]:
    lines = [f"**{name}** — 검색 건수: {_md(search.get('count'))}; 조회: {_md(search.get('retrieved_at'))}", "", f"- 정확한 검색식: `{search.get('query', '').replace('`', '')}`", f"- [PubMed 검색 재현]({search.get('url', '')})", f"- PubMed 변환식: `{str(search.get('translation') or '제공되지 않음').replace('`', '')}`"]
    for warning in search.get("warnings", []):
        lines.append(f"- 검색 경고: {_md(warning)}")
    if search.get("error"):
        lines.append(f"- 오류: {_md(search['error'])}")
    return lines + [""]


def to_markdown(result: Mapping[str, Any]) -> str:
    windows = result["windows"]
    lines = ["# 의료 AI 논문 주제 탐색 기록", "", f"- 검색 기준일: {result['as_of']}", f"- 조회 시각 (UTC): {result['retrieved_at']}", f"- 출처: {result['source']}", f"- 서지정보 출처 표시: `{result['verified_by']}`", f"- 확인 범위: {result['verification_scope']}", f"- 이전 완료 기간: {windows['prior']['start']} ~ {windows['prior']['end']}", f"- 최근 완료 기간: {windows['recent']['start']} ~ {windows['recent']['end']}", f"- {windows['excluded_current_year']}년은 기간 비교에서 제외. 올해 누적 검색과 최신 문헌 표본은 별도 표시.", "", "## 해석 범위", ""]
    if result.get("export_note"):
        lines.extend([f"**내보낸 범위:** {_md(result['export_note'])}", ""])
    lines.extend(f"- {item}" for item in result["limitations"])
    lines.extend(["", "## 입력 설정", "", "```json", json.dumps(result["config"], ensure_ascii=False, indent=2), "```", "", "## 기본 검색", "", f"`{result['base_query'].replace('`', '')}`", ""])
    for name, record in result["base_periods"].items():
        label = {"prior": "이전 완료 기간", "recent": "최근 완료 기간", "current_ytd": "올해 누적 (완료 기간 비교에서 제외)"}.get(name, name)
        lines.extend(_search_markdown(label, record))
    lines.extend(["## 연도별 검색 일치 건수", "", "각 연도는 독립 검색이며 전자·인쇄 출판일 때문에 PMID가 겹칠 수 있습니다. 합계는 고유 논문 수가 아닙니다.", ""])
    for record in result["yearly_counts"]:
        lines.extend(_search_markdown(str(record["year"]), record))
    for lens in result["lenses"]:
        lines.extend([f"## {lens['label']}", "", f"**탐색 가설 (입증된 연구 공백이 아님):** {lens['question']}", "", f"- 이전 / 최근 완료 기간: {_md(lens['prior_count'])} / {_md(lens['recent_count'])}", f"- 건수 변화: {_md(lens['delta'])}", f"- 증가배수: {lens['growth_ratio'] if lens['growth_ratio'] is not None else '표시하지 않음'} — {lens['growth_note']}", ""])
        lines.extend(_search_markdown("이전 완료 기간", lens["prior_search"]))
        lines.extend(_search_markdown("최근 완료 기간", lens["recent_search"]))
        lines.extend(_search_markdown("최신 문헌 표본 검색 (올해 포함)", lens["sample_search"]))
        sw = lens["sample_window"]
        lines.extend([f"표본 범위: {sw['start']} ~ {sw['end']}. 전체 검색 일치 {_md(lens['sample_total_count'])}건 중 메타데이터 {len(lens['papers'])}건, 최대 {lens['sample_limit']}건. {lens['sample_label']}", "", "### 사용자 입력 기반 실행 여건", ""])
        for item in lens["feasibility"]:
            lines.append(f"- {item['label']}: {item['status']} — {item['reason']}")
        lines.extend(["", "### 관련 문헌 표본", ""])
        if not lens["papers"]:
            lines.extend(["표시할 메타데이터가 없습니다. 검색 실패 여부를 확인하세요. 문헌 부재나 참신성의 근거가 아닙니다.", ""])
        for paper in lens["papers"]:
            lines.extend([f"#### [{_md(paper.get('title', ''))}]({paper['url']})", "", f"- PMID: {paper['pmid']}; DOI: {_md(paper.get('doi') or '없음')}", f"- 저널: {_md(paper.get('journal'))}; 연도: {_md(paper.get('year'))}; 출판일: {_md(paper.get('publication_date') or '제공되지 않음')}", f"- 저자: {_md('; '.join(str(author) for author in paper.get('authors', [])))}", f"- 서지정보 출처: `{paper['verified_by']}`; 철회 표시: {'있음 — 사용 전 확인' if paper.get('retracted') else '수신 메타데이터에 없음'}", "", _md(paper.get("abstract") or "초록이 제공되지 않았습니다."), "", f"**표현 감지 주의:** {paper['mention_caution']}", ""])
            for mention in paper.get("mentions", []):
                lines.extend([f"- {mention['label']} / {mention['field']} / 실제 표현: {_md(mention['term'])}", f"  > {_md(mention['snippet'])}"])
            lines.append("")
        if lens["errors"]:
            lines.extend(["### 수집 오류", "", *[f"- {_md(error)}" for error in lens["errors"]], ""])
    return "\n".join(lines).rstrip() + "\n"


def _csv_safe(value: Any) -> str | int | float:
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return value
    text = "" if value is None else str(value)
    # Spreadsheet programs may evaluate formulas even after leading whitespace.
    if text.lstrip().startswith(("=", "+", "-", "@")) or text.startswith(("\t", "\r", "\n")):
        text = "'" + text
    return text


def to_csv(result: Mapping[str, Any]) -> str:
    """One row per actual sampled PMID per lens, with one empty row if absent.

    Period and sample counts stay separate; exact queries, errors, caveats and
    source snippets travel with every row so the file is useful on its own.
    """
    columns = ["lens_id", "lens_label", "research_question_hypothesis", "export_note", "as_of", "retrieved_at", "prior_start", "prior_end", "recent_start", "recent_end", "excluded_current_year", "prior_count", "recent_count", "delta", "growth_ratio", "growth_note", "prior_query", "prior_url", "prior_translation", "recent_query", "recent_url", "recent_translation", "sample_start", "sample_end", "sample_query", "sample_url", "sample_translation", "sample_total_count", "sample_metadata_count", "sample_limit", "sample_label", "pmid", "title", "abstract", "journal", "year", "publication_date", "doi", "authors", "publication_types", "mesh_terms", "retracted", "pubmed_url", "verified_by", "mentions_json", "feasibility_json", "warnings_json", "errors_json", "limitations_json"]
    output = io.StringIO(newline="")
    writer = csv.DictWriter(output, fieldnames=columns)
    writer.writeheader()
    for lens in result["lenses"]:
        for paper in lens["papers"] or [{}]:
            row = {
                "lens_id": lens["id"], "lens_label": lens["label"], "research_question_hypothesis": lens["question"],
                "export_note": result.get("export_note", "선택된 연구 관점의 검색 결과와 문헌 표본"),
                "as_of": result["as_of"], "retrieved_at": result["retrieved_at"],
                "prior_start": result["windows"]["prior"]["start"], "prior_end": result["windows"]["prior"]["end"],
                "recent_start": result["windows"]["recent"]["start"], "recent_end": result["windows"]["recent"]["end"],
                "excluded_current_year": result["windows"]["excluded_current_year"],
                "sample_start": lens["sample_window"]["start"], "sample_end": lens["sample_window"]["end"],
                "sample_metadata_count": len(lens["papers"]),
                "pubmed_url": paper.get("url", ""), "verified_by": paper.get("verified_by", ""),
            }
            for key in ("prior_count", "recent_count", "delta", "growth_ratio", "growth_note", "sample_query", "sample_url", "sample_total_count", "sample_limit", "sample_label"):
                row[key] = lens[key]
            for period in ("prior", "recent", "sample"):
                for key in ("query", "url", "translation"):
                    row[f"{period}_{key}"] = lens[f"{period}_search"].get(key)
            for key in ("pmid", "title", "abstract", "journal", "year", "publication_date", "doi", "retracted"):
                row[key] = paper.get(key, "")
            for key in ("authors", "publication_types", "mesh_terms"):
                row[key] = "; ".join(str(item) for item in paper.get(key, []))
            for key, value in (("mentions", paper.get("mentions", [])), ("feasibility", lens["feasibility"]), ("warnings", lens["warnings"]), ("errors", lens["errors"]), ("limitations", result["limitations"])):
                row[f"{key}_json"] = json.dumps(value, ensure_ascii=False)
            writer.writerow({key: _csv_safe(value) for key, value in row.items()})
    return output.getvalue()


_BIB_ESCAPES = {"\\": r"\textbackslash{}", "{": r"\{", "}": r"\}", "%": r"\%", "&": r"\&", "_": r"\_", "#": r"\#", "$": r"\$", "~": r"\textasciitilde{}", "^": r"\textasciicircum{}"}


def _bib_escape(value: Any) -> str:
    return "".join(_BIB_ESCAPES.get(char, char) for char in re.sub(r"[\r\n\t]+", " ", str(value)))


def to_bibtex(result: Mapping[str, Any]) -> str:
    """Export deduplicated actual metadata; no invented authors or DOI values."""
    provenance = {
        "as_of": result["as_of"], "retrieved_at": result["retrieved_at"],
        "export_note": result.get("export_note", "선택된 연구 관점의 검색 결과와 문헌 표본"),
        "verified_by": result["verified_by"], "verification_scope": result["verification_scope"],
        "windows": result["windows"], "limitations": result["limitations"],
        "searches": [{"lens_id": lens["id"], "prior_search": lens["prior_search"], "recent_search": lens["recent_search"], "sample_search": lens["sample_search"], "sample_limit": lens["sample_limit"], "sample_metadata_count": len(lens["papers"]), "errors": lens["errors"]} for lens in result["lenses"]],
    }
    lines = ["% PubMed sampled metadata only. Keyword mentions are not verified study designs."]
    lines.extend("% " + line for line in json.dumps(provenance, ensure_ascii=False, indent=2).splitlines())
    lines.append("")
    seen = set()
    for lens in result["lenses"]:
        for paper in lens["papers"]:
            if paper["pmid"] in seen:
                continue
            seen.add(paper["pmid"])
            identifier = re.sub(r"[^A-Za-z0-9_-]", "", paper["pmid"])
            fields = {
                "title": paper.get("title"), "journal": paper.get("journal"),
                "year": paper.get("year"), "doi": paper.get("doi"),
                "url": paper["url"], "pmid": paper["pmid"],
                "verified": "true", "verified_by": "pubmed",
                "verified_on": result["retrieved_at"][:10],
                "verification_scope": "PubMed bibliographic metadata only; study design, findings, novelty, and DOI registration not independently verified",
                "note": "verified_by=pubmed metadata; bounded latest-search sample; " + ("retraction marker present" if paper.get("retracted") else "no retraction marker in returned metadata"),
            }
            lines.append(f"@article{{pubmed{identifier},")
            for key, value in fields.items():
                if value is not None and value != "":
                    lines.append(f"  {key} = {{{_bib_escape(value)}}},")
            if paper.get("authors"):
                # Double-braced names preserve the actual PubMed display names.
                authors = " and ".join("{" + _bib_escape(author) + "}" for author in paper["authors"])
                lines.append(f"  author = {{{authors}}},")
            lines.extend(["}", ""])
    return "\n".join(lines)
