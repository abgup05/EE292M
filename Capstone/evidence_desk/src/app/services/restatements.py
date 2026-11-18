"""A company's restatement ledger, outside a run: company facts in, the ledger out.

One job: read the company facts through the :class:`~app.core.ports.FilingSource`,
keep them in the fact store when one is given, and build the ledger with
:mod:`app.core.restatements`, as of a date when one is given.
"""

from __future__ import annotations

from datetime import UTC, date, datetime

from app.core.fact_models import RestatementLedger
from app.core.facts import FactBook, FactsError
from app.core.models import Company
from app.core.ports import FilingSource, SourceError
from app.core.restatements import build_ledger
from app.services.numbers import content_hash, keep_facts
from app.store import FactStore


def company_restatements(
    company: Company,
    filings: FilingSource,
    *,
    facts_store: FactStore | None = None,
    as_of: date | None = None,
) -> RestatementLedger:
    """The ledger of ``company``, from facts filed by ``as_of`` (all when None).

    Raises :class:`SourceError` when EDGAR cannot give the facts or they are not
    the shape :class:`~app.core.facts.FactBook` reads.
    """
    payload = filings.company_facts(company)
    if facts_store is not None:
        error = keep_facts(
            facts_store, company, filings, payload, content_hash(payload), datetime.now(UTC)
        )
        if error is not None:
            raise SourceError(f"The facts could not be kept in the fact store ({error})")
    try:
        book = FactBook(payload, as_of=as_of)
    except FactsError as exc:
        raise SourceError(f"The XBRL company facts could not be read: {exc}") from exc
    return build_ledger(book, ticker=company.ticker)
