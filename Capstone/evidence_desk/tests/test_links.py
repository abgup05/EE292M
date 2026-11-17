"""Deep links that open a source page at an excerpt (URL Text Fragments)."""

from urllib.parse import unquote

import pytest

from app.core.links import passage_link

FILING = "https://www.sec.gov/Archives/edgar/data/1045810/000104581026000075/nvda-20260726.htm"


def _fragment_parts(link: str) -> list[str]:
    _, _, directive = link.partition("#:~:text=")
    return [unquote(part) for part in directive.split(",")]


def test_short_excerpt_is_used_whole() -> None:
    link = passage_link(FILING, "Data Center revenue grew 56% from a year ago.")
    assert link.startswith(FILING + "#:~:text=")
    assert _fragment_parts(link) == ["Data Center revenue grew 56% from a year ago."]


def test_long_excerpt_uses_first_and_last_five_words() -> None:
    excerpt = "one two three four five six seven eight nine ten eleven twelve"
    link = passage_link(FILING, excerpt)
    assert _fragment_parts(link) == ["one two three four five", "eight nine ten eleven twelve"]


def test_exactly_ten_words_is_used_whole() -> None:
    excerpt = "one two three four five six seven eight nine ten"
    assert _fragment_parts(passage_link(FILING, excerpt)) == [excerpt]


def test_whitespace_runs_are_collapsed() -> None:
    link = passage_link(FILING, "Risk\nfactors  could harm us")
    assert _fragment_parts(link) == ["Risk factors could harm us"]


@pytest.mark.parametrize("character", ["-", ",", "&"])
def test_reserved_characters_are_percent_encoded(character: str) -> None:
    link = passage_link(FILING, f"left {character} right")
    directive = link.partition("#:~:text=")[2]
    assert character not in directive
    assert unquote(directive) == f"left {character} right"


def test_spaces_and_unicode_are_encoded() -> None:
    directive = passage_link(FILING, "the company’s results").partition("#:~:text=")[2]
    assert " " not in directive
    assert "%E2%80%99" in directive


def test_existing_fragment_is_replaced() -> None:
    link = passage_link(FILING + "#item2", "Data Center revenue grew.")
    assert link == FILING + "#:~:text=Data%20Center%20revenue%20grew."


@pytest.mark.parametrize(
    "url", ["ftp://example.org/file.htm", "mailto:ir@example.org", "/relative/path", ""]
)
def test_non_http_urls_are_unchanged(url: str) -> None:
    assert passage_link(url, "Data Center revenue grew.") == url


def test_empty_excerpt_leaves_url_unchanged() -> None:
    assert passage_link(FILING, "   ") == FILING
