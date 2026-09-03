from __future__ import annotations

import pytest
import requests

from src.seo_sources import SourceError, YouTubeClient


class FakeResponse:
    def __init__(
        self,
        payload=None,
        *,
        status_code=200,
        text="",
        headers=None,
        json_error: Exception | None = None,
    ):
        self._payload = payload
        self._json_error = json_error
        self.status_code = status_code
        self.ok = status_code < 400
        self.text = text
        self.reason = text
        self.headers = headers or {}

    def json(self):
        if self._json_error is not None:
            raise self._json_error
        return self._payload


class FakeSession:
    def __init__(self, outcomes):
        self.outcomes = list(outcomes)
        self.calls = []

    def get(self, url, **kwargs):
        self.calls.append((url, kwargs))
        outcome = self.outcomes.pop(0)
        if isinstance(outcome, BaseException):
            raise outcome
        return outcome


def test_youtube_timeout_is_bounded_and_wrapped_as_source_error():
    session = FakeSession([requests.Timeout("slow"), requests.Timeout("still slow")])
    sleeps = []
    client = YouTubeClient(api_key="key", session=session, sleeper=sleeps.append)

    with pytest.raises(SourceError, match="request timed out") as caught:
        client.trending_snapshot(max_results=1)

    assert caught.value.source == "youtube_data_api"
    assert caught.value.status_code is None
    assert len(session.calls) == 2
    assert session.calls[0][1]["timeout"] == (3.05, 10.0)
    assert sleeps == [0.4]


def test_youtube_invalid_json_is_wrapped_without_retry():
    session = FakeSession(
        [FakeResponse(json_error=ValueError("not json"))]
    )
    client = YouTubeClient(api_key="key", session=session, sleeper=lambda _: None)

    with pytest.raises(SourceError, match="invalid JSON response") as caught:
        client.trending_snapshot(max_results=1)

    assert caught.value.source == "youtube_data_api"
    assert len(session.calls) == 1


def test_youtube_transient_5xx_retries_once_then_succeeds():
    session = FakeSession(
        [
            FakeResponse(status_code=503, text="temporarily unavailable"),
            FakeResponse({"items": []}),
        ]
    )
    sleeps = []
    client = YouTubeClient(api_key="key", session=session, sleeper=sleeps.append)

    assert client.trending_snapshot(max_results=1) == []
    assert len(session.calls) == 2
    assert sleeps == [0.4]


def test_youtube_exhausted_5xx_preserves_status_code():
    session = FakeSession(
        [
            FakeResponse(status_code=500, text="first failure"),
            FakeResponse(status_code=503, text="second failure"),
        ]
    )
    client = YouTubeClient(api_key="key", session=session, sleeper=lambda _: None)

    with pytest.raises(SourceError, match="second failure") as caught:
        client.trending_snapshot(max_results=1)

    assert caught.value.status_code == 503
    assert len(session.calls) == 2
