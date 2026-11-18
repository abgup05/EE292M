"""The breakdowns tagged in a company's latest annual or quarterly report.

One use case: select the company's latest filing of the form, fetch its primary
document, read its inline XBRL (:func:`app.sources.ixbrl.read_tagged_facts`)
and build the breakdowns (:func:`app.core.breakdowns.build_report`). The
filing cache is not used: it keeps a filing's parsed text, and the tagged
facts are only in the raw HTML, so the document is always fetched. The command
line (``app.breakdowns``) calls it.
"""

from __future__ import annotations

from typing import Protocol

from ed_v9.core.breakdown_models import BreakdownReport, FilingInfo
from ed_v9.core.breakdowns import build_report
from ed_v9.core.documents import FetchedFiling, FilingRef
from ed_v9.core.models import Company
from ed_v9.sources.ixbrl import read_tagged_facts

FORMS = ("10-K", "10-Q")


class BreakdownSource(Protocol):
    """What this use case needs from SEC EDGAR (:class:`app.sources.edgar.EdgarClient` has it)."""

    def company(self, ticker: str) -> Company:
        """Resolve a ticker. Raises UnknownTicker or SourceError."""
        ...

    def latest_of_form(self, company: Company, form: str) -> FilingRef:
        """The newest filing of exactly ``form``. Raises SourceError when there is none."""
        ...

    def fetch(self, ref: FilingRef) -> FetchedFiling:
        """Retrieve a filing's primary document. Raises SourceError."""
        ...


def filing_info(ref: FilingRef) -> FilingInfo:
    """The record's description of the filing ``ref`` names."""
    return FilingInfo(
        form=ref.form,
        period_end=ref.period_end,
        filed_date=ref.filed_date,
        accession=ref.accession,
        url=ref.url,
    )


def filing_breakdowns(
    company_or_ticker: Company | str, form: str, *, filings: BreakdownSource
) -> BreakdownReport:
    """The breakdowns tagged in the company's latest ``form`` filing.

    ``form`` is "10-K" or "10-Q"; anything else is ValueError. The filing is
    ``filings.latest_of_form(company, form)``, so a company's only filing of the
    form (its first annual report) is read too. Raises UnknownTicker for an
    unknown ticker and SourceError when EDGAR has no filing of the form or cannot
    list or deliver it.
    """
    if form not in FORMS:
        raise ValueError(f"form must be 10-K or 10-Q, not {form!r}")
    company = (
        company_or_ticker
        if isinstance(company_or_ticker, Company)
        else filings.company(company_or_ticker)
    )
    ref = filings.latest_of_form(company, form)
    fetched = filings.fetch(ref)
    return build_report(read_tagged_facts(fetched.html), company=company, filing=filing_info(ref))
