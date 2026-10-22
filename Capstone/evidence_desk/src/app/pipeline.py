"""One bounded research run: plan, discover, retrieve, extract, synthesize, verify.

Every stage is injectable so tests run the real pipeline without a network.
The run leaves this module only after :func:`app.verify.verify_findings` has
checked each citation; the brief contains verified findings alone.
"""

from __future__ import annotations

import logging
import time
import uuid
from collections.abc import Callable
from datetime import UTC, datetime

from app.extract import ExtractedDocument, extract_document
from app.fetch import FetchedPage, FetchError, fetch_page
from app.models import (
    Brief,
    ExtractionStatus,
    ResearchRequest,
    Run,
    RunStatus,
    Source,
    Subquestion,
    SubquestionStatus,
)
from app.store import Store
from app.synthesize import Draft, ExtractiveSynthesizer, Synthesizer
from app.urls import canonicalize
from app.verify import verify_findings

RUN_TIME_LIMIT_SECONDS = 180.0
MAX_SEARCH_RESULTS = 30
MIN_COMPLETE_SOURCES = 6
MIN_FINDINGS = 3
MAX_FINDINGS = 8

Fetcher = Callable[[str], FetchedPage]
Searcher = Callable[[list[Subquestion], int], list[str]]
log = logging.getLogger(__name__)


def new_run(request: ResearchRequest) -> Run:
    """Create a running record with a fresh ID and UTC start time."""
    return Run(
        id=f"run-{uuid.uuid4().hex[:12]}",
        inputs=request,
        status=RunStatus.running,
        started_at=datetime.now(UTC),
    )


def execute_run(
    run: Run,
    store: Store,
    *,
    fetcher: Fetcher = fetch_page,
    synthesizer: Synthesizer | None = None,
    searcher: Searcher | None = None,
    clock: Callable[[], float] = time.monotonic,
) -> Run:
    """Execute ``run`` to completion, persisting progress, and return the final record."""
    synthesizer = synthesizer or ExtractiveSynthesizer()
    started = clock()
    run.synthesizer = synthesizer.name
    store.save_run(run)

    run.subquestions = _plan(run, synthesizer)
    store.save_run(run)

    candidates = _discover(run, searcher)
    documents = _retrieve(run, store, candidates, fetcher, clock, started)
    store.save_run(run)

    if not documents:
        run.errors.append("No source could be retrieved and extracted; no brief was produced.")
        return _finish(run, store, RunStatus.failed)

    draft = _synthesize(run, synthesizer, documents)
    result = verify_findings(draft.findings, draft.evidence, store.get_source_texts(run.id))
    run.findings = result.verified
    run.unsupported_findings = result.unsupported
    run.evidence = result.evidence
    run.errors.extend(f"Citation check: {problem}" for problem in result.problems)

    answered = draft.answered_subquestion_ids | {
        subquestion.id
        for subquestion in run.subquestions
        if subquestion.id in draft.answered_subquestion_ids
    }
    for subquestion in run.subquestions:
        subquestion.status = (
            SubquestionStatus.answered
            if subquestion.id in answered
            else SubquestionStatus.unanswered
        )
    status = _status(run, documents)
    run.brief = _brief(run, draft, status, documents)
    return _finish(run, store, status)


def _plan(run: Run, synthesizer: Synthesizer) -> list[Subquestion]:
    try:
        return synthesizer.plan(run.inputs)
    except Exception as exc:  # noqa: BLE001 - any backend failure falls back, and is recorded
        log.warning("planning with %s failed: %s", synthesizer.name, exc)
        run.errors.append(f"Planning with {synthesizer.name} failed ({exc}); used template plan.")
        return ExtractiveSynthesizer().plan(run.inputs)


def _discover(run: Run, searcher: Searcher | None) -> list[tuple[str, str]]:
    """Seed URLs first, then search results, canonicalized and deduplicated."""
    candidates: list[tuple[str, str]] = [(url, "seed") for url in run.inputs.seed_urls]
    if searcher is None:
        run.coverage_limits.append(
            "No search provider configured: only the supplied seed URLs were considered."
        )
    else:
        try:
            for url in searcher(run.subquestions, MAX_SEARCH_RESULTS):
                candidates.append((url, "search"))
        except Exception as exc:  # noqa: BLE001 - search failure limits coverage, never the run
            log.warning("search failed: %s", exc)
            run.coverage_limits.append(f"Search failed ({exc}); only seed URLs were considered.")
    seen: set[str] = set()
    unique: list[tuple[str, str]] = []
    for url, origin in candidates:
        key = canonicalize(url)
        if key not in seen:
            seen.add(key)
            unique.append((url, origin))
    return unique


def _retrieve(
    run: Run,
    store: Store,
    candidates: list[tuple[str, str]],
    fetcher: Fetcher,
    clock: Callable[[], float],
    started: float,
) -> dict[str, ExtractedDocument]:
    documents: dict[str, ExtractedDocument] = {}
    canonical_seen: dict[str, str] = {}
    hashes: dict[str, str] = {}
    for index, (url, origin) in enumerate(candidates, start=1):
        if len(documents) >= run.inputs.source_budget:
            run.coverage_limits.append(
                f"Source budget of {run.inputs.source_budget} reached; "
                f"{len(candidates) - index + 1} candidate page(s) were not fetched."
            )
            break
        if clock() - started > RUN_TIME_LIMIT_SECONDS:
            run.coverage_limits.append(
                f"Run time limit of {int(RUN_TIME_LIMIT_SECONDS)} s reached; "
                f"{len(candidates) - index + 1} candidate page(s) were not fetched."
            )
            break
        source_id = f"src-{index}"
        try:
            page = fetcher(url)
        except FetchError as exc:
            run.sources.append(_failed_source(source_id, url, origin, str(exc)))
            continue
        canonical = canonicalize(page.final_url)
        if canonical in canonical_seen:
            run.sources.append(
                _failed_source(
                    source_id, url, origin, f"Duplicate of {canonical_seen[canonical]} (same page)"
                )
            )
            continue
        document = extract_document(canonical, page.html)
        if not document.text.strip():
            run.sources.append(_failed_source(source_id, url, origin, "No readable text extracted"))
            continue
        if document.content_hash in hashes:
            run.sources.append(
                _failed_source(
                    source_id,
                    url,
                    origin,
                    f"Duplicate of {hashes[document.content_hash]} (identical content)",
                )
            )
            continue
        canonical_seen[canonical] = source_id
        hashes[document.content_hash] = source_id
        documents[source_id] = document
        store.save_source_text(run.id, source_id, document.text)
        run.sources.append(
            Source(
                id=source_id,
                canonical_url=canonical,
                requested_url=url,
                title=document.title,
                publisher=document.publisher,
                published_date=document.published_date,
                retrieved_at=page.retrieved_at,
                content_hash=document.content_hash,
                extraction_status=ExtractionStatus.extracted,
                origin=origin,
            )
        )
        store.save_run(run)
    return documents


def _failed_source(source_id: str, url: str, origin: str, error: str) -> Source:
    return Source(
        id=source_id,
        canonical_url=canonicalize(url),
        requested_url=url,
        title="",
        publisher="",
        retrieved_at=datetime.now(UTC),
        content_hash="",
        extraction_status=ExtractionStatus.failed,
        origin=origin,
        error=error,
    )


def _synthesize(
    run: Run, synthesizer: Synthesizer, documents: dict[str, ExtractedDocument]
) -> Draft:
    try:
        return synthesizer.synthesize(run.inputs, run.subquestions, documents)
    except Exception as exc:  # noqa: BLE001 - fall back to extractive and say so
        log.warning("synthesis with %s failed: %s", synthesizer.name, exc)
        run.errors.append(
            f"Synthesis with {synthesizer.name} failed ({exc}); used extractive fallback."
        )
        run.synthesizer = "extractive"
        return ExtractiveSynthesizer().synthesize(run.inputs, run.subquestions, documents)


def _status(run: Run, documents: dict[str, ExtractedDocument]) -> RunStatus:
    """Complete only when every acceptance condition holds; otherwise partial."""
    reasons: list[str] = []
    if len(documents) < MIN_COMPLETE_SOURCES:
        reasons.append(
            f"Fewer than six sources were extracted ({len(documents)}); the review is not complete."
        )
    if run.unsupported_findings:
        reasons.append(
            f"{len(run.unsupported_findings)} finding(s) lacked verified evidence and were "
            "withheld from the brief."
        )
    if not MIN_FINDINGS <= len(run.findings) <= MAX_FINDINGS:
        reasons.append(f"{len(run.findings)} verified finding(s); a complete brief has 3 to 8.")
    unanswered = [s.text for s in run.subquestions if s.status != SubquestionStatus.answered]
    if unanswered:
        reasons.append(f"{len(unanswered)} subquestion(s) remain unanswered.")
    run.coverage_limits.extend(reasons)
    return RunStatus.partial if reasons else RunStatus.complete


def _brief(
    run: Run, draft: Draft, status: RunStatus, documents: dict[str, ExtractedDocument]
) -> Brief:
    unknowns = list(draft.unknowns)
    unknowns.extend(
        f"Unanswered subquestion: {s.text}"
        for s in run.subquestions
        if s.status != SubquestionStatus.answered
        and not any(s.text in unknown for unknown in unknowns)
    )
    single = [f.id for f in run.findings if f.single_source]
    disagreements = list(draft.disagreements)
    next_steps = list(draft.next_steps)
    if single:
        next_steps.append(
            f"Seek a second independent source for single-source finding(s): {', '.join(single)}."
        )
    return Brief(
        direct_answer=draft.direct_answer,
        findings=run.findings,
        disagreements=disagreements,
        unknowns=unknowns,
        next_steps=next_steps,
        source_ids=list(documents.keys()),
        coverage_status=status,
    )


def _finish(run: Run, store: Store, status: RunStatus) -> Run:
    run.status = status
    run.finished_at = datetime.now(UTC)
    store.save_run(run)
    return run
