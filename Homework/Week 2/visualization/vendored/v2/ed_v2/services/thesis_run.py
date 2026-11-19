"""One thesis run: resolve, read, plan, retrieve, assess, verify, decide.

This is the only place a run is advanced, and both entry points (the HTTP API
and the command line) call it. It depends on the ports in
:mod:`app.core.ports`, never on a concrete EDGAR client or engine. A run
leaves this module only after :func:`app.core.gate.gate_claim` has checked
every quote and :mod:`app.core.policy` has computed the verdicts and status.
"""

from __future__ import annotations

import logging
import time
import uuid
from collections.abc import Callable
from datetime import UTC, datetime

from ed_v2.core import limits, policy
from ed_v2.core.gate import RunIds, StoredSource, gate_claim
from ed_v2.core.models import (
    Brief,
    Claim,
    Coverage,
    ExtractionStatus,
    Run,
    RunStatus,
    ThesisRequest,
    Verdict,
)
from ed_v2.core.ports import Analyst, ClaimDraft, FilingSource, PageFetcher, SourceError
from ed_v2.engines.extractive import ExtractiveAnalyst
from ed_v2.engines.fallback import FallbackAnalyst
from ed_v2.retrieval.chunk import chunk_document
from ed_v2.retrieval.search import PassageIndex
from ed_v2.services.ingest import ingest
from ed_v2.sources.http import fetch_page as default_fetch_page
from ed_v2.store import Store

log = logging.getLogger(__name__)
MAX_UNKNOWNS = 12
NOT_ASSESSED_RATIONALE = "Not assessed: the run time limit was reached first."
NOT_ASSESSED_UNKNOWN = "Not assessed before the run time limit: {claim}"
NO_EVIDENCE_UNKNOWN = "No verified evidence was found for: {claim}"


def new_run(request: ThesisRequest) -> Run:
    """Create a running record with a fresh ID and UTC start time."""
    return Run(
        id=f"run-{uuid.uuid4().hex[:12]}",
        inputs=request,
        status=RunStatus.running,
        started_at=datetime.now(UTC),
    )


def fail_run(run: Run, store: Store, message: str) -> Run:
    """End ``run`` as failed, with the reason, the finish time and no brief."""
    run.errors.append(message)
    run.brief = None
    return _finish(run, store, RunStatus.failed)


def execute_run(
    run: Run,
    store: Store,
    *,
    filings: FilingSource,
    analyst: Analyst,
    fetch_page: PageFetcher = default_fetch_page,
    clock: Callable[[], float] = time.monotonic,
) -> Run:
    """Execute ``run`` to completion, persisting progress, and return the final record."""
    started = clock()

    def out_of_time() -> bool:
        return clock() - started > limits.RUN_TIME_LIMIT_SECONDS

    fallback_steps: list[str] = []

    def on_failure(step: str, exc: Exception) -> None:
        log.warning("%s engine failed during %s: %s", analyst.name, step, _safe(exc))
        fallback_steps.append(step)
        run.errors.append(
            f"The {analyst.name} engine failed during {step} ({_safe(exc)}); "
            "the deterministic engine was used for that step."
        )

    deterministic = ExtractiveAnalyst()
    engine: Analyst = (
        analyst
        if analyst.name == deterministic.name
        else FallbackAnalyst(analyst, deterministic, on_failure)
    )
    run.engine = analyst.name
    _stage(run, store, "company")
    try:
        company = filings.company(run.inputs.ticker)
    except SourceError as exc:
        return fail_run(run, store, str(exc))
    run.company = company
    run.claims = [
        Claim(id=f"c{position}", text=text)
        for position, text in enumerate(run.inputs.claims, start=1)
    ]

    _stage(run, store, "filings")
    ingested = ingest(
        run, company, store, filings=filings, fetch_page=fetch_page, out_of_time=out_of_time
    )
    run.coverage = Coverage(
        sources_requested=ingested.distinct_requested,
        sources_read=len(ingested.documents),
        claims_total=len(run.claims),
    )
    if not ingested.documents:
        _, reasons = policy.run_status(
            sources_requested=ingested.distinct_requested,
            sources_extracted=0,
            claims=run.claims,
            withheld_findings=0,
            engine_fallbacks=0,
            time_limit_hit=ingested.time_limit_hit,
        )
        return fail_run(run, store, reasons[0])

    _stage(run, store, "planning")
    queries = engine.plan(run.inputs, company)
    if len(queries) != len(run.claims):
        run.errors.append("The plan did not cover every claim; keyword queries were used instead.")
        fallback_steps.append("plan")
        queries = deterministic.plan(run.inputs, company)

    _stage(run, store, "retrieving")
    passages = [
        passage
        for source_id, document in ingested.documents.items()
        for passage in chunk_document(source_id, document)
    ]
    index = PassageIndex(passages)
    urls = {source.id: source.url for source in run.sources}
    stored = {
        source_id: StoredSource(document.text, urls[source_id])
        for source_id, document in ingested.documents.items()
    }
    run.coverage.passages_indexed = len(passages)

    _stage(run, store, "assessing")
    ids = RunIds()
    unknowns: list[str] = []
    time_limit_hit = ingested.time_limit_hit
    unassessed: list[Claim] = []
    for position, claim in enumerate(run.claims):
        if out_of_time():
            time_limit_hit = True
            unassessed = run.claims[position:]
            run.coverage_limits.append(
                f"The run time limit was reached; {len(unassessed)} claim(s) were not assessed."
            )
            for skipped in unassessed:
                skipped.rationale = NOT_ASSESSED_RATIONALE
            break
        run.stage_detail = f"claim {position + 1} of {len(run.claims)}"
        store.save_run(run)
        claim.queries = [query for query in queries[position] if query.strip()][
            : limits.MAX_QUERIES_PER_CLAIM
        ]
        offered = index.search([claim.text, *claim.queries])
        claim.passages_considered = len(offered)
        draft = (
            engine.assess(run.inputs, company, claim, offered)
            if offered
            else ClaimDraft(rationale="No passage in the sources read shares terms with the claim.")
        )
        result = gate_claim(claim.id, draft, {p.id: p for p in offered}, stored, ids)
        run.findings.extend(result.findings)
        run.unsupported_findings.extend(result.unsupported)
        run.evidence.extend(result.evidence)
        run.errors.extend(f"Citation check: {problem}" for problem in result.problems)
        claim.finding_ids = [finding.id for finding in result.findings]
        claim.rationale = draft.rationale
        claim.verdict = policy.claim_verdict(result.findings)
        unknowns.extend(draft.unknowns)
        run.coverage.findings_verified += len(result.findings)
        run.coverage.findings_withheld += len(result.unsupported)
        run.coverage.excerpts_verified += len(result.evidence)
        run.coverage.quotes_offered += result.quotes_offered
        run.coverage.quotes_rejected += result.quotes_rejected
        if claim.verdict != Verdict.not_addressed:
            run.coverage.claims_with_evidence += 1
        store.save_run(run)

    _stage(run, store, "verifying")
    summary_step = len(fallback_steps)
    summary = engine.summarize(run.inputs, company, run.claims, run.findings)
    model_wrote_summary = (
        analyst.name != deterministic.name
        and len(fallback_steps) == summary_step
        and bool(run.findings)
    )
    status, reasons = policy.run_status(
        sources_requested=ingested.distinct_requested,
        sources_extracted=len(ingested.documents),
        claims=run.claims,
        withheld_findings=len(run.unsupported_findings),
        engine_fallbacks=len(fallback_steps),
        time_limit_hit=time_limit_hit,
    )
    run.coverage_limits.extend(reasons)
    for claim in run.claims:
        if claim in unassessed:
            unknowns.append(NOT_ASSESSED_UNKNOWN.format(claim=claim.text))
        elif claim.verdict in (None, Verdict.not_addressed):
            unknowns.append(NO_EVIDENCE_UNKNOWN.format(claim=claim.text))
    run.brief = Brief(
        summary=summary.summary,
        summary_origin="model" if model_wrote_summary else "template",
        unknowns=_distinct(unknowns)[:MAX_UNKNOWNS],
        next_steps=_distinct(summary.next_steps),
        coverage_status=status,
        status_note=policy.STATUS_NOTES[status],
    )
    return _finish(run, store, status)


def sources_read(run: Run) -> int:
    """How many of the run's sources were extracted."""
    return sum(1 for s in run.sources if s.extraction_status == ExtractionStatus.extracted)


def _safe(exc: Exception) -> str:
    """An error description that is safe to show: our own messages, otherwise the type only."""
    if type(exc).__module__.startswith("ed_v2."):
        return str(exc)[:320]
    return type(exc).__name__


def _distinct(items: list[str]) -> list[str]:
    seen: set[str] = set()
    kept: list[str] = []
    for item in items:
        text = item.strip()
        if text and text.casefold() not in seen:
            seen.add(text.casefold())
            kept.append(text)
    return kept


def _stage(run: Run, store: Store, stage: str) -> None:
    run.stage = stage
    run.stage_detail = ""
    store.save_run(run)


def _finish(run: Run, store: Store, status: RunStatus) -> Run:
    run.status = status
    run.stage = "done"
    run.stage_detail = ""
    run.finished_at = datetime.now(UTC)
    store.save_run(run)
    return run
