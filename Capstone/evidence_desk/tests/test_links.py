"""Deep links that open a source page at an excerpt (URL Text Fragments)."""

from urllib.parse import unquote

import pytest

from app.core.links import link_kind, passage_link

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
    # Within one line; line breaks are the subject of the first-line tests below.
    link = passage_link(FILING, "Risk \tfactors  could harm us")
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


# The referee's finding 7: what a text fragment cannot match ---------------------------------

PARAGRAPHS = (
    "Data Center revenue grew 56% from a year ago.\n"
    "Gaming revenue was down 3% from a year ago and up 9% sequentially."
)


def test_a_multi_line_excerpt_links_by_its_first_line_only() -> None:
    """Text fragments do not match across block boundaries, so only the first line is used."""
    link = passage_link(FILING, PARAGRAPHS)
    assert _fragment_parts(link) == ["Data Center revenue grew 56% from a year ago."]
    assert link_kind(PARAGRAPHS) == "first-line"


def test_a_long_first_line_uses_its_own_first_and_last_five_words() -> None:
    excerpt = "one two three four five six seven eight nine ten eleven twelve\nthirteen fourteen"
    assert _fragment_parts(passage_link(FILING, excerpt)) == [
        "one two three four five",
        "eight nine ten eleven twelve",
    ]


def test_blank_lines_before_the_first_line_are_skipped() -> None:
    assert _fragment_parts(passage_link(FILING, "\n\n  Risk factors\nmore")) == ["Risk factors"]


@pytest.mark.parametrize(
    "row",
    [
        "Data Center $41,096 $30,771 34%",
        "Purchases of property and equipment (3,236) (1,069)",
        "$ 96,221 $ 46,743 106 %",
        "Revenue $ 46,743",
    ],
)
def test_a_table_row_links_to_the_document_without_a_fragment(row: str) -> None:
    """The stored row re-attaches "$" and "%" to its cells, so it cannot match the page."""
    assert passage_link(FILING, row) == FILING
    assert link_kind(row) == "document"


def test_a_table_row_on_the_first_line_links_to_the_document() -> None:
    excerpt = "Data Center $41,096 $30,771 34%\nData Center revenue grew 34%."
    assert passage_link(FILING, excerpt) == FILING
    assert link_kind(excerpt) == "document"


@pytest.mark.parametrize(
    "prose",
    [
        "Data Center revenue grew 56% from a year ago.",
        "Revenue for the second quarter of fiscal 2027 was $96.2 billion",
        "Sales to one customer represented 16% of revenue in 2026 and 12% in 2025",
    ],
)
def test_prose_with_numbers_is_a_passage(prose: str) -> None:
    assert link_kind(prose) == "passage"
    assert passage_link(FILING, prose) != FILING


def test_an_empty_excerpt_is_a_document_link() -> None:
    assert link_kind("  \n ") == "document"
