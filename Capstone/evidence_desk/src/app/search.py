"""Optional web discovery through the Brave Search API.

The API key never leaves the server and never appears in error messages.
Discovery is bounded: one query per subquestion, at most ``limit`` URLs in
total, and only ``http(s)`` results are returned.
"""

from __future__ import annotations

import os

import httpx

from app.models import Subquestion

ENDPOINT = "https://api.search.brave.com/res/v1/web/search"
RESULTS_PER_QUERY = 10
TIMEOUT_SECONDS = 12.0


class SearchError(RuntimeError):
    """The provider could not be queried; the message is safe to show."""


class BraveSearcher:
    """Callable ``(subquestions, limit) -> urls`` backed by Brave web search."""

    def __init__(self, api_key: str, client: httpx.Client | None = None) -> None:
        self._api_key = api_key
        self._client = client or httpx.Client(timeout=TIMEOUT_SECONDS)

    def __call__(self, subquestions: list[Subquestion], limit: int) -> list[str]:
        urls: list[str] = []
        for subquestion in subquestions:
            if len(urls) >= limit:
                break
            for url in self._query(subquestion.search_query):
                if url.startswith(("http://", "https://")) and url not in urls:
                    urls.append(url)
                if len(urls) >= limit:
                    break
        return urls

    def _query(self, query: str) -> list[str]:
        try:
            response = self._client.get(
                ENDPOINT,
                params={"q": query, "count": RESULTS_PER_QUERY},
                headers={"x-subscription-token": self._api_key, "accept": "application/json"},
            )
        except httpx.HTTPError as exc:
            raise SearchError(f"Search request failed: {exc.__class__.__name__}") from exc
        if response.status_code != 200:
            raise SearchError(f"Search provider returned HTTP {response.status_code}")
        try:
            results = response.json().get("web", {}).get("results", [])
        except ValueError as exc:
            raise SearchError("Search provider returned malformed JSON") from exc
        return [str(item.get("url", "")) for item in results if isinstance(item, dict)]


def searcher_from_env() -> BraveSearcher | None:
    """Return a searcher when ``BRAVE_SEARCH_API_KEY`` is set, else None."""
    key = os.environ.get("BRAVE_SEARCH_API_KEY", "").strip()
    return BraveSearcher(key) if key else None
