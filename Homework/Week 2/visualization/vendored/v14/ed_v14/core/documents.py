"""The shapes that cross the boundary between a source adapter and the pipeline.

Every adapter (SEC filing, public web page) returns a :class:`Document`. The
invariant all of them keep: ``Document.text`` is the exact text stored for
verification, and every ``Section.text`` is an exact substring of it.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime


@dataclass(frozen=True)
class Section:
    """Text under one heading; ``heading`` is the citation locator."""

    heading: str
    text: str


@dataclass(frozen=True)
class Document:
    """Stored source text plus the metadata the brief shows for it."""

    url: str
    title: str
    publisher: str
    published_date: str | None
    text: str
    content_hash: str
    sections: list[Section] = field(default_factory=list)


@dataclass(frozen=True)
class Passage:
    """A retrievable slice of one document.

    ``text`` is an exact substring of the document text and ``start`` is its
    offset there, so a quote taken from a passage can be verified against the
    stored source. ``form`` and ``filed`` are set only on a passage of a current
    report (8-K) offered to a claim beside the passages retrieved for it
    (:mod:`app.services.events`); every other passage leaves them empty.
    """

    id: str
    source_id: str
    locator: str
    text: str
    start: int
    form: str = ""
    filed: str = ""


@dataclass(frozen=True)
class FilingRef:
    """One filing in SEC EDGAR's index.

    ``period_end`` is the index's ``reportDate``: the end of a periodic report's
    period, or the date of the event a current report (8-K) reports. ``items`` are
    the 8-K item numbers the index lists for a current report ("5.02", "9.01"),
    in the index's order; empty for every other form.
    """

    cik: int
    accession: str
    form: str
    period_end: str
    filed_date: str
    primary_document: str
    url: str
    items: tuple[str, ...] = ()


@dataclass(frozen=True)
class FormListing:
    """A company's filings of one form, newest first, and how far the index was read.

    ``where`` names the part of EDGAR's index that was read ("EDGAR's recent index
    and the 2 newest of its 3 older index pages"). ``complete`` is True only when
    every page of the index was read: only then is a filing that is not in ``refs``
    one EDGAR does not list.
    """

    refs: list[FilingRef]
    where: str
    complete: bool


@dataclass(frozen=True)
class FetchedFiling:
    """The primary document of a filing as retrieved."""

    ref: FilingRef
    html: str
    retrieved_at: datetime
