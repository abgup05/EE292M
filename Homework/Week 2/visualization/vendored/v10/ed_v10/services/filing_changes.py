"""What changed between a company's two latest filings of one form (milestone 6).

One use case: pick the latest filing of the form and the one before it, read each
through the :class:`~app.store.FilingCache` exactly as a thesis run does (a filing
this parser already read is rebuilt from the cache and not fetched), parse it, and
compare the two with :func:`app.core.filing_diff.diff_documents`. The command line
(``app.changes``) and, later, an API route call it.

Reading reuses :func:`app.services.ingest._read_filing` (the cache lookup, the
fetch, the parse and the cache index) rather than repeating it; ingest stores a
filing's text right after that call, and so does :func:`filing_changes`.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

from ed_v10.core import limits
from ed_v10.core.change_models import FilingChanges, FilingSide
from ed_v10.core.documents import Document, FetchedFiling, FilingRef
from ed_v10.core.filing_diff import MAX_LISTED, diff_documents, totals
from ed_v10.core.models import Company
from ed_v10.core.ports import SourceError
from ed_v10.services.ingest import _read_filing
from ed_v10.sources.filing import item_coverage
from ed_v10.store import FilingCache

FORMS = ("10-K", "10-Q")
COVERAGE_NOTE = (
    "Item headings were not found for most of {title}; its changes are grouped under "
    "unnumbered text."
)
IDENTICAL_NOTE = "The two filings have identical extracted text."


class FormFilingSource(Protocol):
    """What this use case needs from SEC EDGAR (:class:`app.sources.edgar.EdgarClient` has it)."""

    def company(self, ticker: str) -> Company:
        """Resolve a ticker. Raises UnknownTicker or SourceError."""
        ...

    def filings_of_form(self, company: Company, form: str, limit: int) -> list[FilingRef]:
        """The newest ``limit`` filings of ``form``, newest first; fewer than two: SourceError."""
        ...

    def fetch(self, ref: FilingRef) -> FetchedFiling:
        """Retrieve a filing's primary document. Raises SourceError."""
        ...


def _read(
    label: str, ref: FilingRef, company: Company, filings: FormFilingSource, cache: FilingCache
) -> Document:
    """One filing as stored text and sections, from the cache or EDGAR; SourceError if unread."""
    source, document, _ = _read_filing(label, ref, company, filings, cache)  # type: ignore[arg-type]
    if document is None:
        raise SourceError(f"{source.title} could not be read: {source.error}")
    cache.put_text(document.content_hash, document.text)
    return document


def _side(ref: FilingRef, document: Document) -> FilingSide:
    return FilingSide(
        form=ref.form,
        period_end=ref.period_end,
        filed_date=ref.filed_date,
        accession=ref.accession,
        url=ref.url,
        title=document.title,
        item_coverage=round(item_coverage(document), 4),
    )


@dataclass(frozen=True)
class FilingPair:
    """The two filings to compare, read and parsed: the earlier and the later."""

    company: Company
    earlier_ref: FilingRef
    later_ref: FilingRef
    earlier: Document
    later: Document


def read_filing_pair(
    company_or_ticker: Company | str,
    form: str,
    *,
    filings: FormFilingSource,
    cache: FilingCache | None = None,
) -> FilingPair:
    """Select the company's latest ``form`` filing and the one before it, and read both.

    ``form`` is "10-K" or "10-Q"; anything else is ValueError. With no ``cache``, a
    cache in memory serves this call only. Raises UnknownTicker for an unknown
    ticker and SourceError when EDGAR cannot be read, the company has fewer than
    two filings of the form, or either filing cannot be fetched.
    """
    if form not in FORMS:
        raise ValueError(f"form must be 10-K or 10-Q, not {form!r}")
    company = (
        company_or_ticker
        if isinstance(company_or_ticker, Company)
        else filings.company(company_or_ticker)
    )
    later_ref, earlier_ref = filings.filings_of_form(company, form, 2)[:2]
    own_cache = cache is None
    store = FilingCache() if cache is None else cache
    try:
        return read_pair(company, earlier_ref, later_ref, filings=filings, cache=store)
    finally:
        if own_cache:
            store.close()


def read_pair(
    company: Company,
    earlier_ref: FilingRef,
    later_ref: FilingRef,
    *,
    filings: FormFilingSource,
    cache: FilingCache,
) -> FilingPair:
    """Read two given filings through ``cache`` (later first), as :func:`read_filing_pair` does.

    For a caller that has already chosen the pair. Raises SourceError when either
    filing cannot be read.
    """
    later = _read("later", later_ref, company, filings, cache)
    earlier = _read("earlier", earlier_ref, company, filings, cache)
    return FilingPair(company, earlier_ref, later_ref, earlier, later)


def compare_pair(
    pair: FilingPair, *, exhaustive: bool = False, max_listed: int | None = MAX_LISTED
) -> FilingChanges:
    """What changed from ``pair.earlier`` to ``pair.later``, with the notes a reader needs.

    ``exhaustive`` and ``max_listed`` (None lists every changed paragraph) are passed to
    :func:`~app.core.filing_diff.diff_documents`.
    """
    items = diff_documents(
        pair.earlier,
        pair.later,
        earlier_url=pair.earlier_ref.url,
        later_url=pair.later_ref.url,
        exhaustive=exhaustive,
        max_listed=max_listed,
    )
    sides = (_side(pair.earlier_ref, pair.earlier), _side(pair.later_ref, pair.later))
    notes = [
        COVERAGE_NOTE.format(title=side.title)
        for side in sides
        if side.item_coverage < limits.MIN_ITEM_COVERAGE
    ]
    if pair.earlier.content_hash == pair.later.content_hash:
        notes.append(IDENTICAL_NOTE)
    return FilingChanges(
        company=pair.company,
        earlier=sides[0],
        later=sides[1],
        items=items,
        totals=totals(items),
        notes=notes,
    )


def filing_changes(
    company_or_ticker: Company | str,
    form: str,
    *,
    filings: FormFilingSource,
    cache: FilingCache | None = None,
) -> FilingChanges:
    """Compare the company's latest ``form`` filing with the one before it.

    ``form`` is "10-K" (annual against the previous annual) or "10-Q" (quarterly
    against the previous quarterly). Raises as :func:`read_filing_pair` does.
    """
    return compare_pair(read_filing_pair(company_or_ticker, form, filings=filings, cache=cache))
