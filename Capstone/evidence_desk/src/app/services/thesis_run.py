"""One thesis run: resolve, read, compute numbers, plan, retrieve, assess, verify, decide.

This is the only place a run is advanced, and both entry points (the HTTP API
and the command line) call it. It depends on the ports in
:mod:`app.core.ports`, never on a concrete EDGAR client or engine. A run
leaves this module only after :func:`app.core.gate.gate_claim` has checked
every quote, cited figure and stated number, and :mod:`app.core.policy` has
computed the verdicts and status.
"""

from __future__ import annotations

import logging
import time
import uuid
from collections.abc import Callable
from concurrent.futures import Future, ThreadPoolExecutor
from dataclasses import dataclass, field
from datetime import UTC, datetime

from app.core import limits, policy
from app.core.documents import Passage
from app.core.gate import RunIds, StoredSource, gate_claim
from app.core.models import (
    Brief,
    Claim,
    Coverage,
    ExtractionStatus,
    Run,
    RunStatus,
    SourceKind,
    ThesisRequest,
    Verdict,
)
from app.core.numcheck import check_numbers
from app.core.ports import (
    Analyst,
    ClaimDraft,
    FilingSource,
    PageFetcher,
    SourceError,
    SummaryDraft,
)
from app.engines.extractive import ExtractiveAnalyst
from app.engines.fallback import FallbackAnalyst
from app.retrieval.chunk import chunk_document
from app.retrieval.search import PassageIndex
from app.services.ingest import ingest
from app.services.numbers import load_numbers, select_figures
from app.sources.http import fetch_page as default_fetch_page
from app.store import Store

log = logging.getLogger(__name__)
MAX_UNKNOWNS = 12
NOT_ASSESSED_RATIONALE = "Not assessed: the run time limit was reached first."
NOT_ASSESSED_UNKNOWN = "Not assessed before the run time limit: {claim}"
NO_EVIDENCE_UNKNOWN = "No verified evidence was found for: {claim}"
NO_PASSAGE_RATIONALE = "No passage in the sources read shares terms with the claim."


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


@dataclass
class EngineFailures:
    """Every engine step that fell back, in order, with the reason that is safe to show."""

    engine: str
    steps: list[tuple[str, str]] = field(default_factory=list)

    def record(self, step: str, reason: str) -> None:
        """Note that ``step`` fell back because of ``reason``."""
        self.steps.append((step, reason))

    def __len__(self) -> int:
        return len(self.steps)

    def messages(self) -> list[str]:
        """One sentence per distinct reason, naming the steps it hit.

        "The claude engine failed for 7 steps (plan, 5 x assess, summarize): <reason>;
        the deterministic engine was used for those."
        """
        by_reason: dict[str, list[str]] = {}
        for step, reason in self.steps:
            by_reason.setdefault(reason, []).append(step)
        out: list[str] = []
        for reason, steps in by_reason.items():
            counts: dict[str, int] = {}
            for step in steps:
                counts[step] = counts.get(step, 0) + 1
            listed = ", ".join(f"{n} x {s}" if n > 1 else s for s, n in counts.items())
            many = len(steps) > 1
            out.append(
                f"The {self.engine} engine failed for {len(steps)} step{'s' if many else ''} "
                f"({listed}): {reason}; the deterministic engine was used for "
                f"{'those' if many else 'that step'}."
            )
        return out


@dataclass
class _Assessment:
    """One claim's draft, the passages it was drafted from, and the steps that fell back."""

    draft: ClaimDraft
    offered: list[Passage]
    failures: list[tuple[str, str]]


def execute_run(
    run: Run,
    store: Store,
    *,
    filings: FilingSource,
    analyst: Analyst,
    fetch_page: PageFetcher = default_fetch_page,
    clock: Callable[[], float] = time.monotonic,
    concurrency: int = limits.MAX_CONCURRENT_ASSESSMENTS,
) -> Run:
    """Execute ``run`` to completion, persisting progress, and return the final record.

    Up to ``concurrency`` claims are assessed at once (1 assesses them one after
    another); the record is the same either way.
    """
    if concurrency < 1:
        raise ValueError("concurrency must be at least 1")
    started = clock()

    def out_of_time() -> bool:
        return clock() - started > limits.RUN_TIME_LIMIT_SECONDS

    failures = EngineFailures(analyst.name)
    plan_fallbacks = 0

    def on_failure(step: str, exc: Exception) -> None:
        log.warning("%s engine failed during %s: %s", analyst.name, step, _safe(exc))
        failures.record(step, _safe(exc))

    deterministic = ExtractiveAnalyst()
    engine: Analyst = (
        analyst
        if analyst.name == deterministic.name
        else FallbackAnalyst(analyst, deterministic, on_failure)
    )
    run.engine = analyst.name
    run.engine_detail = str(getattr(analyst, "detail", "") or "")
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

    _stage(run, store, "numbers")
    # The facts are recorded as a source but are not a document: they are never chunked or
    # quoted, and they do not count toward sources requested or read.
    numbers = load_numbers(company, filings, source_id=f"s{len(run.sources) + 1}")
    if numbers.source is not None:
        run.sources.append(numbers.source)
    if numbers.report is not None:
        run.metrics = list(numbers.report.metrics)
        run.series = list(numbers.report.series)
    run.metrics_notes = list(numbers.notes)
    if numbers.error is not None:
        run.coverage_limits.append(policy.FACTS_UNAVAILABLE.format(error=numbers.error))
    figures = select_figures(numbers.report)
    offered_figures = {figure.id: figure for figure in figures}
    run.coverage.metrics_computed = sum(1 for m in run.metrics if m.value is not None)
    run.coverage.figures_offered = len(figures)

    _stage(run, store, "planning")
    queries = engine.plan(run.inputs, company)
    if len(queries) != len(run.claims):
        run.errors.append("The plan did not cover every claim; keyword queries were used instead.")
        plan_fallbacks += 1
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

    def assess_claim(claim: Claim, offered: list[Passage]) -> _Assessment:
        """Draft one claim on a worker thread; its fallbacks are kept, not yet recorded."""
        steps: list[tuple[str, str]] = []

        def on_claim_failure(step: str, exc: Exception) -> None:
            log.warning("%s engine failed during %s: %s", analyst.name, step, _safe(exc))
            steps.append((step, _safe(exc)))

        claim_engine: Analyst = (
            analyst
            if analyst.name == deterministic.name
            else FallbackAnalyst(analyst, deterministic, on_claim_failure)
        )
        draft = claim_engine.assess(run.inputs, company, claim, offered, figures=figures)
        return _Assessment(draft, offered, steps)

    def start(pool: ThreadPoolExecutor, position: int) -> Future[_Assessment]:
        """Retrieve one claim's passages here, in claim order, and hand its assessment out."""
        claim = run.claims[position]
        claim.queries = [query for query in queries[position] if query.strip()][
            : limits.MAX_QUERIES_PER_CLAIM
        ]
        offered = index.search([claim.text, *claim.queries])
        claim.passages_considered = len(offered)
        if offered:
            return pool.submit(assess_claim, claim, offered)
        ready: Future[_Assessment] = Future()
        ready.set_result(_Assessment(ClaimDraft(rationale=NO_PASSAGE_RATIONALE), offered, []))
        return ready

    # Up to ``concurrency`` assessments run at once, but claims start in claim order and their
    # results pass the gate in claim order, so every id and count is what a sequential run
    # gives. The time limit is checked once before each round of starts: a claim not started
    # in time is reported as not assessed, exactly as when claims ran one after another.
    total = len(run.claims)
    in_flight: dict[int, Future[_Assessment]] = {}
    next_up = 0
    with ThreadPoolExecutor(max_workers=concurrency, thread_name_prefix="assess") as pool:
        for position, claim in enumerate(run.claims):
            if next_up < total and len(in_flight) < concurrency and not out_of_time():
                while next_up < total and len(in_flight) < concurrency:
                    in_flight[next_up] = start(pool, next_up)
                    next_up += 1
            if position not in in_flight:
                time_limit_hit = True
                unassessed = run.claims[position:]
                run.coverage_limits.append(
                    f"The run time limit was reached; {len(unassessed)} claim(s) were not assessed."
                )
                for skipped in unassessed:
                    skipped.rationale = NOT_ASSESSED_RATIONALE
                break
            run.stage_detail = f"claim {position + 1} of {total}"
            store.save_run(run)
            assessment = in_flight.pop(position).result()
            draft, offered = assessment.draft, assessment.offered
            for step, reason in assessment.failures:
                failures.record(step, reason)
            if offered:
                fell_back = any(step == "assess" for step, _ in assessment.failures)
                claim.assessed_by = deterministic.name if fell_back else analyst.name
            result = gate_claim(
                claim.id, draft, {p.id: p for p in offered}, stored, ids, figures=offered_figures
            )
            run.findings.extend(result.findings)
            run.unsupported_findings.extend(result.unsupported)
            run.evidence.extend(result.evidence)
            run.errors.extend(f"Citation check: {problem}" for problem in result.problems)
            claim.finding_ids = [finding.id for finding in result.findings]
            claim.rationale = draft.rationale
            claim.verdict = policy.claim_verdict(result.findings)
            unknowns.extend(draft.unknowns)
            coverage = run.coverage
            coverage.findings_verified += len(result.findings)
            coverage.findings_withheld += len(result.unsupported)
            coverage.findings_proposed = coverage.findings_verified + coverage.findings_withheld
            coverage.excerpts_verified += len(result.evidence)
            coverage.quotes_offered += result.quotes_offered
            coverage.quotes_rejected += result.quotes_rejected
            coverage.numbers_checked += result.numbers_checked
            coverage.numbers_unmatched += result.numbers_unmatched
            coverage.figures_cited += result.figures_cited
            if claim.verdict != Verdict.not_addressed:
                coverage.claims_with_evidence += 1
            store.save_run(run)

    _stage(run, store, "verifying")
    summary_step = len(failures)
    summary = engine.summarize(run.inputs, company, run.claims, run.findings)
    model_wrote_summary = (
        analyst.name != deterministic.name and len(failures) == summary_step and bool(run.findings)
    )
    if model_wrote_summary:
        unsupported = _unsupported_summary_numbers(summary, run)
        if unsupported:
            run.errors.append(policy.SUMMARY_REPLACED.format(numbers=", ".join(unsupported)))
            summary = deterministic.summarize(run.inputs, company, run.claims, run.findings)
            model_wrote_summary = False
    run.errors.extend(failures.messages())
    fallbacks = len(failures) + plan_fallbacks
    run.coverage.engine_fallbacks = fallbacks
    status, reasons = policy.run_status(
        sources_requested=ingested.distinct_requested,
        sources_extracted=len(ingested.documents),
        claims=run.claims,
        withheld_findings=len(run.unsupported_findings),
        engine_fallbacks=fallbacks,
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


def _unsupported_summary_numbers(summary: SummaryDraft, run: Run) -> list[str]:
    """Numbers in a model summary found in no verified finding statement and no run metric."""
    allowed = [finding.statement for finding in run.findings if finding.verified]
    allowed += [metric.display for metric in run.metrics]
    return check_numbers(summary.summary, allowed, run.metrics).unmatched


def sources_read(run: Run) -> int:
    """How many of the run's documents (filings and pages, not XBRL facts) were extracted."""
    return sum(
        1
        for s in run.sources
        if s.extraction_status == ExtractionStatus.extracted and s.kind != SourceKind.sec_xbrl
    )


def _safe(exc: Exception) -> str:
    """An error description that is safe to show: our own messages, otherwise the type only."""
    if type(exc).__module__.startswith("app."):
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
