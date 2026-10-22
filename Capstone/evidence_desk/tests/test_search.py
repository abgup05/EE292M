"""Optional web discovery: queries per subquestion, bounded results, key stays server-side."""

import httpx
import pytest

from app.models import Subquestion
from app.search import BraveSearcher, SearchError

SUBQUESTIONS = [
    Subquestion(id="sq-1", text="What risks?", search_query="generative ai risks"),
    Subquestion(id="sq-2", text="What benefits?", search_query="generative ai benefits"),
]


def make_client(handler) -> httpx.Client:
    return httpx.Client(transport=httpx.MockTransport(handler))


def results(*urls: str) -> dict:
    return {"web": {"results": [{"url": url, "title": "t"} for url in urls]}}


def test_collects_urls_per_query_up_to_limit() -> None:
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        query = request.url.params["q"]
        return httpx.Response(200, json=results(f"https://a.org/{query[-5:]}", "https://b.org/x"))

    searcher = BraveSearcher("secret-key", client=make_client(handler))
    urls = searcher(SUBQUESTIONS, 3)
    assert urls == ["https://a.org/risks", "https://b.org/x", "https://a.org/efits"]
    assert [r.url.params["q"] for r in seen] == ["generative ai risks", "generative ai benefits"]
    assert all(r.headers["x-subscription-token"] == "secret-key" for r in seen)


def test_skips_non_http_results() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=results("ftp://a.org/f", "https://ok.org/"))

    searcher = BraveSearcher("k", client=make_client(handler))
    assert searcher(SUBQUESTIONS[:1], 10) == ["https://ok.org/"]


def test_provider_error_raises_without_leaking_key() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(429, text="slow down")

    searcher = BraveSearcher("secret-key", client=make_client(handler))
    with pytest.raises(SearchError) as info:
        searcher(SUBQUESTIONS[:1], 10)
    assert "secret-key" not in str(info.value)
    assert "429" in str(info.value)
