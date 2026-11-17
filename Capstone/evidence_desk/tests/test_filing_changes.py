"""The filing-changes use case: select two filings, read them through the cache, diff them."""

from __future__ import annotations

from dataclasses import dataclass

import pytest

from app.core.documents import FilingRef
from app.core.models import Company
from app.core.ports import SourceError, UnknownTicker
from app.services.filing_changes import filing_changes
from app.store import FilingCache
from tests.fakes import NVIDIA, FakeFilings, synthetic_ref

KEEP = (
    "We depend on third-party foundries to manufacture our semiconductor wafers, and any "
    "disruption in their capacity could delay our product shipments to customers."
)
DROPPED = (
    "Export controls imposed by the United States government restrict sales of certain "
    "data center products to customers in China and other countries."
)
PLANTED = (
    "Climate disclosure rules adopted by European regulators will require additional "
    "reporting about greenhouse emissions throughout our supply chain."
)
BUSINESS = "We design accelerated computing platforms for data centers, gaming and automobiles."


def annual_report(*risks: str, business: str = BUSINESS) -> str:
    """A minimal 10-K primary document with Items 1 and 1A."""
    paragraphs = "".join(f"<p>{text}</p>" for text in risks)
    return (
        "<html><body><p>PART I</p><p><b>Item 1. Business</b></p>"
        f"<p>{business}</p><p><b>Item 1A. Risk Factors</b></p>{paragraphs}</body></html>"
    )


@dataclass
class FormFilings(FakeFilings):
    """FakeFilings that can also list the filings of one form, as EdgarClient does."""

    def filings_of_form(self, company: Company, form: str, limit: int) -> list[FilingRef]:
        """The configured refs of ``form``, newest first as given; fewer than two fails."""
        if self.index_error is not None:
            raise self.index_error
        refs = [ref for ref in self.refs if ref.form == form]
        if len(refs) < 2:
            raise SourceError(f"{company.name} has {len(refs)} {form} filing(s)")
        return refs[:limit]


LATER, EARLIER = synthetic_ref(2, "10-K"), synthetic_ref(1, "10-K")


def two_annual_reports(later_html: str | SourceError | None = None) -> FormFilings:
    later = annual_report(KEEP, PLANTED) if later_html is None else later_html
    return FormFilings(
        refs=[LATER, EARLIER],
        documents={LATER.url: later, EARLIER.url: annual_report(KEEP, DROPPED)},
    )


def test_two_annual_reports_are_compared_item_by_item() -> None:
    result = filing_changes("nvda", "10-K", filings=two_annual_reports())
    assert result.company == NVIDIA
    assert result.later.accession == LATER.accession
    assert result.earlier.accession == EARLIER.accession
    assert result.later.title == "NVIDIA CORP 10-K, period ended 2026-02-01"
    assert (result.later.form, result.later.period_end, result.later.filed_date) == (
        "10-K",
        "2026-02-01",
        "2026-02-15",
    )
    assert result.later.url == LATER.url and result.later.item_coverage == pytest.approx(1.0)
    assert [(item.item, item.present_in) for item in result.items] == [
        ("Item 1. Business", "both"),
        ("Item 1A. Risk Factors", "both"),
    ]
    risks = result.items[1]
    assert [p.text for p in risks.added_paragraphs] == [PLANTED]
    assert [p.text for p in risks.removed_paragraphs] == [DROPPED]
    assert risks.added_paragraphs[0].link.startswith(LATER.url + "#:~:text=")
    assert risks.removed_paragraphs[0].link.startswith(EARLIER.url + "#:~:text=")
    assert (result.totals.added, result.totals.removed, result.totals.unchanged) == (1, 1, 2)
    assert result.notes == []


def test_a_company_object_is_used_as_given() -> None:
    filings = two_annual_reports()
    filings.company_error = SourceError("the company list must not be asked for")
    assert filing_changes(NVIDIA, "10-K", filings=filings).company == NVIDIA


def test_each_listed_paragraph_is_a_span_of_the_cached_text_of_its_filing() -> None:
    cache = FilingCache()
    result = filing_changes("NVDA", "10-K", filings=two_annual_reports(), cache=cache)
    later_text = cache.get_text(cache.lookup_filing(LATER.accession, _version()).content_hash)
    added = result.items[1].added_paragraphs[0]
    assert later_text is not None
    assert later_text[added.start : added.start + len(added.text)] == added.text


def _version() -> str:
    from app.services.ingest import PARSER_VERSION

    return PARSER_VERSION


def test_a_second_comparison_reads_both_filings_from_the_cache() -> None:
    cache = FilingCache()
    filings = two_annual_reports()
    first = filing_changes("NVDA", "10-K", filings=filings, cache=cache)
    assert len(filings.fetched) == 2
    second = filing_changes("NVDA", "10-K", filings=filings, cache=cache)
    assert len(filings.fetched) == 2
    assert second == first


def test_a_company_with_one_filing_of_the_form_is_refused_with_the_reason() -> None:
    filings = FormFilings(refs=[LATER, synthetic_ref(3)], documents={})
    with pytest.raises(SourceError, match="has 1 10-K filing"):
        filing_changes("NVDA", "10-K", filings=filings)
    assert filings.fetched == []


def test_a_filing_that_cannot_be_fetched_is_a_source_error_naming_it() -> None:
    filings = two_annual_reports(SourceError("EDGAR answered HTTP 503 for the document"))
    with pytest.raises(SourceError) as raised:
        filing_changes("NVDA", "10-K", filings=filings)
    message = str(raised.value)
    assert "NVIDIA CORP 10-K, period ended 2026-02-01" in message
    assert "HTTP 503" in message


def test_an_unknown_ticker_is_refused() -> None:
    with pytest.raises(UnknownTicker):
        filing_changes("NOPE", "10-K", filings=two_annual_reports())


def test_only_annual_and_quarterly_reports_are_compared() -> None:
    with pytest.raises(ValueError, match="10-K or 10-Q"):
        filing_changes("NVDA", "8-K", filings=two_annual_reports())


def test_a_filing_mostly_outside_numbered_items_gets_a_note() -> None:
    unsegmented = f"<html><body><p>{KEEP}</p><p>{PLANTED}</p><p>{BUSINESS}</p></body></html>"
    result = filing_changes("NVDA", "10-K", filings=two_annual_reports(unsegmented))
    assert result.later.item_coverage == 0.0
    assert result.notes == [
        "Item headings were not found for most of NVIDIA CORP 10-K, period ended 2026-02-01; "
        "its changes are grouped under unnumbered text."
    ]
    assert [(item.item, item.present_in) for item in result.items] == [
        ("Item 1. Business", "earlier"),
        ("Item 1A. Risk Factors", "earlier"),
        ("Full document", "later"),
    ]
