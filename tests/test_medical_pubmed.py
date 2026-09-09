"""Network-free contract and failure tests for the PubMed adapter."""

from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
import threading
import time as real_time

import pytest
import requests

from medical_research import pubmed
from medical_research.pubmed import PubMedClient, PubMedError


class Response:
    def __init__(self, payload=None, xml=None, status=200, headers=None):
        self.payload = payload
        self.content = xml.encode() if isinstance(xml, str) else xml
        self.status_code = status
        self.headers = headers or {}

    def json(self):
        if isinstance(self.payload, Exception):
            raise self.payload
        return self.payload


class Session:
    def __init__(self, *responses):
        self.responses = list(responses)
        self.calls = []

    def post(self, url, **kwargs):
        self.calls.append((url, kwargs))
        response = self.responses.pop(0)
        if isinstance(response, Exception):
            raise response
        return response


class Clock:
    def __init__(self):
        self.now = 100.0
        self.sleeps = []

    def monotonic(self):
        return self.now

    def sleep(self, delay):
        self.sleeps.append(delay)
        self.now += delay


@pytest.fixture(autouse=True)
def request_clock(monkeypatch):
    clock = Clock()
    # Replacing the module attribute avoids patching global stdlib time used by
    # ThreadPoolExecutor/pytest themselves.
    monkeypatch.setattr(pubmed, "time", clock)
    monkeypatch.setattr(pubmed, "_NEXT_REQUEST_AT", 0.0)
    return clock


def search_payload(count="127", pmids=None, **extra):
    return {"esearchresult": {"count": count, "idlist": pmids or [], "querytranslation": "cancer[All Fields]", **extra}}


def record(pmid="123", extra="", article_extra="", title="A study"):
    return f"""<PubmedArticle><MedlineCitation><PMID>{pmid}</PMID>
      <Article><ArticleTitle>{title}</ArticleTitle>{article_extra}</Article>
      {extra}</MedlineCitation></PubmedArticle>"""


def xml_response(*records):
    return Response(xml="<PubmedArticleSet>" + "".join(records) + "</PubmedArticleSet>")


def test_count_is_independent_of_sample_and_uses_post_with_documented_sort():
    session = Session(Response(search_payload(pmids=["123", "456"])))
    result = PubMedClient(api_key="private-key", email="private@example.org", session=session).search(" cancer ", limit=2)
    assert result.count == 127 and result.pmids == ["123", "456"]
    assert result.query == "cancer" and result.translation == "cancer[All Fields]"
    assert datetime.fromisoformat(result.retrieved_at).tzinfo is not None
    url, options = session.calls[0]
    assert "private" not in url and "?" not in url
    assert options["data"]["api_key"] == "private-key"
    assert options["data"]["sort"] == "pub_date"
    assert options["allow_redirects"] is False
    assert options["timeout"] == (4, 12)


def test_valid_zero_count_remains_zero():
    result = PubMedClient(session=Session(Response(search_payload(count="0")))).search("unmatched term")
    assert result.count == 0 and result.pmids == []


@pytest.mark.parametrize("payload", [
    {"error": "API rate limit exceeded private-key https://secret-url"},
    {"esearchresult": {"count": "0", "idlist": [], "errorlist": {"fieldsnotfound": ["oops"]}}},
    {"esearchresult": {"count": "0", "idlist": [], "ERROR": "failed"}},
    {}, [], search_payload(count="NaN"), search_payload(count=-1), search_payload(count=True),
    search_payload(count=1.5), search_payload(count="1" * 13),
    search_payload(pmids=["invalid"]), search_payload(pmids=["123", "123"]),
    search_payload(count="0", pmids=["123"]), search_payload(querytranslation=[]),
    search_payload(warninglist=[]), ValueError("private-key https://secret-url"),
])
def test_search_errors_are_not_misreported_as_zero_and_do_not_leak(payload):
    session = Session(Response(payload))
    with pytest.raises(PubMedError) as exc:
        PubMedClient(api_key="private-key", session=session).search("cancer")
    assert "private-key" not in str(exc.value) and "https://" not in str(exc.value)
    assert len(session.calls) == 1


def test_warning_text_is_preserved_with_secret_and_url_redaction():
    payload = search_payload(warninglist={"quotedphrasesnotfound": ["Quoted phrase not found: unusual phrase", "private-key https://bad/?api_key=private-key"]})
    result = PubMedClient(api_key="private-key", session=Session(Response(payload))).search("unusual phrase")
    assert result.count == 127
    assert "Quoted phrase not found: unusual phrase" in result.warnings
    assert "private-key" not in " ".join(result.warnings)
    assert "https://" not in " ".join(result.warnings)


@pytest.mark.parametrize("query, limit", [("", 0), ("  ", 0), (None, 0), ("a" * 8001, 0), ("cancer", -1), ("cancer", 51), ("cancer", True), ("cancer", 1.2)])
def test_query_validation_does_not_send_a_request(query, limit):
    session = Session()
    with pytest.raises(PubMedError):
        PubMedClient(session=session).search(query, limit=limit)
    assert not session.calls


@pytest.mark.parametrize("first", [Response(status=429, headers={"Retry-After": "1000"}), Response(status=503), requests.Timeout("private-key")])
def test_transient_failures_retry_with_bounded_backoff(first, request_clock):
    session = Session(first, Response(search_payload(count="0")))
    assert PubMedClient(session=session).search("cancer").count == 0
    assert len(session.calls) == 2
    assert max(request_clock.sleeps) <= 5


def test_nontransient_error_does_not_retry():
    session = Session(Response(status=403))
    with pytest.raises(PubMedError):
        PubMedClient(session=session).search("cancer")
    assert len(session.calls) == 1


def test_network_failure_stops_after_three_attempts():
    session = Session(*[requests.ConnectionError("private-key https://secret") for _ in range(3)])
    with pytest.raises(PubMedError) as exc:
        PubMedClient(session=session).search("cancer")
    assert len(session.calls) == 3
    assert "private-key" not in str(exc.value)


def test_every_client_and_endpoint_shares_rate_limit(request_clock):
    starts = []

    class TimedSession(Session):
        def post(self, url, **kwargs):
            starts.append(request_clock.now)
            return super().post(url, **kwargs)

    first = PubMedClient(session=TimedSession(Response(search_payload())))
    second = PubMedClient(api_key="key", session=TimedSession(xml_response(record())))
    first.search("cancer")
    second.fetch(["123"])
    assert starts[1] - starts[0] >= 0.36 - 1e-9


def test_concurrent_client_calls_are_serialized(request_clock):
    starts, active, maximum = [], 0, 0
    guard = threading.Lock()

    class ConcurrentSession:
        def post(self, url, **kwargs):
            nonlocal active, maximum
            with guard:
                active += 1
                maximum = max(active, maximum)
                starts.append(request_clock.now)
            real_time.sleep(0.005)
            with guard:
                active -= 1
            return Response(search_payload())

    with ThreadPoolExecutor(max_workers=4) as executor:
        results = list(executor.map(lambda _: PubMedClient(session=ConcurrentSession()).search("cancer"), range(4)))
    assert len(results) == 4 and maximum == 1
    assert all(later - earlier >= 0.36 - 1e-9 for earlier, later in zip(starts, starts[1:]))


def test_fetch_preserves_mixed_text_structured_abstract_authors_and_medline_date():
    xml = """<PubmedArticleSet><PubmedArticle><MedlineCitation><PMID>123</PMID>
      <Article><ArticleTitle>Deep <i>learning</i> &amp; medicine</ArticleTitle>
      <Abstract><AbstractText Label="METHODS">We studied <b>42</b> people.</AbstractText>
      <AbstractText NlmCategory="RESULTS">AUC 0.8.</AbstractText></Abstract>
      <Journal><Title>Medical AI</Title><JournalIssue><PubDate><MedlineDate>2024 Dec-2025 Jan</MedlineDate></PubDate></JournalIssue></Journal>
      <AuthorList><Author><LastName>Kim</LastName><ForeName>Min</ForeName></Author>
      <Author><CollectiveName>AI Study Group</CollectiveName></Author></AuthorList>
      <PublicationTypeList><PublicationType>Clinical Trial</PublicationType><PublicationType>Retracted Publication</PublicationType></PublicationTypeList>
      <ELocationID EIdType="doi">10.1234/fallback</ELocationID></Article>
      <MeshHeadingList><MeshHeading><DescriptorName>Machine Learning</DescriptorName><QualifierName>methods</QualifierName></MeshHeading></MeshHeadingList>
      </MedlineCitation><PubmedData><ArticleIdList><ArticleId IdType="doi">10.1234/main</ArticleId></ArticleIdList></PubmedData>
      </PubmedArticle></PubmedArticleSet>"""
    result = PubMedClient(session=Session(Response(xml=xml))).fetch(["123"])[0]
    assert result.title == "Deep learning & medicine"
    assert result.abstract == "METHODS: We studied 42 people.\n\nRESULTS: AUC 0.8."
    assert result.year == "2024" and result.publication_date == "2024 Dec-2025 Jan"
    assert result.authors == ["Min Kim", "AI Study Group"]
    assert result.mesh_terms == ["Machine Learning"] and result.retracted
    assert result.doi == "10.1234/main" and result.journal == "Medical AI"


def test_missing_abstract_and_date_are_preserved_and_order_restored():
    session = Session(xml_response(record("456"), record("123", extra='<CommentsCorrectionsList><CommentsCorrections RefType="RetractionIn"/></CommentsCorrectionsList>')))
    results = PubMedClient(session=session).fetch(["123", "456", "123"])
    assert [article.pmid for article in results] == ["123", "456"]
    assert results[0].abstract == "" and results[0].year == "" and results[0].retracted


def test_book_citation_and_electronic_date_fallback():
    book = """<PubmedBookArticle><BookDocument><PMID>123</PMID><ArticleTitle>AI chapter</ArticleTitle>
      <Book><BookTitle>Clinical AI</BookTitle><PubDate><Year>2025</Year><Month>Jan</Month></PubDate></Book>
      <Abstract><AbstractText>Book abstract.</AbstractText></Abstract></BookDocument>
      <PubmedBookData><ArticleIdList><ArticleId IdType="doi">10.1111/book</ArticleId></ArticleIdList></PubmedBookData></PubmedBookArticle>"""
    session = Session(xml_response(book, record("456", article_extra='<ArticleDate><Year>2024</Year><Month>03</Month><Day>12</Day></ArticleDate><ELocationID EIdType="doi">10.1234/electronic</ELocationID>')))
    book_result, electronic = PubMedClient(session=session).fetch(["123", "456"])
    assert book_result.journal == "Clinical AI" and book_result.year == "2025"
    assert book_result.doi == "10.1111/book" and book_result.abstract == "Book abstract."
    assert electronic.publication_date == "2024 03 12" and electronic.doi == "10.1234/electronic"


@pytest.mark.parametrize("xml", ["", "<broken", '<ERROR>private-key</ERROR>', '<PubmedArticleSet><ERROR>bad</ERROR></PubmedArticleSet>', '<PubmedArticleSet/>', '<PubmedArticleSet><Other/></PubmedArticleSet>', '<PubmedArticleSet>' + record("456") + '</PubmedArticleSet>', '<PubmedArticleSet>' + record(title="") + '</PubmedArticleSet>', '<!DOCTYPE x [<!ENTITY test "private-key">]><PubmedArticleSet/>'])
def test_fetch_rejects_malformed_error_missing_and_wrong_records(xml):
    with pytest.raises(PubMedError) as exc:
        PubMedClient(session=Session(Response(xml=xml))).fetch(["123"])
    assert "private-key" not in str(exc.value)


@pytest.mark.parametrize("pmids", ["123", ["0"], ["1,2"], [123], ["123"] * 51])
def test_fetch_validation_avoids_network(pmids):
    session = Session()
    with pytest.raises(PubMedError):
        PubMedClient(session=session).fetch(pmids)
    assert not session.calls


def test_fetch_empty_list_avoids_network():
    assert PubMedClient(session=Session()).fetch([]) == []
