"""Record types for the fact store and what is computed from dated facts.

Pure data. A :class:`CompanyProfile` is what EDGAR's submissions index says about
a filer beside its filings (its industry code); a :class:`RestatementLedger` is
computed by :mod:`app.core.restatements` from a :class:`app.core.facts.FactBook`
and returned by the API and ``make restatements``; a view only draws it.
"""

from __future__ import annotations

from pydantic import BaseModel, Field


class CompanyProfile(BaseModel):
    """A filer as EDGAR's submissions index describes it.

    ``sic`` is the four-digit Standard Industrial Classification code and
    ``sic_description`` its title ("3674", "Semiconductors & Related Devices"); both
    are empty when the index gives none.
    """

    cik: int
    ticker: str
    name: str
    sic: str = ""
    sic_description: str = ""


class StoredCompany(BaseModel):
    """One company in the fact store: who it is, how many facts are kept, and when loaded."""

    cik: int
    ticker: str
    name: str
    sic: str = ""
    sic_description: str = ""
    facts: int = 0
    skipped: int = 0
    payload_sha256: str = ""
    loaded_at: str = ""


class StoredFiling(BaseModel):
    """One filing some stored fact came from: accession, form and filing date."""

    accession: str
    form: str
    filed: str


class LedgerValue(BaseModel):
    """One value a filing gave a period, and how far it moved from the value before it.

    The first value of a period has no change (``change`` and ``change_percent`` None).
    ``change_percent`` is None when the value before it is zero. ``concept`` is the
    us-gaap concept the filing tagged it with.
    """

    value: float
    display: str
    accession: str
    form: str
    filed: str
    concept: str
    change: float | None = None
    change_display: str = ""
    change_percent: float | None = None
    change_percent_display: str = ""


class LedgerEntry(BaseModel):
    """One metric and period whose value differs between filings, oldest value first.

    ``period_label`` names the period ("Fiscal year ended 2024-01-28", "Quarter ended
    ...", "As of ..."); ``period`` is "annual", "quarter", "half_year", "nine_months",
    "instant" or "other". ``values[0]`` is the first value reported, each later item a
    value that differed from the one before it by more than the tolerance. ``reports``
    counts every report of the period, the unchanged ones included.
    """

    key: str
    label: str
    unit: str
    period: str
    start: str | None
    end: str
    period_label: str
    reports: int
    values: list[LedgerValue] = Field(default_factory=list)
    concept_changed: bool = False


class RestatementLedger(BaseModel):
    """Every metric and period of one company whose value differs between filings.

    ``tolerance_note`` states when two values count as the same; ``periods_checked``
    is the denominator (every period of every metric reported at least twice), and
    ``entries`` are those with a change, newest period first within each metric. ``as_of``
    is the date the ledger was computed as of (only facts filed by then), "" for all.
    """

    company: str
    cik: int
    ticker: str = ""
    as_of: str = ""
    tolerance_note: str
    metrics_checked: list[str] = Field(default_factory=list)
    periods_checked: int = 0
    periods_restated: int = 0
    entries: list[LedgerEntry] = Field(default_factory=list)
    notes: list[str] = Field(default_factory=list)
