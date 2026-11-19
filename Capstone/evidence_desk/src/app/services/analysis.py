"""The analysis of a run, after its verdicts are final: relevance, analytics, odds, corollaries
and the argued analysis.

One job, called by :func:`app.services.thesis_run.execute_run` once the computed tests have
entered the verdicts. In order:

1. relevance (:mod:`app.core.relevance`): the measures that bear on each claim, the
   thesis's headline figures, and the reported figures no claim is tied to. The parts a
   claim may name (a segment, a product line, a geography) are those the newest filings the
   run read tag; when no computed test already read those tags, they are read here, once,
   from the tags the cache keeps or the HTML the run fetched (nothing is fetched for them);
2. analytics from every provider in ``providers`` (this version:
   :class:`~app.core.analytics.FactsProvider`, from the run's dated facts and those tags);
3. persistence odds for each claim's test (:mod:`app.core.persistence`);
4. with an analysing model: one "propose" request for every claim's implications, each read
   and computed by code (:mod:`app.core.corollaries`), then one "analyse" request for the
   argument, every sentence audited (:mod:`app.core.analysis_audit`).

Without a model (the extractive engine), when a request fails, or when a cassette holds no
answer, the record carries the computed analysis only and says why: a reason on the
analysis, and one line in ``run.errors`` for a failure. The run's status and verdicts are
never changed here.
"""

from __future__ import annotations

import logging
import threading
import time
from collections.abc import Callable, Sequence
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field, replace
from typing import Any

from app.core import analysis_policy as rules
from app.core.analysis_audit import audit_argument, citables
from app.core.analysis_models import (
    Analysis,
    Analytic,
    ArgSentence,
    ClaimAnalysis,
    ClaimArgument,
    Corollary,
    Persistence,
    RelevantMeasure,
    ThesisArgument,
)
from app.core.analytics import AnalyticsProvider, AnalyticsRequest, FactsProvider
from app.core.breakdown_models import BreakdownReport
from app.core.claim_eval import HistoryBooks, Measures, newest_periods
from app.core.claim_test_models import ComputedTest
from app.core.claimtest import ClaimTest
from app.core.corollaries import COUNTED, FactsAt, corollaries, flag
from app.core.models import Claim, Finding, Run
from app.core.persistence import persistence
from app.core.ports import (
    Analyser,
    AnalysisBrief,
    ArgumentDraft,
    BriefClaim,
    BriefItem,
    ProposedImplications,
    SourceError,
)
from app.core.relevance import (
    claim_relevance,
    compares_with_peers,
    headline,
    part_names,
    untied_metric_ids,
)
from app.engines.transport import EngineError, answered_by, answers_mark
from app.services.computed import Computed
from app.services.numbers import NumbersResult

log = logging.getLogger(__name__)
MAX_WHY_CHARS = 320
MAX_FINDINGS_SHOWN = 6
MAX_QUOTE_CHARS = 300
MAX_OPENING_CHARS = 400
# Reads the tagged breakdowns of the newest filings the run read: the reports and any failure.
ReportReader = Callable[[], tuple[list[BreakdownReport], list[str]]]
DEFAULT_PROVIDERS: tuple[AnalyticsProvider, ...] = (FactsProvider(),)
# The order a claim's analytics are listed in, by kind (a kind not named here: with the measure).
READING_ORDER = {
    "headroom": 0,
    "needed": 0,
    "cushion": 0,
    "sides": 0,
    "history": 0,
    "part_growth": 1,
    "part_pace": 1,
    "base_rate": 1,
    "bridge": 3,
    "peer_standing": 3,
    "earnings_quality": 4,
    "pe": 5,
    "fcf_yield": 5,
    "reverse_dcf": 5,
}


@dataclass(frozen=True)
class _Claimed:
    """One claim's relevance, analytics and odds, before any model is asked."""

    relevant: list[RelevantMeasure]
    analytic_ids: list[str]
    odds: Persistence


def _why(exc: Exception) -> str:
    # An EngineError's message is safe to show (its contract); it is cut, never echoed whole.
    return str(exc)[:MAX_WHY_CHARS] or exc.__class__.__name__


Timing = Callable[[str, float, bool, str], None]


def _no_timing(stage: str, seconds: float, background: bool, note: str) -> None:
    """Timings nobody asked for."""


@dataclass
class _Task:
    """Work started in a thread of its own: the thread, where it leaves its result, and when
    it began (by the run's clock)."""

    thread: threading.Thread
    box: dict[str, Any]
    began: float

    def joined(self, wait: float | None) -> bool:
        """Wait up to ``wait`` seconds (None: until it ends); True when it has ended."""
        self.thread.join(wait)
        return "out" in self.box


def _started(name: str, work: Callable[[], Any], clock: Callable[[], float]) -> _Task:
    box: dict[str, Any] = {}

    def run() -> None:
        began = clock()
        try:
            box["out"] = work()
        finally:
            box["seconds"] = clock() - began

    thread = threading.Thread(target=run, name=name, daemon=True)
    task = _Task(thread, box, clock())
    thread.start()
    return task


def _provided(provider: AnalyticsProvider, request: AnalyticsRequest) -> list[Analytic] | str:
    """The provider's analytics, or why it gave none. A provider is code outside this module,
    so any failure of one is caught here and logged with its trace; a :class:`SourceError`
    carries a message safe to show."""
    try:
        return provider.provide(request)
    except SourceError as exc:
        return _why(exc)
    except Exception as exc:  # noqa: BLE001 - see the docstring
        log.exception("The analytics provider %s failed", provider.name)
        return f"it failed ({exc.__class__.__name__})"


@dataclass
class Background:
    """What a run starts as soon as its claims are computed, to be joined by the analysis: the
    providers that read EDGAR, and the corollary proposals. ``reports`` are the tagged
    breakdowns the parts are read from, with ``breakdowns_note`` saying which or why none."""

    reports: list[BreakdownReport]
    breakdowns_note: str
    providers: dict[str, _Task] = field(default_factory=dict)
    proposal: _Task | None = None
    # Where the analyser's answers stood before this run asked for any (answers_mark).
    answers_mark: int = 0


def _tests(run: Run, computed: Computed) -> dict[str, tuple[ClaimTest, ComputedTest]]:
    tests: dict[str, tuple[ClaimTest, ComputedTest]] = {}
    for claim in run.claims:
        test = computed.tests.get(claim.id)
        if test is not None and claim.computed is not None:
            tests[claim.id] = (test, claim.computed)
    return tests


def _request(
    run: Run,
    numbers: NumbersResult,
    tests: dict[str, tuple[ClaimTest, ComputedTest]],
    relevant: dict[str, list[RelevantMeasure]],
    reports: Sequence[BreakdownReport],
) -> AnalyticsRequest:
    return AnalyticsRequest(
        book=numbers.book,
        calendar=numbers.calendar,
        measures={claim_id: [m.key for m in items] for claim_id, items in relevant.items()},
        tests=tests,
        reports=reports,
        error=numbers.error or "",
        company=run.company,
        claims={claim.id: claim.text for claim in run.claims},
        as_of=run.inputs.as_of,
        today=run.started_at.date(),
        payload=numbers.payload,
    )


def _relevance(
    run: Run,
    tests: dict[str, tuple[ClaimTest, ComputedTest]],
    reports: Sequence[BreakdownReport],
    findings: Sequence[Finding],
) -> dict[str, list[RelevantMeasure]]:
    parts = part_names(reports)
    return {
        claim.id: claim_relevance(
            claim, tests[claim.id][0] if claim.id in tests else None, findings, run.metrics, parts
        )
        for claim in run.claims
    }


def start_background(
    run: Run,
    numbers: NumbersResult,
    computed: Computed,
    analyser: Analyser,
    *,
    providers: Sequence[AnalyticsProvider] = DEFAULT_PROVIDERS,
    read_reports: ReportReader | None = None,
    out_of_time: Callable[[], bool] = lambda: False,
    clock: Callable[[], float] = time.monotonic,
) -> Background:
    """Start what the analysis needs and nothing later in the run changes: each provider with
    a time budget (it reads EDGAR), and the request for the corollaries. Called once the
    claims are computed, so both run while the claims are assessed; the analysis joins them.

    They are given what is known then: each claim's text, its computed test, the measures its
    test and its words name and the parts the filings tag. A measure that only a finding
    cites is not known yet, so a provider started here does not see it (the run's own facts
    provider, which runs at the end, does), and the proposer is not shown a verdict.
    """
    reports, note = _reports(computed, read_reports)
    started = Background(reports, note, answers_mark=answers_mark(analyser))
    if out_of_time():
        return started
    tests = _tests(run, computed)
    relevant = _relevance(run, tests, reports, [])
    request = _request(run, numbers, tests, relevant, reports)
    for provider in providers:
        if getattr(provider, "budget_seconds", None) is not None:
            started.providers[provider.name] = _started(
                f"provider-{provider.name}", lambda p=provider: _provided(p, request), clock
            )
    if analyser.name != "none" and run.company is not None:
        brief = _propose_brief(run, relevant, reports)

        def propose() -> ProposedImplications | EngineError:
            try:
                return analyser.propose(brief)
            except EngineError as exc:
                return exc

        started.proposal = _started("propose", propose, clock)
    return started


def _provide(
    run: Run,
    providers: Sequence[AnalyticsProvider],
    request: AnalyticsRequest,
    analysis: Analysis,
    background: Background,
    clock: Callable[[], float],
    timing: Timing,
) -> list[Analytic]:
    """Every provider's analytics. One with a time budget was started in the background
    (:func:`start_background`) and is waited for until its budget, counted from its start, is
    spent; past it the run goes on without it, and its thread is left to finish what it is
    reading (what it keeps on disk is there for the next run). One that gives nothing is
    named in ``providers_failed`` with its reason and gets a line in ``run.errors``."""
    analytics: list[Analytic] = []
    for provider in providers:
        analysis.providers.append(provider.name)
        budget = getattr(provider, "budget_seconds", None)
        began = clock()
        found: list[Analytic] | str
        if budget is None:
            found = _provided(provider, request)
            timing(f"analytics: {provider.name}", clock() - began, False, "")
        elif provider.name not in background.providers:
            found = rules.OUT_OF_TIME_WHY
        else:
            task = background.providers[provider.name]
            if task.joined(max(budget - (clock() - task.began), 0.0)):
                found = task.box["out"]
                timing(f"analytics: {provider.name}", task.box["seconds"], True, "")
            else:
                found = rules.PROVIDER_OUT_OF_TIME.format(seconds=budget)
                timing(f"analytics: {provider.name}", float(budget), True, "out of time")
        if isinstance(found, str):
            analysis.providers_failed.append(provider.name)
            analysis.provider_reasons[provider.name] = found
            run.errors.append(rules.PROVIDER_FAILED_ERROR.format(name=provider.name, why=found))
        else:
            analytics += found
    return analytics


def _test_line(claim: Claim) -> str:
    test = claim.computed
    if test is None:
        return ""
    line = f"{test.bound or test.canonical}: {test.outcome_label}"
    if test.margin_display:
        line += f" (margin {test.margin_display})"
    if test.reason:
        line += f". {test.reason}"
    if test.agreement_label:
        line += f". Readers: {test.agreement_label}"
    return line


def _analytic_text(item: Analytic) -> str:
    text = f"{item.question} {item.reading} [{item.label}: {item.display}]"
    # What a number from outside the company's own facts rests on, and what it is not.
    return f"{text} Note: {item.note}" if item.note and item.provider != "facts" else text


def _finding_text(finding: Finding, quote: str | None) -> str:
    counted = f", counted as {finding.counted_as}" if finding.counted_as else ""
    text = f"[{finding.stance.value}{counted}] {finding.statement}"
    return text + (f' Quote: "{quote[:MAX_QUOTE_CHARS]}"' if quote else "")


def _corollary_text(item: Corollary) -> str:
    text = (
        f"{item.sentence} (if the claim is true this should {item.expect[:-1]}; "
        f"read by {item.read_by}): "
    )
    if item.computed is None:
        return text + "not computed."
    test = item.computed
    margin = f", margin {test.margin_display}" if test.margin_display else ""
    return (
        text + f"{test.bound or test.canonical}: {test.outcome_label}{margin}; {item.result_label}."
    )


def _claim_notes(claim: Claim) -> tuple[str, ...]:
    notes = [claim.compile_note, claim.caution, claim.event_note]
    return tuple(note for note in notes if note)


def _brief(
    run: Run,
    analytics: Sequence[Analytic],
    claimed: dict[str, _Claimed],
    found: Sequence[Corollary],
    parts: Sequence[str] = (),
) -> AnalysisBrief:
    """The record as the analysing model is shown it, every item with the id to cite."""
    by_id = {item.id: item for item in analytics}
    quotes: dict[str, str] = {}
    for item in run.evidence:
        quotes.setdefault(item.finding_id, item.excerpt)
    claims: list[BriefClaim] = []
    for claim in run.claims:
        mine = claimed[claim.id]
        findings = [f for f in run.findings if f.claim_id == claim.id][:MAX_FINDINGS_SHOWN]
        odds = mine.odds
        own = [by_id[i] for i in mine.analytic_ids]
        claims.append(
            BriefClaim(
                id=claim.id,
                text=claim.text,
                verdict=claim.verdict.value if claim.verdict else "none",
                test=_test_line(claim),
                findings=tuple(
                    BriefItem(f.id, _finding_text(f, quotes.get(f.id))) for f in findings
                ),
                analytics=tuple(BriefItem(i.id, _analytic_text(i)) for i in own if i.available),
                corollaries=tuple(
                    BriefItem(c.id, _corollary_text(c)) for c in found if c.claim_id == claim.id
                ),
                odds=(
                    (BriefItem(odds.id, f"{odds.note or odds.warning} {odds.caveat}".strip()),)
                    if odds.applicable and (odds.note or odds.warning)
                    else ()
                ),
                notes=_claim_notes(claim),
                not_computed=tuple(
                    f"{i.label}: {i.reading or i.note}" for i in own if not i.available
                ),
            )
        )
    tied = {
        metric_id for mine in claimed.values() for m in mine.relevant for metric_id in m.metric_ids
    }
    figures = tuple(
        BriefItem(m.id, f"{m.label}, {m.period_label}: {m.display}")
        for m in run.metrics
        if m.value is not None and m.id in tied
    )[: rules.MAX_METRICS_SHOWN]
    events = tuple(
        BriefItem(
            e.id,
            f"8-K filed {e.filed_date}; "
            + "; ".join(
                f"Item {i.number} {i.title}"
                + (f': "{" ".join(i.opening)[:MAX_OPENING_CHARS]}"' if i.opening else "")
                for i in e.items
            ),
        )
        for e in run.timeline
        if e.substantive
    )[: rules.MAX_EVENTS_SHOWN]
    company = run.company
    assert company is not None
    return AnalysisBrief(
        company=company,
        decision=run.inputs.decision,
        claims=tuple(claims),
        analytics=tuple(
            BriefItem(item.id, _analytic_text(item))
            for item in analytics
            if item.available and (item.scope == "company" or not item.claim_ids)
        ),
        figures=figures,
        events=events,
        as_of=run.inputs.as_of.isoformat() if run.inputs.as_of else "",
        parts=tuple(parts),
    )


def _reports(
    computed: Computed, read_reports: ReportReader | None
) -> tuple[list[BreakdownReport], str]:
    """The tagged breakdowns the parts are read from (those a computed test already read, else
    the newest filings' own) and the note saying which, or why none; a failure is a note,
    never an error."""
    reports = list(computed.reports)
    errors: list[str] = []
    if not reports and read_reports is not None:
        reports, errors = read_reports()
    if reports:
        read = " and ".join(
            f"the {report.filing.form} filed {report.filing.filed_date}" for report in reports
        )
        return reports, " ".join([f"Parts are read from the tags of {read}.", *errors])
    why = " ".join(errors) or "No filing's tagged breakdowns were read."
    return reports, f"No part of the business could be read: {why}"


def _propose_brief(
    run: Run, relevant: dict[str, list[RelevantMeasure]], reports: Sequence[BreakdownReport]
) -> AnalysisBrief:
    """What the proposer is shown: each claim's text, its computed test and why it has none,
    the reported figures the claims are tied to and the parts the filings tag. No verdict:
    the proposals are asked for before the claims are assessed."""
    company = run.company
    assert company is not None
    tied = {i for items in relevant.values() for m in items for i in m.metric_ids}
    return AnalysisBrief(
        company=company,
        decision=run.inputs.decision,
        claims=tuple(
            BriefClaim(
                id=claim.id,
                text=claim.text,
                verdict="",
                test=_test_line(claim),
                notes=tuple(note for note in (claim.compile_note, _peer_note(claim)) if note),
            )
            for claim in run.claims
        ),
        figures=tuple(
            BriefItem(m.id, f"{m.label}, {m.period_label}: {m.display}")
            for m in run.metrics
            if m.value is not None and m.id in tied
        )[: rules.MAX_METRICS_SHOWN],
        as_of=run.inputs.as_of.isoformat() if run.inputs.as_of else "",
        parts=tuple(dict.fromkeys(label for _, label in part_names(reports))),
    )


def _peer_note(claim: Claim) -> str:
    return rules.PEER_CLAIM_NOTE if compares_with_peers(claim.text) else ""


def analyse_run(
    run: Run,
    numbers: NumbersResult,
    computed: Computed,
    analyser: Analyser,
    *,
    providers: Sequence[AnalyticsProvider] = DEFAULT_PROVIDERS,
    read_reports: ReportReader | None = None,
    background: Background | None = None,
    out_of_time: Callable[[], bool] = lambda: False,
    on_step: Callable[[str], None] = lambda step: None,
    clock: Callable[[], float] = time.monotonic,
    timing: Timing = _no_timing,
) -> None:
    """Set ``run.analysis`` and each claim's ``analysis``, and count them (see the module
    docstring). ``background`` is what :func:`start_background` started earlier in the run;
    without it, it is started here. ``read_reports`` reads the tagged breakdowns of the
    newest filings the run read, and is called only when no computed test read them.
    ``on_step`` is told before each model request, to show progress; ``timing`` is told how
    long each part took (its name, seconds, whether it ran in the background, a note)."""
    coverage = run.coverage
    if background is None:
        background = start_background(
            run,
            numbers,
            computed,
            analyser,
            providers=providers,
            read_reports=read_reports,
            out_of_time=out_of_time,
            clock=clock,
        )
    analysis = Analysis(
        untied_note=rules.UNTIED,
        breakdowns_note=background.breakdowns_note,
        corollary_rule=rules.COROLLARY_RULE,
        audit_rule=rules.AUDIT_RULE,
        persistence_method=rules.PERSISTENCE_METHOD.format(
            paths=rules.PERSISTENCE_PATHS,
            horizon=rules.PERSISTENCE_HORIZON,
            changes="N",
            step="differences in points for a percent, growth rates for an amount",
            seed=rules.PERSISTENCE_SEED,
        ),
    )
    tests = _tests(run, computed)
    reports = background.reports
    relevant = _relevance(run, tests, reports, run.findings)
    request = _request(run, numbers, tests, relevant, reports)
    analytics = _provide(run, providers, request, analysis, background, clock, timing)
    coverage.analytics_computed = sum(1 for item in analytics if item.available)
    coverage.analytics_unavailable = sum(1 for item in analytics if not item.available)
    coverage.analytics_providers_failed = len(analysis.providers_failed)
    measures = Measures(numbers.book, numbers.calendar) if numbers.book is not None else None
    claimed: dict[str, _Claimed] = {}
    for claim in run.claims:
        own = [item for item in analytics if claim.id in item.claim_ids]
        # Reading order: the claim's own test, the part it names, the measure, then what lies
        # behind the number. The sort is stable, so each provider's order holds within a group.
        mine = [item.id for item in sorted(own, key=lambda item: READING_ORDER.get(item.kind, 2))]
        for measure in relevant[claim.id]:
            measure.analytic_ids = [
                item.id
                for item in analytics
                if item.measure == measure.key and claim.id in item.claim_ids
            ]
        pair = tests.get(claim.id)
        odds = persistence(
            claim.id,
            pair[0] if pair else None,
            claim.computed if pair else None,
            measures,
        )
        claimed[claim.id] = _Claimed(relevant[claim.id], mine, odds)
    analysis.headline = headline(
        run.claims, relevant, run.metrics, analytics, {key: pair[0] for key, pair in tests.items()}
    )
    analysis.untied_metric_ids = untied_metric_ids(run.metrics, relevant)
    analysis.analytics = analytics
    if not analysis.headline:
        analysis.headline_note = rules.NO_HEADLINE
    found, argument_claims, thesis, reasons = _model_steps(
        run,
        numbers,
        background,
        analyser,
        analytics,
        claimed,
        analysis,
        out_of_time,
        on_step,
        timing,
        clock,
    )
    for claim in run.claims:
        mine = claimed[claim.id]
        own = [c for c in found if c.claim_id == claim.id]
        argument = next((a for a in argument_claims if a.claim_id == claim.id), None)
        claim.analysis = ClaimAnalysis(
            relevant=mine.relevant,
            relevance_note="" if mine.relevant else rules.NO_MEASURE,
            analytic_ids=mine.analytic_ids,
            corollaries=own,
            corollary_flag=flag(own),
            persistence=mine.odds,
            argument=argument,
            argument_note="" if argument is not None else reasons.get(claim.id, ""),
        )
        if claim.analysis.corollary_flag:
            analysis.flags.append(f"{claim.id}: {claim.analysis.corollary_flag}")
            coverage.corollary_flags += 1
        if argument is not None and argument.lean_flag:
            analysis.flags.append(f"{claim.id}: {argument.lean_flag}")
            coverage.analysis_lean_flags += 1
    analysis.thesis = thesis
    run.analysis = analysis


def _count_corollaries(run: Run, found: Sequence[Corollary]) -> None:
    """Every proposed corollary is in exactly one count (``Coverage`` says which)."""
    coverage = run.coverage
    counted = [c for c in found if c.status in COUNTED]
    coverage.corollaries_proposed = len(found)
    coverage.corollaries_not_agreed = sum(1 for c in found if c.status == "not_agreed")
    coverage.corollaries_no_test = sum(1 for c in found if c.status == "not_computable")
    coverage.corollaries_as_expected = sum(1 for c in counted if c.result == "as_expected")
    coverage.corollaries_against = sum(1 for c in counted if c.result == "against")
    coverage.corollaries_cannot_tell = sum(1 for c in counted if c.result == "cannot_tell")
    coverage.corollaries_computed = coverage.corollaries_as_expected + coverage.corollaries_against


def _model_steps(
    run: Run,
    numbers: NumbersResult,
    background: Background,
    analyser: Analyser,
    analytics: list[Analytic],
    claimed: dict[str, _Claimed],
    analysis: Analysis,
    out_of_time: Callable[[], bool],
    on_step: Callable[[str], None],
    timing: Timing,
    clock: Callable[[], float],
) -> tuple[list[Corollary], list[ClaimArgument], ThesisArgument | None, dict[str, str]]:
    """The model requests, when there is a model and time. Whatever keeps the record from
    holding a model's argument is a reason on the analysis and one line in ``run.errors``."""
    why = ""
    if analyser.name == "none":
        why = rules.NO_MODEL_WHY
    elif run.company is None:
        why = "the company could not be read"
    elif background.proposal is None and out_of_time():
        why = rules.OUT_OF_TIME_WHY
    if why:
        analysis.corollaries_note = rules.NO_PROPOSER
        analysis.argument_note = rules.NO_ARGUMENT.format(why=why)
        run.errors.append(rules.COMPUTED_ONLY_ERROR.format(why=why))
        return [], [], None, {}
    found: list[Corollary] = []
    failures: list[str] = []
    reports = background.reports
    proposed: ProposedImplications | EngineError
    if background.proposal is None:
        proposed = EngineError(rules.OUT_OF_TIME_WHY)
    else:
        on_step("Analysing: waiting for the proposed corollaries")
        # Not waited for with a limit of its own: the request has one (its timeout).
        background.proposal.joined(None)
        proposed = background.proposal.box["out"]
        timing("corollaries: proposed by the model", background.proposal.box["seconds"], True, "")
    if isinstance(proposed, EngineError):
        analysis.corollaries_step = "failed" if background.proposal is not None else "not_asked"
        analysis.corollaries_note = rules.PROPOSE_FAILED.format(why=_why(proposed))
        failures.append(f"the corollaries: {_why(proposed)}")
    else:
        began = clock()
        facts = FactsAt(
            book=numbers.book,
            calendar=numbers.calendar,
            payload=numbers.payload,
            as_of=numbers.as_of,
            books=HistoryBooks(numbers.payload) if numbers.payload is not None else None,
            reports=reports,
            error=numbers.error or "",
        )
        newest = (
            newest_periods(numbers.book, numbers.calendar) if numbers.book is not None else None
        )
        found = corollaries(proposed.implications, facts, newest)
        analysis.corollaries_step = "answered"
        analysis.corollaries_by = answered_by(
            analyser, [rules.PROPOSE_STEP], background.answers_mark
        )
        if proposed.problems:
            dropped = "; ".join(proposed.problems)
            analysis.corollaries_note = f"Dropped from the proposal: {dropped}."
        _count_corollaries(run, found)
        timing("corollaries: computed", clock() - began, False, "")
    claims, thesis, reasons = _argue(
        run,
        analyser,
        analytics,
        claimed,
        found,
        analysis,
        failures,
        out_of_time,
        on_step,
        timing,
        clock,
    )
    if analysis.argument_by == "model":
        # Who answered the argument's own requests in this run, not the cassette at large.
        analysis.argument_detail = answered_by(
            analyser, [rules.ANALYSE_STEP, rules.CONCLUDE_STEP], background.answers_mark
        )
    if failures:
        run.errors.append(rules.MODEL_STEP_ERROR.format(why="; ".join(failures)))
    return found, claims, thesis, reasons


def _argument_text(argument: ClaimArgument) -> str:
    """A claim's audited argument as the thesis's request is shown it: its lean, its
    assessment and what decides it, each sentence that failed the audit marked with why."""

    def lines(sentences: Sequence[ArgSentence]) -> str:
        return " ".join(
            s.text + ("" if s.verified else f" [UNVERIFIED: {'; '.join(s.problems)}]")
            for s in sentences
        )

    parts = [f"Lean: {argument.lean}."]
    if argument.lean_flag:
        parts.append(argument.lean_flag)
    for title, sentences in (
        ("Assessment", argument.assessment),
        ("What decides it", argument.decides),
        ("What would change the verdict", argument.would_change),
    ):
        if sentences:
            parts.append(f"{title}: {lines(sentences)}")
    return " ".join(parts)


def _argue(
    run: Run,
    analyser: Analyser,
    analytics: list[Analytic],
    claimed: dict[str, _Claimed],
    found: Sequence[Corollary],
    analysis: Analysis,
    failures: list[str],
    out_of_time: Callable[[], bool],
    on_step: Callable[[str], None],
    timing: Timing,
    clock: Callable[[], float],
) -> tuple[list[ClaimArgument], ThesisArgument | None, dict[str, str]]:
    """The argument: one request per claim, several at once, each audited; then one for the
    thesis, shown the audited arguments. A claim whose request fails, or is not sent for want
    of time, has no argument and a reason, and the others stand; the thesis's request runs on
    what there is. Returns the claims' arguments, the thesis's, and each missing one's reason."""
    coverage = run.coverage
    brief = _brief(run, analytics, claimed, found)
    ids = [claim.id for claim in run.claims]

    def one(claim_id: str) -> ArgumentDraft | str | None:
        if out_of_time():
            return None
        try:
            return analyser.analyse_claim(brief, claim_id)
        except EngineError as exc:
            return _why(exc)

    on_step("Analysing: arguing each claim")
    began = clock()
    workers = rules.MAX_CONCURRENT_ARGUMENTS
    with ThreadPoolExecutor(max_workers=workers, thread_name_prefix="analyse") as pool:
        answers = dict(zip(ids, pool.map(one, ids), strict=True))
    timing(
        "argument: the claims",
        clock() - began,
        False,
        f"{len(ids)} request(s), up to {workers} at once",
    )
    drafts = {cid: a for cid, a in answers.items() if isinstance(a, ArgumentDraft)}
    reasons: dict[str, str] = {}
    for claim_id, answer in answers.items():
        if answer is None:
            reasons[claim_id] = rules.NO_CLAIM_ARGUMENT.format(why=rules.OUT_OF_TIME_WHY)
        elif isinstance(answer, str):
            reasons[claim_id] = rules.NO_CLAIM_ARGUMENT.format(why=f"the request failed ({answer})")
            failures.append(f"the argument about {claim_id}: {answer}")
    asked = sum(1 for answer in answers.values() if answer is not None)
    odds = [mine.odds for mine in claimed.values()]
    known = citables(run, analytics, found, odds)
    withheld = {finding.id for finding in run.unsupported_findings}
    verdicts = {claim.id: claim.verdict for claim in run.claims}
    written = [draft.claims[0] for draft in drafts.values()]
    claims, _, counts = audit_argument(written, None, known, withheld, verdicts)
    by_id = {argument.claim_id: argument for argument in claims}
    thesis: ThesisArgument | None = None
    thesis_draft: ArgumentDraft | None = None
    thesis_state = "not asked: " + rules.OUT_OF_TIME_WHY
    if not out_of_time():
        on_step("Analysing: arguing the thesis")
        arguments = tuple(
            BriefItem(cid, _argument_text(by_id[cid]) if cid in by_id else reasons[cid])
            for cid in ids
        )
        began = clock()
        try:
            thesis_draft = analyser.analyse_thesis(replace(brief, arguments=arguments))
        except EngineError as exc:
            analysis.thesis_step = "failed"
            thesis_state = f"the request failed ({_why(exc)})"
            failures.append(f"the argument about the thesis: {_why(exc)}")
        else:
            _, thesis, more = audit_argument([], thesis_draft.thesis, known, withheld, verdicts)
            counts = counts.merged(more)
            analysis.thesis_step = "answered"
            thesis_state = "answered"
        timing("argument: the thesis", clock() - began, False, "")
    elif asked:
        failures.append(f"the argument about the thesis: {rules.OUT_OF_TIME_WHY}")
    analysis.argument_claims_asked = asked
    analysis.argument_claims_answered = len(drafts)
    coverage.analysis_claims_asked = asked
    coverage.analysis_claims_answered = len(drafts)
    coverage.analysis_thesis_answered = int(thesis is not None)
    sent = asked + int(analysis.thesis_step != "not_asked")
    answered = len(drafts) + int(thesis is not None)
    if sent == 0:
        analysis.argument_step = "not_asked"
        analysis.argument_note = rules.NO_ARGUMENT.format(why=rules.OUT_OF_TIME_WHY)
        failures.append(f"the argument: {rules.OUT_OF_TIME_WHY}")
        return [], None, reasons
    if answered == 0:
        analysis.argument_step = "failed"
        first = next((why for why in answers.values() if isinstance(why, str)), thesis_state)
        analysis.argument_note = rules.NO_ARGUMENT.format(
            why=f"every request failed (the first: {first})"
        )
        return [], None, reasons
    whole = len(drafts) == len(ids) and thesis is not None
    analysis.argument_step = "answered" if whole else "partial"
    analysis.argument_by = "model"
    analysis.argument_detail = analyser.detail
    notes: list[str] = []
    if not whole:
        notes.append(
            rules.ARGUMENT_PARTIAL.format(answered=len(drafts), total=len(ids), thesis=thesis_state)
        )
    dropped = [f"{cid}: {p}" for cid, draft in drafts.items() for p in draft.problems]
    dropped += [f"thesis: {p}" for p in (thesis_draft.problems if thesis_draft else [])]
    if dropped:
        notes.append("Dropped from the answers: " + "; ".join(dropped) + ".")
    analysis.argument_note = " ".join(notes)
    coverage.analysis_sentences_written = counts.written
    coverage.analysis_sentences_verified = counts.verified
    coverage.analysis_sentences_unverified = counts.unverified
    coverage.analysis_sentences_restating = counts.restating
    coverage.analysis_sentences_cut = sum(d.cut for d in drafts.values()) + (
        thesis_draft.cut if thesis_draft else 0
    )
    coverage.analysis_unverified_no_evidence = counts.reasons["no_evidence"]
    coverage.analysis_unverified_unknown_id = counts.reasons["unknown_id"]
    coverage.analysis_unverified_disallowed_id = counts.reasons["disallowed_id"]
    coverage.analysis_unverified_number = counts.reasons["number"]
    coverage.analysis_claims_argued = sum(1 for claim in claims if claim.assessment)
    return claims, thesis, reasons
