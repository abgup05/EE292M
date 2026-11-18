"""One thesis run: resolve, read, compute numbers, plan, retrieve, assess, verify, decide.

This is the only place a run is advanced, and both entry points (the HTTP API
and the command line) call it. It depends on the ports in
:mod:`app.core.ports`, never on a concrete EDGAR client or engine. A run
leaves this module only after :func:`app.core.gate.gate_claim` has checked
every quote, cited figure and stated number (and each finding's reason), a
configured checker has read each verified finding's meaning
(:mod:`app.core.meaning`), the years each verified finding names have been
checked against its evidence (:mod:`app.core.periods`; reported, never
withheld), every number in a claim's commentary, the unknowns and the next steps
has been checked against the verified evidence, and :mod:`app.core.policy` has
computed the verdicts and status.
"""

from __future__ import annotations

import logging
import threading
import time
import uuid
from collections.abc import Callable, Iterator
from concurrent.futures import Future, ThreadPoolExecutor
from contextlib import contextmanager
from dataclasses import dataclass, field
from datetime import UTC, date, datetime

from app.core import events as event_rules
from app.core import limits, policy
from app.core.documents import Passage
from app.core.event_models import Event, EventItem
from app.core.gate import GateResult, RunIds, StoredSource, gate_claim
from app.core.meaning import MeaningResult, apply_judgements, check_items
from app.core.metric_models import Metric
from app.core.models import (
    Brief,
    Claim,
    Company,
    Coverage,
    Evidence,
    ExtractionStatus,
    Finding,
    Run,
    RunStatus,
    SourceKind,
    Stance,
    ThesisRequest,
    UnplacedPeriod,
    Verdict,
)
from app.core.numcheck import check_numbers
from app.core.periods import check_periods
from app.core.ports import (
    Analyser,
    Analyst,
    Checker,
    ClaimDraft,
    ClaimReaders,
    FilingSource,
    PageFetcher,
    SourceError,
    SummaryDraft,
)
from app.engines.analyser import NoAnalyser
from app.engines.checker import NoChecker
from app.engines.extractive import ExtractiveAnalyst
from app.engines.fallback import FallbackAnalyst
from app.retrieval.chunk import chunk_document
from app.retrieval.search import PassageIndex
from app.services import events as event_service
from app.services.analysis import analyse_run
from app.services.computed import compute_claims, count_computed
from app.services.ingest import Ingested, ingest
from app.services.numbers import NumbersResult, load_numbers, select_figures
from app.services.tagged_figures import (
    FOR_CLAIMS,
    load_tagged_figures,
    newest_reports,
    read_reports,
)
from app.sources.http import fetch_page as default_fetch_page
from app.store import FactStore, FilingCache, Store

log = logging.getLogger(__name__)
MAX_UNKNOWNS = 12
NOT_ASSESSED_RATIONALE = "Not assessed: the run time limit was reached first."
NOT_ASSESSED_UNKNOWN = "Not assessed before the run time limit: {claim}"
NO_EVIDENCE_UNKNOWN = "No verified evidence was found for: {claim}"
NO_PASSAGE_RATIONALE = "No passage in the sources read shares terms with the claim."


def new_run(request: ThesisRequest, thesis_id: str | None = None) -> Run:
    """Create a running record with a fresh ID and UTC start time.

    ``thesis_id`` names the saved thesis this run tests, if any.
    """
    return Run(
        id=f"run-{uuid.uuid4().hex[:12]}",
        inputs=request,
        thesis_id=thesis_id,
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
    """One claim after its worker: the draft, what passed the gate, and the meaning check.

    ``meaning`` is None when no checker read the claim's findings; ``check_error``
    says why a checker that was asked could not.
    """

    draft: ClaimDraft
    offered: list[Passage]
    failures: list[tuple[str, str]]
    gated: GateResult = field(default_factory=GateResult)
    meaning: MeaningResult | None = None
    check_error: str = ""


class _GateOrder:
    """Lets claims assessed on worker threads pass the gate one at a time, in claim order.

    The gate issues the finding and evidence ids, so passing it in claim order
    keeps every id what a sequential run gives; one claim at a time also keeps
    the shared quote indexes of the stored sources to one thread.
    """

    def __init__(self) -> None:
        self._next = 0
        self._done: set[int] = set()
        self._ready = threading.Condition()

    @contextmanager
    def turn(self, position: int) -> Iterator[None]:
        """Wait until every claim before ``position`` has passed; hand the turn on afterwards."""
        with self._ready:
            self._ready.wait_for(lambda: self._next == position)
        try:
            yield
        finally:
            self.done(position)

    def done(self, position: int) -> None:
        """Mark ``position`` as through the gate (or as never needing it)."""
        with self._ready:
            self._done.add(position)
            while self._next in self._done:
                self._next += 1
            self._ready.notify_all()


@dataclass
class _Unchecked:
    """Claims whose meaning check could not run, the findings left unchecked, and why."""

    claims: int = 0
    findings: int = 0
    reasons: list[str] = field(default_factory=list)


def execute_run(
    run: Run,
    store: Store,
    *,
    filings: FilingSource,
    analyst: Analyst,
    fetch_page: PageFetcher = default_fetch_page,
    clock: Callable[[], float] = time.monotonic,
    concurrency: int = limits.MAX_CONCURRENT_ASSESSMENTS,
    cache: FilingCache | None = None,
    checker: Checker | None = None,
    facts_store: FactStore | None = None,
    claim_reader: ClaimReaders = None,
    analyser: Analyser | None = None,
) -> Run:
    """Execute ``run`` to completion, persisting progress, and return the final record.

    Up to ``concurrency`` claims are assessed at once (1 assesses them one after
    another); the record is the same either way. Source text is kept in
    ``cache``; without one, an in-memory cache that lives for this run only.
    ``checker`` reads each claim's verified findings again, after the gate and
    before the verdict, in the worker that assessed the claim; without one (or
    with :class:`~app.engines.checker.NoChecker`) every finding stays unchecked.
    ``facts_store`` keeps every XBRL fact the run reads (none kept without one).
    ``claim_reader`` is the model parser, a second reader of each claim's test; without
    one (the default) the grammar reads them alone. ``analyser`` proposes each claim's
    corollaries and argues the analysis once the verdicts are final (two requests); without
    one the run records the analysis code computes (:mod:`app.services.analysis`).
    """
    if concurrency < 1:
        raise ValueError("concurrency must be at least 1")
    cache = cache if cache is not None else FilingCache()
    reader = None if checker is None or isinstance(checker, NoChecker) else checker
    started = clock()

    def out_of_time() -> bool:
        return clock() - started > limits.RUN_TIME_LIMIT_SECONDS

    failures = EngineFailures(analyst.name)
    plan_fallbacks = 0

    def on_failure(step: str, exc: Exception) -> None:
        log.warning("%s engine failed during %s: %s", analyst.name, step, safe_message(exc))
        failures.record(step, safe_message(exc))

    deterministic = ExtractiveAnalyst()
    engine: Analyst = (
        analyst
        if analyst.name == deterministic.name
        else FallbackAnalyst(analyst, deterministic, on_failure)
    )
    run.engine = analyst.name
    run.engine_detail = str(getattr(analyst, "detail", "") or "")
    if reader is not None:
        run.checker = reader.name
        run.checker_detail = str(reader.detail or "")
    _stage(run, store, "company")
    try:
        company = filings.company(run.inputs.ticker)
    except SourceError as exc:
        return fail_run(run, store, str(exc))
    run.company = company
    run.claims = [
        Claim(
            id=f"c{position}",
            text=text,
            categories=[category.value for category in event_rules.claim_categories(text)],
        )
        for position, text in enumerate(run.inputs.claims, start=1)
    ]

    _stage(run, store, "filings")
    ingested = ingest(
        run,
        company,
        store,
        filings=filings,
        fetch_page=fetch_page,
        out_of_time=out_of_time,
        cache=cache,
    )
    run.coverage = Coverage(
        filings_asked=run.inputs.filings,
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

    _stage(run, store, "events")
    timeline = _read_events(run, company, ingested, filings, cache, out_of_time)

    _stage(run, store, "numbers")
    # The facts are recorded as a source but are not a document: they are never chunked or
    # quoted, and they do not count toward sources requested or read.
    numbers = load_numbers(
        company,
        filings,
        source_id=f"s{len(run.sources) + 1}",
        facts_store=facts_store,
        as_of=run.inputs.as_of,
    )
    if numbers.source is not None:
        run.sources.append(numbers.source)
    if numbers.report is not None:
        run.metrics = list(numbers.report.metrics)
        run.series = list(numbers.report.series)
    run.metrics_notes = list(numbers.notes)
    figures = select_figures(numbers.report)
    run.coverage.metrics_computed = sum(1 for m in run.metrics if m.value is not None)
    run.coverage.figures_offered = len(figures)
    tagged_errors: list[str] = []
    if run.inputs.tagged_figures:
        # Opt-in: the figures join the prompt after the company-facts figures and the record
        # with the other metrics, so a finding's metric_ids resolve on the page and in the brief.
        tagged = load_tagged_figures(
            company,
            filings,
            ingested.filing_refs.values(),
            cache=cache,
            html_by_accession=ingested.filing_html,
        )
        run.metrics += tagged.figures
        run.metrics_notes += tagged.notes
        figures = [*figures, *tagged.figures]
        tagged_errors = tagged.errors
        run.coverage.tagged_figures_offered = len(tagged.figures)
    offered_figures = {figure.id: figure for figure in figures}
    # Computed tests: compiled from the claim text, computed from the facts just read. The
    # engine is never asked about them; their outcomes enter the verdicts after the summary.
    newest = newest_reports(ingested.filing_refs.values())
    computed = compute_claims(
        run,
        numbers,
        lambda: read_reports(
            company, filings, newest, cache=cache, html_by_accession=ingested.filing_html
        )[:2],
        claim_reader,
        lambda: read_reports(
            company,
            filings,
            newest,
            cache=cache,
            html_by_accession=ingested.filing_html,
            specs=FOR_CLAIMS,
        )[:2],
    )

    # The parts the analysis may tie a claim to: the tags of the newest reports, from the
    # cache when it keeps them, else from the HTML this run fetched (then kept for the next
    # run). Never a fetch: a filing read from a cache that kept no tags gives a note instead.
    part_reports, part_errors, _ = read_reports(
        company,
        filings,
        newest,
        cache=cache,
        html_by_accession=ingested.filing_html,
        fetch=False,
    )
    ingested.filing_html.clear()  # megabytes of HTML, needed for the tags and no longer

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
    # 8-K sections never join the index: they are offered only to a claim of their category.
    pinned = _pin_event_passages(run, company, timeline)
    urls = {source.id: source.url for source in run.sources}
    # Quotes are verified against the text as stored, read back the one way stored text is read.
    texts = cache.source_texts(run)
    read_ids = [*ingested.documents, *(e.source_id for e in run.timeline if e.source_id)]
    missing = sorted(set(read_ids) - set(texts))
    if missing:
        raise RuntimeError(f"the stored text of {', '.join(missing)} is missing from the cache")
    stored = {source_id: StoredSource(texts[source_id], urls[source_id]) for source_id in read_ids}
    run.coverage.passages_indexed = len(passages)

    _stage(run, store, "assessing")
    period_ends = {source.id: _day(source.period_end) for source in run.sources}
    ids = RunIds()
    unknowns: list[str] = []
    time_limit_hit = ingested.time_limit_hit
    unassessed: list[Claim] = []
    gate_order = _GateOrder()
    unchecked = _Unchecked()

    def check_meaning(claim: Claim, assessment: _Assessment) -> None:
        """Have the checker read the claim's verified findings; apply its judgements."""
        gated = assessment.gated
        if reader is None or not gated.findings:
            return
        items = check_items(gated.findings, {e.id: e for e in gated.evidence}, offered_figures)
        try:
            judgements = reader.check(run.inputs, company, claim, items)
            assessment.meaning = apply_judgements(gated.findings, judgements)
        except Exception as exc:  # noqa: BLE001 - any failure leaves the findings unchecked
            log.warning("the meaning check failed for %s: %s", claim.id, safe_message(exc))
            assessment.check_error = safe_message(exc)

    def assess_claim(position: int, claim: Claim, offered: list[Passage]) -> _Assessment:
        """Draft, gate and check one claim on a worker thread; fallbacks are kept, not recorded."""
        steps: list[tuple[str, str]] = []

        def on_claim_failure(step: str, exc: Exception) -> None:
            log.warning("%s engine failed during %s: %s", analyst.name, step, safe_message(exc))
            steps.append((step, safe_message(exc)))

        claim_engine: Analyst = (
            analyst
            if analyst.name == deterministic.name
            else FallbackAnalyst(analyst, deterministic, on_claim_failure)
        )
        try:
            draft = claim_engine.assess(run.inputs, company, claim, offered, figures=figures)
        except BaseException:
            gate_order.done(position)  # never gated, so later claims must not wait for it
            raise
        with gate_order.turn(position):
            gated = gate_claim(
                claim.id, draft, {p.id: p for p in offered}, stored, ids, figures=offered_figures
            )
        assessment = _Assessment(draft, offered, steps, gated)
        check_meaning(claim, assessment)
        return assessment

    def start(pool: ThreadPoolExecutor, position: int) -> Future[_Assessment]:
        """Retrieve one claim's passages here, in claim order, and hand its assessment out."""
        claim = run.claims[position]
        claim.queries = [query for query in queries[position] if query.strip()][
            : limits.MAX_QUERIES_PER_CLAIM
        ]
        offered = [*index.search([claim.text, *claim.queries]), *pinned.get(claim.id, [])]
        claim.passages_considered = len(offered)
        if offered:
            return pool.submit(assess_claim, position, claim, offered)
        gate_order.done(position)  # an empty draft issues no id
        ready: Future[_Assessment] = Future()
        ready.set_result(_Assessment(ClaimDraft(rationale=NO_PASSAGE_RATIONALE), offered, []))
        return ready

    # Up to ``concurrency`` claims are assessed and checked at once, but claims start in claim
    # order and pass the gate in claim order, and their results are recorded in claim order, so
    # every id and count is what a sequential run gives. The time limit is checked once before
    # each round of starts: a claim not started in time is reported as not assessed, exactly
    # as when claims ran one after another.
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
            draft, offered, result = assessment.draft, assessment.offered, assessment.gated
            for step, reason in assessment.failures:
                failures.record(step, reason)
            if offered:
                fell_back = any(step == "assess" for step, _ in assessment.failures)
                claim.assessed_by = deterministic.name if fell_back else analyst.name
            verified, withheld, evidence = result.findings, result.unsupported, result.evidence
            figures_cited = result.figures_cited
            coverage = run.coverage
            meaning = assessment.meaning
            if meaning is not None:
                # A finding the second model judged unsupported is withheld, and its excerpts
                # and cited figures no longer count.
                verified, withheld = meaning.kept, [*withheld, *meaning.withheld]
                evidence = [item for item in evidence if item.id not in meaning.dropped_evidence]
                figures_cited -= sum(len(finding.metric_ids) for finding in meaning.withheld)
                coverage.findings_checked += meaning.checked
                coverage.findings_partly += meaning.partly
                coverage.findings_failed_meaning += meaning.failed
            elif assessment.check_error:
                unchecked.claims += 1
                unchecked.findings += len(verified)
                unchecked.reasons.append(assessment.check_error)
            # Reported, never withheld: the check changes no finding, verdict or status.
            _check_periods(verified, evidence, offered_figures, period_ends, numbers, coverage)
            run.findings.extend(verified)
            run.unsupported_findings.extend(withheld)
            run.evidence.extend(evidence)
            run.errors.extend(f"Citation check: {problem}" for problem in result.problems)
            claim.finding_ids = [finding.id for finding in verified]
            claim.rationale = _checked_commentary(
                draft.rationale, verified, evidence, offered_figures
            )
            if claim.rationale != draft.rationale:
                coverage.reasons_withheld += 1
            policy.mark_counted(verified)
            claim.verdict = policy.claim_verdict(verified)
            # Reported, never withheld: an 8-K later than a finding changes no verdict.
            _mark_predated(claim, verified, evidence, offered_figures, run)
            unknowns.extend(draft.unknowns)
            coverage.findings_verified += len(verified)
            coverage.findings_withheld += len(withheld)
            coverage.findings_proposed = coverage.findings_verified + coverage.findings_withheld
            coverage.findings_without_quote += sum(1 for f in verified if not f.evidence_ids)
            coverage.excerpts_verified += len(evidence)
            coverage.quotes_offered += result.quotes_offered
            coverage.quotes_found += result.quotes_found
            coverage.quotes_rejected += result.quotes_rejected
            coverage.numbers_checked += result.numbers_checked
            coverage.numbers_unmatched += result.numbers_unmatched
            coverage.reasons_withheld += result.reasons_withheld
            coverage.figures_cited += figures_cited
            if claim.verdict != Verdict.not_addressed:
                coverage.claims_with_evidence += 1
            store.save_run(run)
    _record_meaning_limits(run, reader, analyst, unchecked)
    _note_events(run, timeline)

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
    # The summariser was shown the verdicts of the findings; now the computed tests count.
    shown = {claim.id: claim.verdict for claim in run.claims}
    count_computed(run, {claim.id for claim in unassessed})
    verdicts_after = ""
    if model_wrote_summary:
        # A model's request must stay as recorded, so its summary is kept and followed by
        # a line, written here, naming each verdict the computed tests set or changed.
        verdicts_after = policy.verdicts_after_summary(
            [
                (claim.text, shown[claim.id], claim.verdict)
                for claim in run.claims
                if claim.verdict != shown[claim.id]
            ]
        )
    else:
        # The template is written again from the final verdicts, so it cannot contradict them.
        summary = deterministic.summarize(run.inputs, company, run.claims, run.findings)
    run.errors.extend(failures.messages())

    # The analysis reads the final verdicts and never changes them, nor the run's status.
    def analysing(step: str) -> None:
        run.stage_detail = step
        store.save_run(run)

    analyse_run(
        run,
        numbers,
        computed,
        analyser or NoAnalyser(),
        read_reports=lambda: (part_reports, part_errors),
        out_of_time=out_of_time,
        on_step=analysing,
    )
    unknowns, dropped = _drop_unverified_numbers(unknowns, run)
    next_steps, dropped_steps = _drop_unverified_numbers(summary.next_steps, run)
    if dropped + dropped_steps:
        run.errors.append(policy.ENTRIES_DROPPED.format(count=dropped + dropped_steps))
    fallbacks = len(failures) + plan_fallbacks
    run.coverage.engine_fallbacks = fallbacks
    filings_read = [
        source
        for source in run.sources
        if source.id in ingested.documents and source.kind == SourceKind.sec_filing
    ]
    status, reasons = policy.run_status(
        sources_requested=ingested.distinct_requested,
        sources_extracted=len(ingested.documents),
        claims=run.claims,
        withheld_findings=len(run.unsupported_findings),
        engine_fallbacks=fallbacks,
        time_limit_hit=time_limit_hit,
        thin_filings=sum(
            1
            for source in filings_read
            if source.item_coverage is not None and source.item_coverage < limits.MIN_ITEM_COVERAGE
        ),
        filings_read=len(filings_read),
        facts_error=numbers.error,
        unchecked_findings=unchecked.findings,
        verified_findings=run.coverage.findings_verified,
        tagged_errors=tagged_errors,
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
        next_steps=_distinct(next_steps),
        coverage_status=status,
        status_note=policy.STATUS_NOTES[status],
        provenance_note=policy.provenance_note(run.sources),
        verdicts_after_summary=verdicts_after,
    )
    return _finish(run, store, status)


def _read_events(
    run: Run,
    company: Company,
    ingested: Ingested,
    filings: FilingSource,
    cache: FilingCache,
    out_of_time: Callable[[], bool],
) -> event_service.Timeline:
    """List the 8-Ks since the newest annual report read, read some, and date the evidence.

    Sets ``run.timeline`` and ``run.as_of``. A failure here is a reason on an event
    or the index error on the as-of block, never an error of the run.
    """
    refs = list(ingested.filing_refs.values())
    annual = [ref.filed_date for ref in refs if ref.form.startswith("10-K")]
    requested = run.inputs.as_of
    timeline = event_service.read_timeline(
        company,
        filings,
        cache,
        annual_filed=max(annual, default=None),
        periodic_filed=max((ref.filed_date for ref in refs), default=None),
        out_of_time=out_of_time,
        filed_until=requested.isoformat() if requested is not None else None,
    )
    run.timeline = timeline.events
    read = [(ref.form, ref.filed_date, ref.url) for ref in refs]
    run.as_of = event_service.as_of(timeline, read, run.started_at.date(), requested=requested)
    return timeline


def _pin_event_passages(
    run: Run, company: Company, timeline: event_service.Timeline
) -> dict[str, list[Passage]]:
    """The 8-K sections offered to each claim, by claim id; their 8-Ks become run sources.

    A claim is offered up to :data:`~app.core.limits.EVENT_PASSAGES_PER_CLAIM` item
    sections of its own categories from 8-Ks read, newest first. An 8-K is a source
    of the run only when one of its sections is offered.
    """
    by_claim: dict[str, list[tuple[Event, EventItem]]] = {}
    for claim in run.claims:
        chosen = event_rules.pinned_items(
            claim.categories, timeline.events, limits.EVENT_PASSAGES_PER_CLAIM
        )
        if chosen:
            by_claim[claim.id] = chosen
    source_ids: dict[str, str] = {}
    for chosen in by_claim.values():
        for item_event, _item in chosen:
            if item_event.id in source_ids:
                continue
            source_id = f"s{len(run.sources) + 1}"
            source_ids[item_event.id] = source_id
            item_event.source_id = source_id
            run.sources.append(
                event_service.event_source(source_id, item_event, company, item_event.url)
            )
    return {
        claim_id: event_service.event_passages(chosen, timeline.documents, source_ids)
        for claim_id, chosen in by_claim.items()
    }


def _mark_predated(
    claim: Claim,
    verified: list[Finding],
    evidence: list[Evidence],
    figures: dict[str, Metric],
    run: Run,
) -> None:
    """Mark each verified finding an 8-K postdates, and caution a claim whose verdict rests on one.

    A finding's dates are those of every filing it cites: the filing of each excerpt
    and of each input of each cited figure. Only a finding the verdict rule counts as
    supporting or challenging gives the claim its caution: context decides no verdict.
    """
    if not claim.categories or not run.timeline:
        return
    published = {source.id: source.published_date for source in run.sources}
    by_evidence = {item.id: item for item in evidence}
    for finding in verified:
        dates = [
            published.get(by_evidence[evidence_id].source_id)
            for evidence_id in finding.evidence_ids
            if evidence_id in by_evidence
        ]
        dates += [
            fact.filed
            for metric_id in finding.metric_ids
            if metric_id in figures
            for fact in figures[metric_id].inputs
        ]
        finding.predated_by = event_rules.predating(
            [day for day in dates if day], claim.categories, run.timeline
        )
    decisive = (Stance.supports, Stance.challenges)
    claim.caution = event_rules.claim_caution(
        [f.predated_by for f in verified if f.counted_as in decisive], run.timeline
    )


def _note_events(run: Run, timeline: event_service.Timeline) -> None:
    """Give each claim of a substantive category what the 8-Ks do and do not report on it."""
    newest = run.as_of.newest_filed if run.as_of is not None else None
    for claim in run.claims:
        claim.event_note = event_rules.events_note(
            claim.categories,
            timeline.events,
            timeline.annual_filed,
            newest,
            timeline.index_error,
        )


def _record_meaning_limits(
    run: Run, reader: Checker | None, analyst: Analyst, unchecked: _Unchecked
) -> None:
    """Say on the run where the meaning check fell short: a coverage limit, or one error line.

    A checker that read with the engine's own model is no independent reading: a
    coverage limit. A check that could not run leaves its findings unchecked: one
    error line here, and the status rule makes the run partial for it
    (:func:`app.core.policy.run_status`).
    """
    if reader is None:
        return
    engine_model = getattr(analyst, "model", None)
    if reader.same_model_as(engine_model if isinstance(engine_model, str) else None):
        run.coverage_limits.append(policy.MEANING_SAME_MODEL)
    if unchecked.findings:
        run.errors.append(
            policy.MEANING_UNCHECKED_ERROR.format(
                claims=unchecked.claims,
                findings=unchecked.findings,
                reasons="; ".join(_distinct(unchecked.reasons)),
            )
        )


def _day(value: str | None) -> date | None:
    """A source's ``YYYY-MM-DD`` period end as a date; None for none or an unreadable one."""
    if not value:
        return None
    try:
        return date.fromisoformat(value)
    except ValueError:
        return None


def _check_periods(
    findings: list[Finding],
    evidence: list[Evidence],
    figures: dict[str, Metric],
    period_ends: dict[str, date | None],
    numbers: NumbersResult,
    coverage: Coverage,
) -> None:
    """Record the period check on each verified finding of one claim, and count it.

    Each finding is checked against its own excerpts (``evidence`` is the claim's
    verified evidence), each with the period end of the source it is from
    (``period_ends``, by source id), and its cited figures (``figures`` are those
    offered, by id), with the company's fiscal calendar when it was read
    (:func:`app.core.periods.check_periods`). Nothing is withheld.
    """
    excerpts = {item.id: item for item in evidence}
    for finding in findings:
        quoted = [excerpts[i] for i in finding.evidence_ids if i in excerpts]
        check = check_periods(
            finding.statement,
            [(item.excerpt, period_ends.get(item.source_id)) for item in quoted],
            [figures[metric_id] for metric_id in finding.metric_ids if metric_id in figures],
            numbers.calendar,
        )
        finding.checks.periods = check.status
        finding.checks.periods_detail = list(check.details)
        finding.checks.periods_unverified = [
            UnplacedPeriod(mention=year.raw, comparative=year.comparative, detail=year.detail)
            for year in check.unplaced
        ]
        coverage.periods_checked += check.checked
        coverage.periods_unverified += len(check.unverified)
        coverage.periods_comparative += len(check.comparative)


def _checked_commentary(
    commentary: str,
    findings: list[Finding],
    evidence: list[Evidence],
    figures: dict[str, Metric],
) -> str:
    """A claim's commentary, or the withheld note when it cites a number its evidence lacks.

    The numbers are checked against the excerpts and cited figures of the claim's
    verified ``findings`` (``evidence`` is the claim's verified evidence, ``figures``
    the figures offered, by id).
    """
    cited = [
        figures[metric_id]
        for finding in findings
        for metric_id in finding.metric_ids
        if metric_id in figures
    ]
    numbers = check_numbers(commentary, [item.excerpt for item in evidence], cited)
    if numbers.status != "failed":
        return commentary
    return policy.COMMENTARY_WITHHELD.format(numbers=", ".join(numbers.unmatched))


def _drop_unverified_numbers(entries: list[str], run: Run) -> tuple[list[str], int]:
    """The engine-written ``entries`` whose numbers are all verified, and how many were dropped.

    Verified means in an excerpt kept as evidence, a verified finding's statement,
    or a reported figure of the run.
    """
    allowed = [item.excerpt for item in run.evidence]
    allowed += [finding.statement for finding in run.findings if finding.verified]
    kept = [
        entry for entry in entries if check_numbers(entry, allowed, run.metrics).status != "failed"
    ]
    return kept, len(entries) - len(kept)


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


def safe_message(exc: Exception) -> str:
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
