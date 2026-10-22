"""URL safety and canonicalization: what may be fetched and what counts as one source."""

import pytest

from app.urls import UnsafeURL, canonicalize, is_private_address, validate_public_url


@pytest.mark.parametrize(
    "url",
    [
        "ftp://example.org/file",
        "file:///etc/passwd",
        "javascript:alert(1)",
        "not a url",
        "https://",
        "http://localhost/admin",
        "http://127.0.0.1:8000/",
        "https://10.0.0.5/internal",
        "https://192.168.1.1/",
        "https://172.16.4.4/",
        "https://[::1]/",
        "https://169.254.169.254/latest/meta-data",
        "https://user:pw@example.org/",
    ],
)
def test_rejects_unsafe_or_malformed_urls(url: str) -> None:
    with pytest.raises(UnsafeURL):
        validate_public_url(url)


def test_accepts_public_http_and_https() -> None:
    assert validate_public_url("https://www.nist.gov/publications/x") == (
        "https://www.nist.gov/publications/x"
    )
    assert validate_public_url("http://example.org/page") == "http://example.org/page"


@pytest.mark.parametrize(
    ("address", "private"),
    [
        ("127.0.0.1", True),
        ("10.1.2.3", True),
        ("172.31.255.255", True),
        ("192.168.0.1", True),
        ("169.254.1.1", True),
        ("::1", True),
        ("fd00::1", True),
        ("0.0.0.0", True),
        ("8.8.8.8", False),
        ("2606:4700::1111", False),
    ],
)
def test_private_address_detection(address: str, private: bool) -> None:
    assert is_private_address(address) is private


@pytest.mark.parametrize(
    ("raw", "canonical"),
    [
        ("HTTPS://WWW.GAO.GOV/products/gao-24-106946", "https://www.gao.gov/products/gao-24-106946"),
        ("https://www.gao.gov/products/gao-24-106946/", "https://www.gao.gov/products/gao-24-106946"),
        ("https://www.gao.gov/products/gao-24-106946#summary", "https://www.gao.gov/products/gao-24-106946"),
        (
            "https://www.gao.gov/products/gao-24-106946?utm_source=x&utm_medium=y",
            "https://www.gao.gov/products/gao-24-106946",
        ),
        ("https://www.gao.gov:443/products/a?b=2&a=1", "https://www.gao.gov/products/a?a=1&b=2"),
        ("http://example.org:80/", "http://example.org/"),
    ],
)
def test_canonicalize_merges_equivalent_urls(raw: str, canonical: str) -> None:
    assert canonicalize(raw) == canonical
