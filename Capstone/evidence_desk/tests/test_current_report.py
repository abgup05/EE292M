"""The 8-K splitter, on recorded NVIDIA current reports and on small made-up ones."""

from __future__ import annotations

import pytest

from app.core.documents import Document
from app.sources.current_report import (
    COVER_HEADING,
    FALLBACK_HEADING,
    TRAILER_HEADING,
    normalise_number,
    parse_current_report,
    parser_version,
)
from tests.fakes import recorded_html

URL = "https://www.sec.gov/Archives/edgar/data/1045810/x/nvda.htm"
# Items 5.02 and 9.01: the resignation of the chief executive (filed 12 November 2026).
RESIGNATION = "nvda-8k-0001045810-26-000082.htm.gz"
# Items 1.01, 2.03, 7.01 and 9.01: a credit agreement (filed 17 August 2026).
SEVERAL_ITEMS = "nvda-8k-0001045810-26-000069.htm.gz"
# Items 8.01 and 9.01, each title on the line after its number (filed by an agent, 18 June 2026).
TITLE_ON_NEXT_LINE = "nvda-8k-0001193125-26-275783.htm.gz"


def parse(html: str) -> Document:
    return parse_current_report(html, url=URL, title="8-K", published_date="2026-11-12")


def headings(document: Document) -> list[str]:
    return [section.heading for section in document.sections]


def made_up(*lines: str) -> str:
    return "<html><body>" + "".join(f"<p>{line}</p>" for line in lines) + "</body></html>"


def test_every_section_is_an_exact_substring_of_the_stored_text() -> None:
    for name in (RESIGNATION, SEVERAL_ITEMS, TITLE_ON_NEXT_LINE):
        document = parse(recorded_html(name))
        cursor = 0
        for section in document.sections:
            found = document.text.find(f"{section.heading}\n{section.text}", cursor)
            assert found >= 0, (name, section.heading)
            cursor = found + len(section.heading) + 1 + len(section.text)


def test_the_resignation_report_splits_into_its_two_items_and_the_signature() -> None:
    document = parse(recorded_html(RESIGNATION))
    assert headings(document) == [
        COVER_HEADING,
        "Item 5.02. Departure of Directors or Certain Officers; Election of Directors; "
        "Appointment of Certain Officers; Compensatory Arrangements of Certain Officers",
        "Item 9.01. Financial Statements and Exhibits",
        TRAILER_HEADING,
    ]
    departure = document.sections[1].text
    assert departure.startswith("On November 11, 2026, the Board of Directors")
    assert "accepted the resignation of Jen-Hsun Huang" in departure


def test_the_signature_block_is_not_part_of_the_last_item() -> None:
    document = parse(recorded_html(RESIGNATION))
    exhibits = document.sections[2].text
    assert "Pursuant to the requirements" not in exhibits
    assert "/s/" not in exhibits
    assert document.sections[3].text.startswith("SIGNATURE")


def test_a_report_of_four_items_has_a_section_for_each() -> None:
    document = parse(recorded_html(SEVERAL_ITEMS))
    assert [h.split(".")[0] + "." + h.split(".")[1][:2] for h in headings(document)[1:-1]] == [
        "Item 1.01",
        "Item 2.03",
        "Item 7.01",
        "Item 9.01",
    ]


def test_a_title_on_the_line_after_the_number_is_taken_as_the_title() -> None:
    document = parse(recorded_html(TITLE_ON_NEXT_LINE))
    assert headings(document)[1:-1] == [
        "Item 8.01. Other Events",
        "Item 9.01. Financial Statements and Exhibits",
    ]


def test_a_heading_naming_two_items_heads_one_section_for_both() -> None:
    document = parse(
        made_up(
            "Items 2.02 and 7.01. Results of Operations; Regulation FD Disclosure.",
            "On May 20, 2026, the company announced its results.",
            "SIGNATURES",
            "By: /s/ A Person",
        )
    )
    assert headings(document) == [
        "Items 2.02 and 7.01. Results of Operations; Regulation FD Disclosure",
        TRAILER_HEADING,
    ]


def test_a_reference_to_an_item_inside_a_sentence_opens_no_section() -> None:
    document = parse(
        made_up(
            "Item 2.03 Creation of a Direct Financial Obligation.",
            "Item 1.01 above is incorporated by reference into this Item 2.03.",
        )
    )
    assert headings(document) == ["Item 2.03. Creation of a Direct Financial Obligation"]
    assert document.sections[0].text.startswith("Item 1.01 above")


def test_the_signature_sentence_ends_the_last_item_when_there_is_no_heading() -> None:
    document = parse(
        made_up(
            "Item 8.01 Other Events.",
            "The company sold a building.",
            "Pursuant to the requirements of the Securities Exchange Act of 1934, the registrant "
            "has duly caused this report to be signed.",
        )
    )
    assert headings(document) == ["Item 8.01. Other Events", TRAILER_HEADING]
    assert document.sections[0].text == "The company sold a building."


def test_an_exhibit_index_after_the_last_item_is_not_part_of_it() -> None:
    document = parse(
        made_up(
            "ITEM 9.01 FINANCIAL STATEMENTS AND EXHIBITS",
            "(d) Exhibits.",
            "EXHIBIT INDEX",
            "99.1 Press release",
            "SIGNATURE",
        )
    )
    assert headings(document) == ["Item 9.01. FINANCIAL STATEMENTS AND EXHIBITS", TRAILER_HEADING]
    assert document.sections[0].text == "(d) Exhibits."


def test_a_report_with_no_item_heading_is_one_full_document_section() -> None:
    document = parse(made_up("A notice with no item heading."))
    assert headings(document) == [FALLBACK_HEADING]


def test_of_two_sections_for_one_item_the_longer_is_kept() -> None:
    document = parse(
        made_up(
            "Item 5.02 Departure of Directors",
            "Item 5.02 Departure of Directors",
            "On June 1, the chief financial officer resigned. A successor was named.",
        )
    )
    assert headings(document) == ["Item 5.02. Departure of Directors"]
    assert document.sections[0].text.startswith("On June 1")


@pytest.mark.parametrize(("raw", "number"), [("5.02", "5.02"), ("5.2", "5.02"), ("09.01", "9.01")])
def test_item_numbers_are_written_as_the_index_writes_them(raw: str, number: str) -> None:
    assert normalise_number(raw) == number


def test_the_splitter_has_a_version_of_its_own() -> None:
    assert parser_version().startswith("8k-")
