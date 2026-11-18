"""Turn a request into stored documents: filings from EDGAR, plus any extra pages.

One job: select, retrieve, parse, deduplicate and record sources. Every source
adapter returns the shared :class:`~app.core.documents.Document`, so nothing
after this module knows which adapter a document came from. A source that
cannot be read is recorded with its error and never ends the run.

Every document's text goes into the :class:`~app.store.FilingCache` once, keyed
by its content hash. A filing already parsed by this exact parser
(:data:`PARSER_VERSION`) is rebuilt from the cache and not fetched again; a
change to the parser's source file changes the version, so stale text is never
quoted. Public pages are always fetched: unlike a filing, a page can change.
"""

from __future__ import annotations

import hashlib
import logging
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Final

import bs4

from app.core import limits
from app.core.documents import Document, FilingRef, Section
from app.core.models import Company, ExtractionStatus, Run, Source, SourceKind
from app.core.ports import FilingSource, PageFetcher, SourceError
from app.sources import filing as filing_parser
from app.sources.filing import item_coverage, parse_filing
from app.sources.http import FetchError
from app.sources.urls import canonicalize
from app.sources.web import extract_document
from app.store import FilingCache, Store

log = logging.getLogger(__name__)
ITEM_COVERAGE_NOTE = (
    "Item headings were not found for most of {title}; its passages are located by "
    "sub-heading only."
)
CACHE_NOTE = (
    "{cached} of {total} filings were read from the local cache; for those, EDGAR was asked "
    "only for the filing list."
)


def parser_version() -> str:
    """The parser's identity: SHA-256 of ``sources/filing.py`` and the BeautifulSoup version.

    Any edit to the parser, or a new HTML library, gives a new version, and a
    filing cached under an older one is fetched and parsed again.
    """
    source = Path(filing_parser.__file__).read_bytes()
    return f"{hashlib.sha256(source).hexdigest()[:16]}-bs4-{bs4.__version__}"


PARSER_VERSION: Final = parser_version()


@dataclass
class Ingested:
    """What was read.

    ``documents`` maps source ID to its stored document. ``requested`` counts
    every source asked for (the filings requested when the index could not be
    read); ``duplicates`` counts sources whose content had already been read,
    so ``requested - duplicates`` is the number of distinct sources asked for.
    ``filing_refs`` maps the source ID of each filing read to its reference.
    ``filing_html`` holds, by accession, the HTML of each filing fetched in this run (a
    filing read from the cache was not fetched and has none): the tags are in the HTML and
    not in the parsed text, and fetching a filing twice in one run is waste. The run reads
    the tags it wants and clears it (megabytes).
    """

    documents: dict[str, Document] = field(default_factory=dict)
    filing_refs: dict[str, FilingRef] = field(default_factory=dict)
    filing_html: dict[str, str] = field(default_factory=dict)
    requested: int = 0
    duplicates: int = 0
    time_limit_hit: bool = False
    filings_from_cache: int = 0

    @property
    def distinct_requested(self) -> int:
        """Sources asked for, counting identical content once."""
        return self.requested - self.duplicates


def _failed(
    source_id: str,
    kind: SourceKind,
    url: str,
    title: str,
    error: str,
    ref: FilingRef | None = None,
) -> Source:
    """A source record for something that was not read, keeping the filing's identity."""
    return Source(
        id=source_id,
        kind=kind,
        title=title,
        publisher="SEC EDGAR" if kind == SourceKind.sec_filing else "",
        url=url,
        requested_url=url,
        form=ref.form if ref else None,
        accession=ref.accession if ref else None,
        period_end=ref.period_end if ref else None,
        published_date=ref.filed_date if ref else None,
        retrieved_at=datetime.now(UTC),
        content_hash="",
        extraction_status=ExtractionStatus.failed,
        error=error,
    )


def _unparsable(exc: Exception) -> str:
    """The error recorded for a document the parser could not handle (type name only)."""
    return f"The document could not be parsed ({type(exc).__name__})"


def filing_title(company: Company, ref: FilingRef) -> str:
    """The title a filing is shown under, such as "NVIDIA CORP 10-Q, period ended 2026-07-26"."""
    return f"{company.name} {ref.form}, period ended {ref.period_end}"


def _select_filings(run: Run, company: Company, filings: FilingSource) -> list[FilingRef] | None:
    """The filings to read, or None when the index could not be read (recorded in errors)."""
    as_of = run.inputs.as_of
    try:
        if as_of is None:
            refs = filings.periodic_filings(company, run.inputs.filings)
        else:
            refs = filings.periodic_filings(company, run.inputs.filings, as_of=as_of.isoformat())
    except SourceError as exc:
        run.errors.append(f"The filing index could not be read: {exc}")
        return None
    if len(refs) < run.inputs.filings:
        span = (
            "the latest annual report and the quarterly reports filed after it"
            if as_of is None
            else (
                f"the newest annual report filed by {as_of.isoformat()} and the quarterly "
                "reports filed after it up to that date"
            )
        )
        run.coverage_limits.append(
            f"{run.inputs.filings} filing(s) were requested; EDGAR lists {len(refs)} ({span})."
        )
    return refs


def ingest(
    run: Run,
    company: Company,
    store: Store,
    *,
    filings: FilingSource,
    fetch_page: PageFetcher,
    out_of_time: Callable[[], bool],
    cache: FilingCache,
) -> Ingested:
    """Read every requested source, keep its text in ``cache`` and record it on ``run``.

    Filings come first, newest first, then the extra URLs in the order given; a
    filing already in ``cache`` for this parser is not fetched. Stops fetching
    when ``out_of_time`` says the run's time limit has passed. ``store`` keeps
    the run's progress.
    """
    selected = _select_filings(run, company, filings)
    refs = selected or []
    extra = list(run.inputs.extra_urls)
    # An unreadable index still counts the filings asked for, so the denominator is honest.
    filings_requested = run.inputs.filings if selected is None else len(refs)
    result = Ingested(requested=filings_requested + len(extra))
    if not refs and not extra:
        return result

    hashes: dict[str, str] = {}
    canonical_seen: dict[str, str] = {}
    pending: list[tuple[str, FilingRef | str]] = [
        (f"s{position}", item) for position, item in enumerate([*refs, *extra], start=1)
    ]
    for done, (source_id, item) in enumerate(pending):
        if out_of_time():
            result.time_limit_hit = True
            run.coverage_limits.append(
                f"The run time limit was reached; {len(pending) - done} source(s) were not fetched."
            )
            break
        run.stage_detail = f"source {done + 1} of {len(pending)}"
        store.save_run(run)
        same_page = False
        if isinstance(item, FilingRef):
            source, document, cached = _read_filing(
                source_id, item, company, filings, cache, keep_html=result.filing_html
            )
            result.filings_from_cache += cached
        else:
            source, document, same_page = _read_page(source_id, item, fetch_page, canonical_seen)
        if same_page:
            result.duplicates += 1
        elif document is not None and document.content_hash in hashes:
            source = source.model_copy(
                update={
                    "extraction_status": ExtractionStatus.failed,
                    "error": f"Duplicate of {hashes[document.content_hash]} (identical content)",
                }
            )
            document = None
            result.duplicates += 1
        run.sources.append(source)
        if document is not None and isinstance(item, FilingRef):
            coverage = source.item_coverage
            if coverage is not None and coverage < limits.MIN_ITEM_COVERAGE:
                run.coverage_limits.append(ITEM_COVERAGE_NOTE.format(title=source.title))
        if document is not None:
            hashes[document.content_hash] = source_id
            result.documents[source_id] = document
            if isinstance(item, FilingRef):
                result.filing_refs[source_id] = item
            cache.put_text(document.content_hash, document.text)
        store.save_run(run)
    if result.filings_from_cache:
        run.coverage_limits.append(
            CACHE_NOTE.format(cached=result.filings_from_cache, total=len(refs))
        )
    return result


def _section_spans(document: Document) -> list[tuple[str, int, int]] | None:
    """Each section as (heading, start, length) in the document text; None if one is not found.

    Every section is an exact substring of the text, in order; a section is
    searched for under its own heading, so a repeated passage is placed right.
    """
    spans: list[tuple[str, int, int]] = []
    cursor = 0
    for section in document.sections:
        found = document.text.find(f"{section.heading}\n{section.text}", cursor)
        if found < 0:
            return None
        start = found + len(section.heading) + 1
        spans.append((section.heading, start, len(section.text)))
        cursor = start + len(section.text)
    return spans


def remember_document(
    cache: FilingCache, ref: FilingRef, document: Document, retrieved: datetime, version: str
) -> None:
    """Index a freshly parsed filing in ``cache`` under ``version`` (the caller stores its text).

    ``version`` names the parser that split it: :data:`PARSER_VERSION` for a periodic
    report, the 8-K splitter's own for a current report.
    """
    spans = _section_spans(document)
    if spans is None:
        log.warning("Filing %s: a section is not a substring of its text; not cached", ref.url)
        return
    cache.remember_filing(
        ref.accession,
        version,
        content_hash=document.content_hash,
        publisher=document.publisher,
        sections=spans,
        retrieved_at=retrieved,
    )


def _remember(cache: FilingCache, ref: FilingRef, document: Document, retrieved: datetime) -> None:
    """Index a freshly parsed periodic report in ``cache`` (its text is stored by the caller)."""
    remember_document(cache, ref, document, retrieved, PARSER_VERSION)


def _from_cache(cache: FilingCache, ref: FilingRef, title: str) -> tuple[Document, datetime] | None:
    """The periodic report as this parser read it before, and when; None if not cached."""
    return cached_document(cache, ref, title, PARSER_VERSION)


def cached_document(
    cache: FilingCache, ref: FilingRef, title: str, version: str
) -> tuple[Document, datetime] | None:
    """The filing as the parser ``version`` read it before, and when it was fetched.

    None when it is not cached, or when its index entry is but its text is not.
    """
    cached = cache.lookup_filing(ref.accession, version)
    if cached is None:
        return None
    text = cache.get_text(cached.content_hash)
    if text is None:
        log.info("Filing %s is indexed in the cache but its text is not; fetching it", ref.url)
        return None
    sections = [
        Section(heading=heading, text=text[start : start + length])
        for heading, start, length in cached.sections
    ]
    document = Document(
        url=ref.url,
        title=title,
        publisher=cached.publisher,
        published_date=ref.filed_date,
        text=text,
        content_hash=cached.content_hash,
        sections=sections,
    )
    return document, cached.retrieved_at


def _read_filing(
    source_id: str,
    ref: FilingRef,
    company: Company,
    filings: FilingSource,
    cache: FilingCache,
    *,
    keep_html: dict[str, str] | None = None,
) -> tuple[Source, Document | None, bool]:
    """Read one filing from the cache, else fetch and parse it.

    Returns (source record, document or None when it was not read, whether it
    came from the cache). When the filing is fetched and ``keep_html`` is given,
    its HTML is put there under its accession.
    """
    title = filing_title(company, ref)
    cached = _from_cache(cache, ref, title)
    if cached is not None:
        document, retrieved_at = cached
        return _filing_source(source_id, ref, title, document, retrieved_at), document, True
    try:
        fetched = filings.fetch(ref)
    except SourceError as exc:
        failed = _failed(source_id, SourceKind.sec_filing, ref.url, title, str(exc), ref)
        return failed, None, False
    if keep_html is not None:
        keep_html[ref.accession] = fetched.html
    try:
        document = parse_filing(
            fetched.html, url=ref.url, title=title, published_date=ref.filed_date
        )
    except Exception as exc:  # noqa: BLE001 - one unparsable filing must not end the run
        log.exception("Parsing %s failed", ref.url)
        error = _unparsable(exc)
        return _failed(source_id, SourceKind.sec_filing, ref.url, title, error, ref), None, False
    if not document.text.strip():
        error = "No readable text extracted"
        return _failed(source_id, SourceKind.sec_filing, ref.url, title, error, ref), None, False
    _remember(cache, ref, document, fetched.retrieved_at)
    return _filing_source(source_id, ref, title, document, fetched.retrieved_at), document, False


def _filing_source(
    source_id: str, ref: FilingRef, title: str, document: Document, retrieved_at: datetime
) -> Source:
    """The source record of a filing that was read; ``retrieved_at`` is when EDGAR sent it.

    It keeps the filing's Item coverage (:func:`~app.sources.filing.item_coverage`), which
    the run status reads.
    """
    return Source(
        id=source_id,
        kind=SourceKind.sec_filing,
        title=title,
        publisher=document.publisher,
        url=ref.url,
        requested_url=ref.url,
        form=ref.form,
        accession=ref.accession,
        period_end=ref.period_end,
        published_date=ref.filed_date,
        retrieved_at=retrieved_at,
        content_hash=document.content_hash,
        extraction_status=ExtractionStatus.extracted,
        sections=len(document.sections),
        characters=len(document.text),
        item_coverage=item_coverage(document),
    )


def _read_page(
    source_id: str,
    url: str,
    fetch_page: PageFetcher,
    canonical_seen: dict[str, str],
) -> tuple[Source, Document | None, bool]:
    """Fetch and extract one page: (source record, document or None, whether it duplicates one).

    A page whose final address was already read is a duplicate and is not extracted again.
    """
    try:
        page = fetch_page(url)
    except FetchError as exc:
        failed = _failed(source_id, SourceKind.public_html, canonicalize(url), "", str(exc))
        return failed, None, False
    canonical = canonicalize(page.final_url)
    if canonical in canonical_seen:
        error = f"Duplicate of {canonical_seen[canonical]} (same page)"
        return _failed(source_id, SourceKind.public_html, canonical, "", error), None, True
    canonical_seen[canonical] = source_id
    try:
        document = extract_document(canonical, page.html)
    except Exception as exc:  # noqa: BLE001 - one unparsable page must not end the run
        log.exception("Extracting %s failed", canonical)
        failed = _failed(source_id, SourceKind.public_html, canonical, "", _unparsable(exc))
        return failed, None, False
    if not document.text.strip():
        error = "No readable text extracted"
        return _failed(source_id, SourceKind.public_html, canonical, "", error), None, False
    source = Source(
        id=source_id,
        kind=SourceKind.public_html,
        title=document.title,
        publisher=document.publisher,
        url=canonical,
        requested_url=url,
        published_date=document.published_date,
        retrieved_at=page.retrieved_at,
        content_hash=document.content_hash,
        extraction_status=ExtractionStatus.extracted,
        sections=len(document.sections),
        characters=len(document.text),
    )
    return source, document, False
