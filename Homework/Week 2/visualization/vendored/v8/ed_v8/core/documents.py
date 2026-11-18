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
    stored source.
    """

    id: str
    source_id: str
    locator: str
    text: str
    start: int


@dataclass(frozen=True)
class FilingRef:
    """One periodic report in SEC EDGAR's index."""

    cik: int
    accession: str
    form: str
    period_end: str
    filed_date: str
    primary_document: str
    url: str


@dataclass(frozen=True)
class FetchedFiling:
    """The primary document of a filing as retrieved."""

    ref: FilingRef
    html: str
    retrieved_at: datetime
