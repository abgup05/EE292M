"""A company's 8-Ks since its annual report: listed from the index, some of them read.

One job: turn EDGAR's list of current reports into the timeline a run (or the
``events`` route and command) records. Every 8-K filed after the newest annual
report is listed from the filing index; the documents of those the rule picks
(:func:`app.core.events.choose_reads`: every 8-K after the newest periodic
report, and those of a substantive category since the annual report, newest
first, at most :data:`~app.core.limits.MAX_EVENTS_READ`) are read through the
:class:`~app.store.FilingCache`, keyed by accession and the 8-K splitter's own
version, and split into items. A document that cannot be fetched or split is a
reason on its event, never an error of the run; the counts say how many of each.

Also here: the item sections offered to a claim (:func:`event_passages`), which
are sources of the run only when one is offered.
"""

from __future__ import annotations

import dataclasses
import logging
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from datetime import UTC, date, datetime
from typing import Final

from app.core import events as rules
from app.core import limits
from app.core.documents import Document, FilingRef, Passage
from app.core.event_models import AsOf, Event, EventCounts, EventItem, EventStatus
from app.core.models import Company, ExtractionStatus, Source, SourceKind
from app.core.ports import FilingSource, SourceError
from app.retrieval.chunk import chunk_document
from app.services.ingest import cached_document, remember_document
from app.sources.current_report import parse_current_report, parser_version
from app.store import FilingCache

log = logging.getLogger(__name__)
SPLITTER_VERSION: Final = parser_version()
NO_ANNUAL = "no annual report was read, so there is no date to list 8-Ks after"
NO_TEXT = "No readable text extracted"


@dataclass
class Timeline:
    """The events listed, the documents read (by event id), the counts and any index error."""

    events: list[Event] = field(default_factory=list)
    documents: dict[str, Document] = field(default_factory=dict)
    counts: EventCounts = field(default_factory=EventCounts)
    annual_filed: str | None = None
    index_error: str = ""

    def read_filings(self) -> list[tuple[str, str, str]]:
        """Each 8-K read, as (form, filing date, URL), for the as-of block."""
        return [(e.form, e.filed_date, e.url) for e in self.events if e.status == EventStatus.read]


def event_title(company: Company, ref: FilingRef) -> str:
    """The title an 8-K is shown under: "NVIDIA CORP 8-K, filed 2026-11-12"."""
    return f"{company.name} {ref.form}, filed {ref.filed_date}"


def _event(ref: FilingRef) -> Event:
    items = [rules.describe_item(number) for number in ref.items]
    categories = rules.event_categories(ref.items)
    return Event(
        id=f"ev-{ref.accession}",
        form=ref.form,
        accession=ref.accession,
        filed_date=ref.filed_date,
        event_date=ref.period_end,
        filed_label=rules.day_label(ref.filed_date),
        url=ref.url,
        items=items,
        categories=[category.value for category in categories],
        substantive=rules.is_substantive(categories),
    )


def _read_document(
    ref: FilingRef, title: str, filings: FilingSource, cache: FilingCache
) -> tuple[Document | None, str]:
    """The 8-K split into items, from the cache or EDGAR; or None and the reason it was not."""
    cached = cached_document(cache, ref, title, SPLITTER_VERSION)
    if cached is not None:
        return cached[0], ""
    try:
        fetched = filings.fetch(ref)
    except SourceError as exc:
        return None, str(exc)
    try:
        document = parse_current_report(
            fetched.html, url=ref.url, title=title, published_date=ref.filed_date
        )
    except Exception as exc:  # noqa: BLE001 - one unreadable 8-K must not end the run
        log.exception("Splitting %s failed", ref.url)
        return None, f"The document could not be split ({type(exc).__name__})"
    if not document.text.strip():
        return None, NO_TEXT
    cache.put_text(document.content_hash, document.text)
    remember_document(cache, ref, document, fetched.retrieved_at, SPLITTER_VERSION)
    return document, ""


def apply_document(item_event: Event, document: Document) -> None:
    """Fill an event's items from its split document: found, locator, opening, roles.

    When the index listed no item for the 8-K, the items are those the document heads.
    """
    sections = rules.item_sections(document)
    if not item_event.items:
        item_event.items = [rules.describe_item(number) for number in sections]
        categories = rules.event_categories(sections)
        item_event.categories = [category.value for category in categories]
        item_event.substantive = rules.is_substantive(categories)
    for item in item_event.items:
        section = sections.get(item.number)
        if section is None:
            continue
        item.found = True
        item.locator = section.heading
        item.opening = rules.opening_sentences(section.text)
        if item.category == rules.Category.leadership.value:
            item.roles = rules.officer_roles(section.text)
    item_event.content_hash = document.content_hash


def read_timeline(
    company: Company,
    filings: FilingSource,
    cache: FilingCache,
    *,
    annual_filed: str | None,
    periodic_filed: str | None,
    out_of_time: Callable[[], bool] = lambda: False,
    cap: int = limits.MAX_EVENTS_READ,
) -> Timeline:
    """List the 8-Ks filed after ``annual_filed`` and read the ones the rule picks.

    ``periodic_filed`` is the filing date of the newest periodic report read. The
    index failing, or no annual report, gives an empty timeline with the reason in
    ``index_error``; a document that cannot be read gives its event status
    ``failed`` and a reason. Once ``out_of_time`` says so, no more are read.
    """
    timeline = Timeline(annual_filed=annual_filed)
    if not annual_filed:
        timeline.index_error = NO_ANNUAL
        timeline.counts = rules.count_events([], cap, annual_filed)
        return timeline
    try:
        refs = filings.current_reports(company, annual_filed)
    except SourceError as exc:
        timeline.index_error = str(exc)
        timeline.counts = rules.count_events([], cap, annual_filed)
        return timeline
    by_id = {f"ev-{ref.accession}": ref for ref in refs}
    timeline.events = [_event(ref) for ref in refs]
    wanted = rules.choose_reads(timeline.events, periodic_filed or annual_filed, cap)
    for item_event in wanted:
        if out_of_time():
            item_event.status = EventStatus.out_of_time
            continue
        ref = by_id[item_event.id]
        document, reason = _read_document(ref, event_title(company, ref), filings, cache)
        if document is None:
            item_event.status = EventStatus.failed
            item_event.reason = reason
            continue
        item_event.status = EventStatus.read
        apply_document(item_event, document)
        timeline.documents[item_event.id] = document
    timeline.counts = rules.count_events(timeline.events, cap, annual_filed)
    return timeline


def as_of(
    timeline: Timeline,
    filings_read: Sequence[tuple[str, str, str]],
    started: date,
    *,
    in_run: bool = True,
) -> AsOf:
    """The as-of block: the periodic reports read (form, date, URL) and the 8-Ks read."""
    return rules.build_as_of(
        filings=[*filings_read, *timeline.read_filings()],
        annual_filed=timeline.annual_filed,
        started=started,
        counts=timeline.counts,
        index_error=timeline.index_error,
        in_run=in_run,
    )


def event_source(source_id: str, item_event: Event, company: Company, ref_url: str) -> Source:
    """The run source of an 8-K one of whose sections is offered to a claim."""
    return Source(
        id=source_id,
        kind=SourceKind.sec_filing,
        title=f"{company.name} {item_event.form}, filed {item_event.filed_date}",
        publisher="SEC EDGAR",
        url=ref_url,
        requested_url=ref_url,
        form=item_event.form,
        accession=item_event.accession,
        period_end=None,
        published_date=item_event.filed_date,
        retrieved_at=datetime.now(UTC),
        content_hash=item_event.content_hash,
        extraction_status=ExtractionStatus.extracted,
    )


def event_passages(
    pinned: Sequence[tuple[Event, EventItem]],
    documents: dict[str, Document],
    source_ids: dict[str, str],
) -> list[Passage]:
    """The first passage of each pinned item's section, marked with its form and filing date.

    ``source_ids`` maps an event id to the run source id its passages carry. A passage
    is an exact slice of the stored 8-K, as every passage is.
    """
    passages: list[Passage] = []
    for item_event, item in pinned:
        source_id = source_ids[item_event.id]
        chunks = chunk_document(source_id, documents[item_event.id])
        first = next((p for p in chunks if p.locator == item.locator), None)
        if first is None:
            continue
        passages.append(
            dataclasses.replace(first, form=item_event.form, filed=item_event.filed_date)
        )
    return passages


def company_events(
    company: Company,
    filings: FilingSource,
    cache: FilingCache,
    *,
    today: date | None = None,
) -> tuple[Timeline, AsOf]:
    """A company's timeline outside a run: after its newest 10-K, read by the run's rule.

    The newest annual and periodic report come from the same selection a run makes
    (:meth:`~app.core.ports.FilingSource.periodic_filings`); their dates anchor the
    list, and they are not read. Raises :class:`SourceError` when EDGAR cannot list
    the company's periodic reports.
    """
    refs = filings.periodic_filings(company, limits.MAX_FILINGS)
    annual = next((ref for ref in refs if ref.form == "10-K"), None)
    periodic = refs[0] if refs else None
    timeline = read_timeline(
        company,
        filings,
        cache,
        annual_filed=annual.filed_date if annual else None,
        periodic_filed=periodic.filed_date if periodic else None,
    )
    listed = [(ref.form, ref.filed_date, ref.url) for ref in refs]
    return timeline, as_of(timeline, listed, today or datetime.now(UTC).date(), in_run=False)
