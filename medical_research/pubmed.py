"""Small, rate-limited PubMed adapter for exploratory literature searches.

ESearch counts describe the entire query result. ``pmids`` and EFetch metadata
are a bounded sample (at most 50 records), never a systematic review corpus.
All instances share a conservative request gate, including keyed instances.
NCBI usage guidance: https://www.ncbi.nlm.nih.gov/books/NBK25497/
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
import re
import threading
import time
from typing import Any
import xml.etree.ElementTree as ET

import requests


_BASE_URL = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/"
_REQUEST_LOCK = threading.Lock()
_NEXT_REQUEST_AT = 0.0
_REQUEST_INTERVAL = 0.36
_MAX_ATTEMPTS = 3
_MAX_RETRY_DELAY = 5.0
_TIMEOUT = (4, 12)
_MAX_RESPONSE_BYTES = 8 * 1024 * 1024
_PMID_PATTERN = re.compile(r"[1-9][0-9]{0,11}\Z")


class PubMedError(RuntimeError):
    """An actionable, sanitized error suitable for display in the application."""


@dataclass
class SearchResult:
    query: str
    count: int
    pmids: list[str]
    translation: str
    warnings: list[str]
    retrieved_at: str


@dataclass
class Article:
    pmid: str
    title: str
    abstract: str
    journal: str
    year: str
    doi: str
    authors: list[str]
    publication_types: list[str]
    mesh_terms: list[str]
    publication_date: str = ""
    retracted: bool = False


def _text(element: ET.Element | None) -> str:
    return " ".join("".join(element.itertext()).split()) if element is not None else ""


def _date(element: ET.Element | None) -> tuple[str, str]:
    if element is None:
        return "", ""
    year = _text(element.find("Year"))
    medline = _text(element.find("MedlineDate"))
    if not re.fullmatch(r"[0-9]{4}", year):
        match = re.search(r"\b[0-9]{4}\b", medline)
        year = match.group(0) if match else ""
    parts = [year, _text(element.find("Month")), _text(element.find("Day"))]
    return year, medline or " ".join(part for part in parts if part)


def _has_messages(value: Any) -> bool:
    if isinstance(value, dict):
        return any(_has_messages(item) for item in value.values())
    if isinstance(value, list):
        return any(_has_messages(item) for item in value)
    return bool(value)


def _retry_delay(response: requests.Response | None, attempt: int) -> float:
    """Honor Retry-After when possible, but never permit an unbounded wait."""
    retry_after = response.headers.get("Retry-After", "") if response is not None else ""
    try:
        delay = float(retry_after)
    except (TypeError, ValueError):
        try:
            until = parsedate_to_datetime(retry_after)
            if until.tzinfo is None:
                until = until.replace(tzinfo=timezone.utc)
            delay = (until - datetime.now(timezone.utc)).total_seconds()
        except (TypeError, ValueError, OverflowError):
            delay = 0.5 * (2**attempt)
    # NaN and infinities are not useful server instructions.
    if not 0 <= delay <= _MAX_RETRY_DELAY:
        delay = _MAX_RETRY_DELAY if delay > _MAX_RETRY_DELAY else 0.5 * (2**attempt)
    return min(delay, _MAX_RETRY_DELAY)


class PubMedClient:
    def __init__(self, api_key=None, email=None, session=None):
        self._api_key = api_key.strip() if isinstance(api_key, str) else None
        self._email = email.strip() if isinstance(email, str) else None
        self._session = session if session is not None else requests.Session()

    def _request(self, endpoint: str, params: dict[str, Any]) -> requests.Response:
        global _NEXT_REQUEST_AT
        data = {"db": "pubmed", "tool": "medical_ai_topic_explorer", **params}
        if self._api_key:
            data["api_key"] = self._api_key
        if self._email:
            data["email"] = self._email
        for attempt in range(_MAX_ATTEMPTS):
            response = None
            try:
                # Hold the process-wide lock through the request as well as the
                # wait: Streamlit sessions cannot race a non-thread-safe session.
                with _REQUEST_LOCK:
                    delay = _NEXT_REQUEST_AT - time.monotonic()
                    if delay > 0:
                        time.sleep(delay)
                    _NEXT_REQUEST_AT = time.monotonic() + _REQUEST_INTERVAL
                    response = self._session.post(
                        _BASE_URL + endpoint,
                        data=data,
                        timeout=_TIMEOUT,
                        allow_redirects=False,
                    )
            except (requests.Timeout, requests.ConnectionError):
                if attempt + 1 == _MAX_ATTEMPTS:
                    raise PubMedError("PubMed에 연결하지 못했습니다. 잠시 후 다시 시도해 주세요.") from None
            except requests.RequestException:
                raise PubMedError("PubMed 요청을 처리하지 못했습니다. 연결 설정을 확인해 주세요.") from None
            else:
                status = response.status_code
                if status == 200:
                    return response
                if status != 429 and not 500 <= status <= 599:
                    raise PubMedError("PubMed가 요청을 거부했습니다. 검색식과 API 설정을 확인해 주세요.")
                if attempt + 1 == _MAX_ATTEMPTS:
                    raise PubMedError("PubMed 요청이 지연되거나 제한되었습니다. 잠시 후 다시 시도해 주세요.")
            time.sleep(_retry_delay(response, attempt))
        raise PubMedError("PubMed 요청을 완료하지 못했습니다.")  # defensive

    def search(self, query: str, limit: int = 0, sort: str = "pub date") -> SearchResult:
        """Return the matching count and up to ``limit`` sampled PMIDs."""
        if not isinstance(query, str) or not query.strip() or len(query) > 8000:
            raise PubMedError("검색식은 공백이 아닌 1~8,000자여야 합니다.")
        if isinstance(limit, bool) or not isinstance(limit, int) or not 0 <= limit <= 50:
            raise PubMedError("논문 표본 수는 0~50 사이의 정수여야 합니다.")
        sort_values = {
            "pub date": "pub_date", "pub_date": "pub_date", "relevance": "relevance",
            "first author": "Author", "Author": "Author", "journal": "JournalName",
            "JournalName": "JournalName",
        }
        if not isinstance(sort, str) or sort not in sort_values:
            raise PubMedError("지원하지 않는 PubMed 정렬 방식입니다.")
        query = query.strip()
        response = self._request(
            "esearch.fcgi", {"term": query, "retmode": "json", "retmax": limit, "sort": sort_values[sort]}
        )
        try:
            payload = response.json()
        except (ValueError, requests.exceptions.JSONDecodeError):
            raise PubMedError("PubMed 검색 응답을 읽지 못했습니다. 잠시 후 다시 시도해 주세요.") from None
        if not isinstance(payload, dict):
            raise PubMedError("PubMed 검색 응답 형식이 올바르지 않습니다.")
        if _has_messages(payload.get("error")) or _has_messages(payload.get("ERROR")):
            raise PubMedError("PubMed가 검색 오류를 반환했습니다. 검색식과 API 설정을 확인해 주세요.")
        result = payload.get("esearchresult")
        if not isinstance(result, dict):
            raise PubMedError("PubMed 검색 결과가 누락되었습니다.")
        if any(_has_messages(result.get(key)) for key in ("error", "ERROR", "errorlist")):
            raise PubMedError("PubMed가 검색식 오류를 반환했습니다. 검색어와 필드 표기를 확인해 주세요.")
        count_raw, pmids = result.get("count"), result.get("idlist")
        translation = result.get("querytranslation", "")
        if (
            isinstance(count_raw, bool)
            or not isinstance(count_raw, (str, int))
            or not re.fullmatch(r"[0-9]+", str(count_raw))
            or len(str(count_raw)) > 12
            or not isinstance(pmids, list)
            or any(not isinstance(pmid, str) or not _PMID_PATTERN.fullmatch(pmid) for pmid in pmids)
            or len(pmids) != len(set(pmids))
            or not isinstance(translation, str)
        ):
            raise PubMedError("PubMed 검색 결과 형식이 올바르지 않습니다.")
        count = int(count_raw)
        if len(pmids) > limit or len(pmids) > count or (count > 0 and limit > 0 and not pmids):
            raise PubMedError("PubMed 검색 건수와 논문 목록이 일치하지 않습니다.")
        warninglist = result.get("warninglist", {})
        if not isinstance(warninglist, dict):
            raise PubMedError("PubMed 검색 경고 형식이 올바르지 않습니다.")
        warnings = []
        if _has_messages(warninglist):
            warnings.append("PubMed가 검색 경고를 반환했습니다. 원본 검색식과 변환된 검색식을 확인하세요.")
            for messages in warninglist.values():
                if isinstance(messages, str):
                    messages = [messages]
                if not isinstance(messages, list) or any(not isinstance(message, str) for message in messages):
                    raise PubMedError("PubMed 검색 경고 형식이 올바르지 않습니다.")
                for message in messages:
                    # Warnings may echo search terms; never echo credentials or
                    # an upstream URL containing query parameters.
                    for secret in (self._api_key, self._email):
                        if secret:
                            message = message.replace(secret, "[redacted]")
                    message = re.sub(r"https?://\S+", "[URL omitted]", message)
                    warnings.append(" ".join(message.split())[:500])
        return SearchResult(
            query=query,
            count=count,
            pmids=pmids,
            translation=translation,
            warnings=warnings,
            retrieved_at=datetime.now(timezone.utc).isoformat(timespec="seconds"),
        )

    def fetch(self, pmids: list[str]) -> list[Article]:
        """Fetch metadata for a bounded PMID sample, preserving request order."""
        if not isinstance(pmids, (list, tuple)) or len(pmids) > 50:
            raise PubMedError("한 번에 최대 50개의 PMID를 조회할 수 있습니다.")
        if any(not isinstance(pmid, str) or not _PMID_PATTERN.fullmatch(pmid) for pmid in pmids):
            raise PubMedError("PMID는 유효한 양의 정수 문자열이어야 합니다.")
        requested = list(dict.fromkeys(pmids))
        if not requested:
            return []
        response = self._request("efetch.fcgi", {"id": ",".join(requested), "retmode": "xml"})
        content = response.content
        if not content or len(content) > _MAX_RESPONSE_BYTES or b"<!ENTITY" in content.upper():
            raise PubMedError("PubMed 논문 응답이 비어 있거나 올바르지 않습니다.")
        try:
            root = ET.fromstring(content)
        except ET.ParseError:
            raise PubMedError("PubMed 논문 응답을 읽지 못했습니다. 잠시 후 다시 시도해 주세요.") from None
        if root.tag != "PubmedArticleSet" or root.find(".//ERROR") is not None:
            raise PubMedError("PubMed가 유효한 논문 목록을 반환하지 않았습니다.")
        articles = {}
        for record in root:
            if record.tag not in {"PubmedArticle", "PubmedBookArticle"}:
                raise PubMedError("PubMed 논문 목록에 지원하지 않는 레코드가 있습니다.")
            article = self._parse_article(record)
            if article.pmid not in requested or article.pmid in articles:
                raise PubMedError("PubMed가 요청한 PMID와 다른 논문 목록을 반환했습니다.")
            articles[article.pmid] = article
        if set(articles) != set(requested):
            raise PubMedError("일부 논문 정보를 PubMed에서 받지 못했습니다. 검색을 다시 실행해 주세요.")
        return [articles[pmid] for pmid in requested]

    @staticmethod
    def _parse_article(record: ET.Element) -> Article:
        is_book = record.tag == "PubmedBookArticle"
        citation = record.find("BookDocument" if is_book else "MedlineCitation")
        article = citation if is_book else record.find("MedlineCitation/Article")
        if citation is None or article is None:
            raise PubMedError("PubMed 논문 레코드의 필수 정보가 누락되었습니다.")
        pmid = _text(citation.find("PMID"))
        title = _text(article.find("ArticleTitle"))
        if not _PMID_PATTERN.fullmatch(pmid) or not title:
            raise PubMedError("PubMed 논문의 PMID 또는 제목이 누락되었습니다.")
        abstracts = []
        for block in article.findall("Abstract/AbstractText"):
            text = _text(block)
            label = block.get("Label", "") or block.get("NlmCategory", "")
            if text:
                abstracts.append(f"{label}: {text}" if label and label != "UNASSIGNED" else text)
        date = article.find("Book/PubDate" if is_book else "Journal/JournalIssue/PubDate")
        if date is None:
            date = article.find("ArticleDate")
        year, publication_date = _date(date)
        journal = _text(article.find("Book/BookTitle" if is_book else "Journal/Title"))
        if not journal and not is_book:
            journal = _text(article.find("Journal/ISOAbbreviation"))
        authors = []
        for author in article.findall("AuthorList/Author"):
            name = _text(author.find("CollectiveName"))
            if not name:
                given = _text(author.find("ForeName")) or _text(author.find("Initials"))
                name = " ".join(part for part in (given, _text(author.find("LastName")), _text(author.find("Suffix"))) if part)
            if name:
                authors.append(name)
        publication_types = [_text(node) for node in article.findall("PublicationTypeList/PublicationType") if _text(node)]
        mesh_terms = [_text(node) for node in citation.findall("MeshHeadingList/MeshHeading/DescriptorName") if _text(node)]
        doi = ""
        for node in record.findall("PubmedBookData/ArticleIdList/ArticleId" if is_book else "PubmedData/ArticleIdList/ArticleId"):
            if node.get("IdType", "").lower() == "doi":
                doi = _text(node)
                break
        if not doi:
            for node in article.findall("ELocationID"):
                if node.get("EIdType", "").lower() == "doi" and node.get("ValidYN", "Y") != "N":
                    doi = _text(node)
                    break
        retracted = any(kind.lower() in {"retracted publication", "retraction of publication"} for kind in publication_types)
        retracted = retracted or any(
            node.get("RefType") in {"RetractionIn", "RetractionOf"}
            for node in citation.findall("CommentsCorrectionsList/CommentsCorrections")
        )
        return Article(
            pmid=pmid, title=title, abstract="\n\n".join(abstracts), journal=journal,
            year=year, doi=doi, authors=authors, publication_types=publication_types,
            mesh_terms=mesh_terms, publication_date=publication_date, retracted=retracted,
        )
