"""Bounded page retrieval: size cap, HTML only, safe redirects, failures reported."""

import httpx
import pytest

from app.fetch import MAX_BYTES, FetchError, fetch_page
from app.urls import UnsafeURL

PUBLIC = ["93.184.216.34"]


def public_resolver(hostname: str, port: int) -> list[str]:
    if hostname == "internal.test":
        raise UnsafeURL("Host 'internal.test' resolves to a private address")
    return PUBLIC


def make_client(handler) -> httpx.Client:
    return httpx.Client(transport=httpx.MockTransport(handler))


def test_returns_html_with_final_url_after_public_redirect() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/old":
            return httpx.Response(301, headers={"location": "https://example.org/new"})
        return httpx.Response(
            200,
            headers={"content-type": "text/html; charset=utf-8"},
            text="<h1>New</h1>",
        )

    page = fetch_page(
        "https://example.org/old", client=make_client(handler), resolver=public_resolver
    )
    assert page.requested_url == "https://example.org/old"
    assert page.final_url == "https://example.org/new"
    assert page.html == "<h1>New</h1>"
    assert page.retrieved_at.tzinfo is not None


def test_rejects_redirect_to_private_literal_address() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(302, headers={"location": "http://10.0.0.5/admin"})

    with pytest.raises(FetchError, match="Private or local"):
        fetch_page(
            "https://example.org/",
            client=make_client(handler),
            resolver=public_resolver,
        )


def test_rejects_redirect_to_host_resolving_privately() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.host == "example.org":
            return httpx.Response(302, headers={"location": "https://internal.test/x"})
        return httpx.Response(200, headers={"content-type": "text/html"}, text="secret")

    with pytest.raises(FetchError, match="private address"):
        fetch_page(
            "https://example.org/",
            client=make_client(handler),
            resolver=public_resolver,
        )


def test_rejects_non_html_response() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, headers={"content-type": "application/pdf"}, content=b"%PDF")

    with pytest.raises(FetchError, match="not HTML"):
        fetch_page(
            "https://example.org/r.pdf",
            client=make_client(handler),
            resolver=public_resolver,
        )


def test_rejects_body_over_size_limit() -> None:
    big = b"<p>" + b"x" * (MAX_BYTES + 1) + b"</p>"

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, headers={"content-type": "text/html"}, content=big)

    with pytest.raises(FetchError, match="2 MB"):
        fetch_page(
            "https://example.org/big",
            client=make_client(handler),
            resolver=public_resolver,
        )


def test_reports_http_error_status() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(404, headers={"content-type": "text/html"}, text="gone")

    with pytest.raises(FetchError, match="HTTP 404"):
        fetch_page(
            "https://example.org/missing",
            client=make_client(handler),
            resolver=public_resolver,
        )


def test_reports_timeout() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ReadTimeout("slow", request=request)

    with pytest.raises(FetchError, match="timed out"):
        fetch_page(
            "https://example.org/slow",
            client=make_client(handler),
            resolver=public_resolver,
        )


def test_stops_redirect_loops() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(302, headers={"location": "https://example.org/loop"})

    with pytest.raises(FetchError, match="redirects"):
        fetch_page(
            "https://example.org/loop",
            client=make_client(handler),
            resolver=public_resolver,
        )
