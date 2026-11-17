"""Splitting an SEC filing into its Items: recorded NVIDIA filings and constructed HTML."""

from __future__ import annotations

import gzip
import hashlib
import json
import re
import time
from pathlib import Path

import pytest

from app.core.documents import Document
from app.sources.filing import parse_filing

EDGAR = Path(__file__).parent / "fixtures" / "edgar"
Q_FIXTURE = "nvda-10q-20260726.htm.gz"
K_FIXTURE = "nvda-10k-20260125.htm.gz"
MAX_PARSE_SECONDS = 20.0


def recorded_html(name: str) -> str:
    path = EDGAR / name
    if not path.exists():
        pytest.skip("EDGAR fixtures not recorded; run `make fixtures`")
    return gzip.decompress(path.read_bytes()).decode("utf-8", errors="replace")


def recorded_url(name: str) -> str:
    return json.loads((EDGAR / "manifest.json").read_text())[name]["url"]


def parse_recorded(name: str, title: str, filed: str) -> Document:
    html = recorded_html(name)
    return parse_filing(html, url=recorded_url(name), title=title, published_date=filed)


@pytest.fixture(scope="module")
def quarterly() -> Document:
    return parse_recorded(Q_FIXTURE, "NVIDIA 10-Q for the period ended 2026-07-26", "2026-08-26")


@pytest.fixture(scope="module")
def annual() -> Document:
    started = time.perf_counter()
    document = parse_recorded(K_FIXTURE, "NVIDIA 10-K for fiscal 2026", "2026-02-25")
    assert time.perf_counter() - started < MAX_PARSE_SECONDS
    return document


def item_chars(document: Document, prefix: str) -> int:
    """Characters under one Item, counting its sub-headed sections."""
    return sum(
        len(section.text)
        for section in document.sections
        if section.heading == prefix or section.heading.startswith(prefix + ".")
    )


def headings(document: Document) -> list[str]:
    return [section.heading for section in document.sections]


# Recorded 10-Q (NVIDIA, period ended 2026-07-26, accession 0001045810-26-000075)


def test_quarterly_finds_mda_and_risk_factors_with_substance(quarterly: Document) -> None:
    assert item_chars(quarterly, "Part I, Item 2") > 5000
    assert item_chars(quarterly, "Part II, Item 1A") > 5000
    assert any(
        heading.startswith("Part I, Item 2. Management") and "Results of Operations" in heading
        for heading in headings(quarterly)
    )


def test_quarterly_keeps_part_one_and_part_two_item_one_apart(quarterly: Document) -> None:
    assert item_chars(quarterly, "Part I, Item 1") > 5000  # the financial statements
    assert any(h.startswith("Part II, Item 1. Legal Proceedings") for h in headings(quarterly))


def test_quarterly_drops_the_inline_xbrl_header(quarterly: Document) -> None:
    assert "ix:header" not in quarterly.text
    assert "dei:EntityCentralIndexKey" not in quarterly.text
    assert "0001045810" not in quarterly.text.split("\n\n")[0][:200]


def test_quarterly_sections_are_exact_substrings(quarterly: Document) -> None:
    assert quarterly.sections
    for section in quarterly.sections:
        assert section.text
        assert section.text in quarterly.text
        assert f"{section.heading}\n{section.text}" in quarterly.text


def test_quarterly_has_one_body_occurrence_per_item(quarterly: Document) -> None:
    assert headings(quarterly)[0] == "Cover page"
    items = [h.split(" › ")[0] for h in headings(quarterly)[1:]]
    runs = [item for before, item in zip([None, *items], items, strict=False) if before != item]
    assert len(runs) == len(set(runs))  # no Item appears in two places


def test_quarterly_has_sub_headed_sections(quarterly: Document) -> None:
    assert any(h.startswith("Part I, Item 2. ") and " › " in h for h in headings(quarterly))


def test_quarterly_drops_page_numbers_and_running_contents_links(quarterly: Document) -> None:
    lines = quarterly.text.split("\n")
    assert not [line for line in lines if line.isdigit() and len(line) <= 3]
    assert not [line for line in lines if line.casefold() == "table of contents"]


def test_quarterly_metadata_and_stable_hash(quarterly: Document) -> None:
    again = parse_recorded(Q_FIXTURE, "NVIDIA 10-Q for the period ended 2026-07-26", "2026-08-26")
    assert again.content_hash == quarterly.content_hash
    assert quarterly.content_hash == hashlib.sha256(quarterly.text.encode()).hexdigest()
    assert quarterly.publisher == "SEC EDGAR"
    assert quarterly.published_date == "2026-08-26"
    assert quarterly.url.endswith("/000104581026000075/nvda-20260726.htm")


def test_quarterly_table_rows_join_currency_and_percent(quarterly: Document) -> None:
    assert re.search(r"\$\d", quarterly.text)
    assert not re.search(r"(^| )\$ [\d(]", quarterly.text, re.MULTILINE)
    assert not re.search(r"\d %", quarterly.text)


# Recorded 10-K (NVIDIA, fiscal year ended 2026-01-25, accession 0001045810-26-000021)


def test_annual_finds_business_risk_factors_and_mda(annual: Document) -> None:
    assert any(h.startswith("Item 1. Business") for h in headings(annual))
    assert item_chars(annual, "Item 1A") > 20000
    assert item_chars(annual, "Item 7") > 20000
    assert not any(h.startswith("Part ") for h in headings(annual))


def test_annual_sections_are_exact_substrings(annual: Document) -> None:
    for section in annual.sections:
        assert section.text in annual.text


# Constructed HTML

STYLE_BOLD = 'style="font-weight:700"'


def page(body: str, document_type: str | None = None) -> str:
    header = ""
    if document_type:
        header = (
            '<div style="display:none"><ix:header><ix:hidden>'
            f'<ix:nonNumeric name="dei:DocumentType" contextRef="c-1">{document_type}'
            "</ix:nonNumeric></ix:hidden></ix:header></div>"
        )
    return f"<html><head><title>t</title></head><body>{header}{body}</body></html>"


def parse(html: str) -> Document:
    return parse_filing(html, url="https://www.sec.gov/x.htm", title="t", published_date=None)


def bold(text: str) -> str:
    return f"<div><span {STYLE_BOLD}>{text}</span></div>"


def para(text: str) -> str:
    return f"<div><span>{text}</span></div>"


def toc_row(item: str, title: str, page_number: str) -> str:
    return (
        f'<tr><td><a href="#x">{item}</a></td><td><span>{title}</span></td>'
        f"<td><span>{page_number}</span></td></tr>"
    )


def test_table_of_contents_duplicates_keep_the_body_occurrence() -> None:
    html = page(
        para("NVIDIA CORPORATION")
        + "<table>"
        + toc_row("Item 1A.", "Risk Factors", "12")
        + toc_row("Item 7.", "Management's Discussion", "30")
        + "</table>"
        + bold("Item 1A. Risk Factors")
        + para("Demand for our products may fall.")
        + bold("Item 7. Management's Discussion")
        + para("Revenue grew in the quarter.")
    )
    document = parse(html)
    assert headings(document) == [
        "Cover page",
        "Item 1A. Risk Factors",
        "Item 7. Management's Discussion",
    ]
    assert document.sections[1].text == "Demand for our products may fall."
    assert "Item 1A. Risk Factors 12" in document.sections[0].text


def test_repeated_item_keeps_the_occurrence_with_the_most_text() -> None:
    html = page(
        bold("Item 1A. Risk Factors")
        + para("See below.")
        + bold("Item 1A. Risk Factors")
        + para("Demand for our products may fall sharply in a downturn.")
    )
    document = parse(html)
    assert headings(document) == ["Item 1A. Risk Factors"]
    assert document.sections[0].text == "Demand for our products may fall sharply in a downturn."


def test_table_is_rendered_one_line_per_row() -> None:
    html = page(
        bold("Item 7. Results")
        + "<table>"
        + "<tr><td><span>Revenue</span></td><td></td><td>$</td><td>46,743</td>"
        + "<td>&#160;</td><td>(1,234</td><td>)</td><td>56</td><td>%</td></tr>"
        + "<tr><td><span>Data&#160;Center</span></td><td>$</td><td>41,096</td></tr>"
        + "</table>"
    )
    document = parse(html)
    assert document.sections[0].text == "Revenue $46,743 (1,234) 56%\nData Center $41,096"


def test_hidden_elements_scripts_and_styles_are_dropped_but_tagged_values_kept() -> None:
    html = page(
        bold("Item 2. Discussion")
        + '<div style="DISPLAY: none">secret hidden text</div>'
        + "<script>var x = 'script text';</script><style>.a{color:red}</style>"
        + '<div><span>Revenue was <ix:nonFraction name="us-gaap:Revenues" contextRef="c-1">'
        + "46.7</ix:nonFraction> billion, <ix:nonNumeric name='x'>up 56%</ix:nonNumeric>."
        + "</span></div>",
        document_type="10-K",
    )
    document = parse(html)
    assert document.sections[0].text == "Revenue was 46.7 billion, up 56%."
    for gone in ("secret", "script text", "color:red", "ix:header", "10-K"):
        assert gone not in document.text


def test_no_item_heading_falls_back_to_full_document() -> None:
    document = parse(page(para("An exhibit without Items.") + para("Second paragraph.")))
    assert headings(document) == ["Full document"]
    assert document.text == "Full document\nAn exhibit without Items.\nSecond paragraph."


def test_quarterly_part_one_and_part_two_item_one_are_kept_apart() -> None:
    html = page(
        bold("PART I. FINANCIAL INFORMATION")
        + bold("Item 1. Financial Statements")
        + para("Balance sheet text.")
        + bold("PART II. OTHER INFORMATION")
        + bold("Item 1. Legal Proceedings")
        + para("Litigation text."),
        document_type="10-Q",
    )
    document = parse(html)
    assert headings(document) == [
        "Part I, Item 1. Financial Statements",
        "Part II, Item 1. Legal Proceedings",
    ]
    assert [s.text for s in document.sections] == ["Balance sheet text.", "Litigation text."]


def test_item_title_on_its_own_line_is_joined_to_the_heading() -> None:
    html = page(bold("ITEM 1A.") + bold("RISK FACTORS") + para("Demand may fall."))
    assert headings(parse(html)) == ["Item 1A. RISK FACTORS"]


def test_bold_sub_heading_starts_a_sub_section() -> None:
    html = page(
        bold("Item 7. Management's Discussion")
        + para("Overview text.")
        + bold("Revenue by Segment")
        + para("Compute grew.")
        + para("Networking grew.")
        + bold("This bold sentence ends with a full stop.")
        + para("Not a sub-heading.")
    )
    document = parse(html)
    assert headings(document) == [
        "Item 7. Management's Discussion",
        "Item 7. Management's Discussion › Revenue by Segment",
    ]
    assert document.sections[1].text == (
        "Compute grew.\nNetworking grew.\nThis bold sentence ends with a full stop.\n"
        "Not a sub-heading."
    )


def test_cover_page_page_numbers_and_contents_links_are_handled() -> None:
    html = page(
        para("UNITED STATES SECURITIES AND EXCHANGE COMMISSION")
        + bold("Item 1. Business")
        + para("We design chips.")
        + para("12")
        + '<div><a href="#toc">Table of Contents</a></div>'
        + para("We sell systems.")
    )
    document = parse(html)
    assert document.text == (
        "Cover page\nUNITED STATES SECURITIES AND EXCHANGE COMMISSION\n\n"
        "Item 1. Business\nWe design chips.\nWe sell systems."
    )


def test_whitespace_and_non_breaking_spaces_collapse_inside_a_line() -> None:
    html = page(
        bold("Item 2.&#160;&#160;Properties")
        + "<div><span>Santa\n  Clara,&#160;</span><span>California</span></div>"
    )
    document = parse(html)
    assert document.text == "Item 2. Properties\nSanta Clara, California"


def test_running_headers_and_parentheticals_are_not_sub_headings() -> None:
    running = bold("Notes to Consolidated Financial Statements") + bold("(Unaudited)")
    html = page(
        bold("Item 8. Financial Statements")
        + "".join(running + para(f"Note {n} text.") for n in range(1, 5))
        + bold("Risks Related to Our Industry")
        + bold("Failure to meet the evolving needs of our industry may harm our business.")
        + para("Our industry changes quickly.")
    )
    assert headings(parse(html)) == [
        "Item 8. Financial Statements",
        "Item 8. Financial Statements › Risks Related to Our Industry",
    ]
