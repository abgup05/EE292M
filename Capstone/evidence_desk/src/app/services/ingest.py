"""Turn a request into stored documents: filings from EDGAR, plus any extra pages.

One job: select, retrieve, parse, deduplicate and record sources. Every source
adapter returns the shared :class:`~app.core.documents.Document`, so nothing
after this module knows which adapter a document came from. A source that
cannot be read is recorded with its error and never ends the run.
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime

from app.core.documents import Document, FilingRef
from app.core.models import Company, ExtractionStatus, Run, Source, SourceKind
from app.core.ports import FilingSource, PageFetcher, SourceError
from app.sources.filing import parse_filing
from app.sources.http import FetchError
from app.sources.urls import canonicalize
from app.sources.web import extract_document
from app.store import Store

log = logging.getLogger(__name__)


@dataclass
class Ingested:
    """What was read.

    ``documents`` maps source ID to its stored document. ``requested`` counts
    every source asked for (the filings requested when the index could not be
    read); ``duplicates`` counts sources whose content had already been read,
    so ``requested - duplicates`` is the number of distinct sources asked for.
    """

    documents: dict[str, Document] = field(default_factory=dict)
    requested: int = 0
    duplicates: int = 0
    time_limit_hit: bool = False

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
    try:
        refs = filings.periodic_filings(company, run.inputs.filings)
    except SourceError as exc:
        run.errors.append(f"The filing index could not be read: {exc}")
        return None
    if len(refs) < run.inputs.filings:
        run.coverage_limits.append(
            f"{run.inputs.filings} filing(s) were requested; EDGAR lists {len(refs)} "
            "(the latest annual report and the quarterly reports filed after it)."
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
) -> Ingested:
    """Read every requested source into the store and record it on ``run``.

    Filings come first, newest first, then the extra URLs in the order given.
    Stops fetching when ``out_of_time`` says the run's time limit has passed.
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
            source, document = _read_filing(source_id, item, company, filings)
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
        if document is not None:
            hashes[document.content_hash] = source_id
            result.documents[source_id] = document
            store.save_source_text(run.id, source_id, document.text)
        store.save_run(run)
    return result


def _read_filing(
    source_id: str, ref: FilingRef, company: Company, filings: FilingSource
) -> tuple[Source, Document | None]:
    """Fetch and parse one filing: (source record, document or None when it was not read)."""
    title = filing_title(company, ref)
    try:
        fetched = filings.fetch(ref)
    except SourceError as exc:
        return _failed(source_id, SourceKind.sec_filing, ref.url, title, str(exc), ref), None
    try:
        document = parse_filing(
            fetched.html, url=ref.url, title=title, published_date=ref.filed_date
        )
    except Exception as exc:  # noqa: BLE001 - one unparsable filing must not end the run
        log.exception("Parsing %s failed", ref.url)
        error = _unparsable(exc)
        return _failed(source_id, SourceKind.sec_filing, ref.url, title, error, ref), None
    if not document.text.strip():
        error = "No readable text extracted"
        return _failed(source_id, SourceKind.sec_filing, ref.url, title, error, ref), None
    source = Source(
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
        retrieved_at=fetched.retrieved_at,
        content_hash=document.content_hash,
        extraction_status=ExtractionStatus.extracted,
        sections=len(document.sections),
        characters=len(document.text),
    )
    return source, document


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
