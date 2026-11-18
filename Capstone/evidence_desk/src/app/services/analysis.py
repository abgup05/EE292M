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
from collections.abc import Callable, Sequence
from dataclasses import dataclass

from app.core import analysis_policy as rules
from app.core.analysis_audit import audit_argument, citables
from app.core.analysis_models import (
    Analysis,
    Analytic,
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
from app.core.ports import Analyser, AnalysisBrief, BriefClaim, BriefItem, SourceError
from app.core.relevance import claim_relevance, headline, part_names, untied_metric_ids
from app.engines.transport import EngineError
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


def _call(provider: AnalyticsProvider, request: AnalyticsRequest) -> list[Analytic] | str:
    """The provider's analytics, or why it gave none. A provider with ``budget_seconds`` runs
    in a thread of its own and is waited for that long: past it the run goes on without it,
    and the thread is left to finish what it is reading (what it keeps on disk is there for
    the next run). A provider is code outside this module, so any failure of one is caught
    here and logged with its trace; a :class:`SourceError` carries a message safe to show."""
    box: dict[str, list[Analytic] | str] = {}

    def work() -> None:
        try:
            box["out"] = provider.provide(request)
        except SourceError as exc:
            box["out"] = _why(exc)
        except Exception as exc:  # noqa: BLE001 - see the docstring
            log.exception("The analytics provider %s failed", provider.name)
            box["out"] = f"it failed ({exc.__class__.__name__})"

    budget = getattr(provider, "budget_seconds", None)
    if budget is None:
        work()
        return box["out"]
    thread = threading.Thread(target=work, name=f"provider-{provider.name}", daemon=True)
    thread.start()
    thread.join(budget)
    if "out" not in box:
        return rules.PROVIDER_OUT_OF_TIME.format(seconds=budget)
    return box["out"]


def _provide(
    run: Run,
    providers: Sequence[AnalyticsProvider],
    request: AnalyticsRequest,
    analysis: Analysis,
    out_of_time: Callable[[], bool],
) -> list[Analytic]:
    """Every provider's analytics. One that gives nothing is named in
    ``providers_failed`` with its reason, gets a line in ``run.errors``, and the others
    still run; one with a time budget is not started once the run's own time is up."""
    analytics: list[Analytic] = []
    for provider in providers:
        analysis.providers.append(provider.name)
        budgeted = getattr(provider, "budget_seconds", None) is not None
        found = rules.OUT_OF_TIME_WHY if budgeted and out_of_time() else _call(provider, request)
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
    computed: Computed, read_reports: ReportReader | None, analysis: Analysis
) -> list[BreakdownReport]:
    """The tagged breakdowns the parts are read from: those a computed test already read, else
    the newest filings' own, read here; a failure is a note, never an error."""
    reports = list(computed.reports)
    errors: list[str] = []
    if not reports and read_reports is not None:
        reports, errors = read_reports()
    if reports:
        read = " and ".join(
            f"the {report.filing.form} filed {report.filing.filed_date}" for report in reports
        )
        analysis.breakdowns_note = " ".join([f"Parts are read from the tags of {read}.", *errors])
    else:
        why = " ".join(errors) or "No filing's tagged breakdowns were read."
        analysis.breakdowns_note = f"No part of the business could be read: {why}"
    return reports


def analyse_run(
    run: Run,
    numbers: NumbersResult,
    computed: Computed,
    analyser: Analyser,
    *,
    providers: Sequence[AnalyticsProvider] = DEFAULT_PROVIDERS,
    read_reports: ReportReader | None = None,
    out_of_time: Callable[[], bool] = lambda: False,
    on_step: Callable[[str], None] = lambda step: None,
) -> None:
    """Set ``run.analysis`` and each claim's ``analysis``, and count them (see the module
    docstring). ``read_reports`` reads the tagged breakdowns of the newest filings the run
    read, and is called only when no computed test read them. ``on_step`` is told before
    each model request, to show progress."""
    coverage = run.coverage
    analysis = Analysis(
        untied_note=rules.UNTIED,
        corollary_rule=rules.COROLLARY_RULE,
        persistence_method=rules.PERSISTENCE_METHOD.format(
            paths=rules.PERSISTENCE_PATHS,
            horizon=rules.PERSISTENCE_HORIZON,
            changes="N",
            step="differences in points for a percent, growth rates for an amount",
            seed=rules.PERSISTENCE_SEED,
        ),
    )
    tests: dict[str, tuple[ClaimTest, ComputedTest]] = {}
    for claim in run.claims:
        test = computed.tests.get(claim.id)
        if test is not None and claim.computed is not None:
            tests[claim.id] = (test, claim.computed)
    reports = _reports(computed, read_reports, analysis)
    parts = part_names(reports)
    relevant = {
        claim.id: claim_relevance(
            claim,
            tests[claim.id][0] if claim.id in tests else None,
            run.findings,
            run.metrics,
            parts,
        )
        for claim in run.claims
    }
    request = AnalyticsRequest(
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
    analytics = _provide(run, providers, request, analysis, out_of_time)
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
    found, argument_claims, thesis = _model_steps(
        run, numbers, reports, analyser, analytics, claimed, analysis, out_of_time, on_step
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
    reports: Sequence[BreakdownReport],
    analyser: Analyser,
    analytics: list[Analytic],
    claimed: dict[str, _Claimed],
    analysis: Analysis,
    out_of_time: Callable[[], bool],
    on_step: Callable[[str], None],
) -> tuple[list[Corollary], list[ClaimArgument], ThesisArgument | None]:
    """The two model requests, when there is a model and time. Whatever keeps the record from
    holding a model's argument is a reason on the analysis and one line in ``run.errors``."""
    coverage = run.coverage
    why = ""
    if analyser.name == "none":
        why = rules.NO_MODEL_WHY
    elif out_of_time():
        why = rules.OUT_OF_TIME_WHY
    elif run.company is None:
        why = "the company could not be read"
    if why:
        analysis.corollaries_note = rules.NO_PROPOSER
        analysis.argument_note = rules.NO_ARGUMENT.format(why=why)
        run.errors.append(rules.COMPUTED_ONLY_ERROR.format(why=why))
        return [], [], None
    found: list[Corollary] = []
    failures: list[str] = []
    on_step("Analysing: proposing corollaries")
    try:
        names = list(dict.fromkeys(label for _, label in part_names(reports)))
        proposed = analyser.propose(_brief(run, analytics, claimed, [], names))
    except EngineError as exc:
        analysis.corollaries_step = "failed"
        analysis.corollaries_note = rules.PROPOSE_FAILED.format(why=_why(exc))
        failures.append(f"the corollaries: {_why(exc)}")
    else:
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
        analysis.corollaries_by = analyser.detail
        if proposed.problems:
            dropped = "; ".join(proposed.problems)
            analysis.corollaries_note = f"Dropped from the proposal: {dropped}."
        _count_corollaries(run, found)
    draft = None
    if out_of_time():
        analysis.argument_note = rules.NO_ARGUMENT.format(why=rules.OUT_OF_TIME_WHY)
        failures.append(f"the argument: {rules.OUT_OF_TIME_WHY}")
    else:
        on_step("Analysing: writing the argument")
        try:
            draft = analyser.analyse(_brief(run, analytics, claimed, found))
        except EngineError as exc:
            analysis.argument_step = "failed"
            analysis.argument_note = rules.NO_ARGUMENT.format(
                why=f"the request failed ({_why(exc)})"
            )
            failures.append(f"the argument: {_why(exc)}")
    if failures:
        run.errors.append(rules.MODEL_STEP_ERROR.format(why="; ".join(failures)))
    if draft is None:
        return found, [], None
    odds = [mine.odds for mine in claimed.values()]
    known = citables(run, analytics, found, odds)
    withheld = {finding.id for finding in run.unsupported_findings}
    verdicts = {claim.id: claim.verdict for claim in run.claims}
    claims, thesis, counts = audit_argument(draft.claims, draft.thesis, known, withheld, verdicts)
    analysis.argument_step = "answered"
    analysis.argument_by = "model"
    analysis.argument_detail = analyser.detail
    if draft.problems:
        analysis.argument_note = "Dropped from the answer: " + "; ".join(draft.problems) + "."
    coverage.analysis_sentences_written = counts.written
    coverage.analysis_sentences_verified = counts.verified
    coverage.analysis_sentences_unverified = counts.unverified
    coverage.analysis_sentences_cut = draft.cut
    coverage.analysis_unverified_no_evidence = counts.reasons["no_evidence"]
    coverage.analysis_unverified_unknown_id = counts.reasons["unknown_id"]
    coverage.analysis_unverified_disallowed_id = counts.reasons["disallowed_id"]
    coverage.analysis_unverified_number = counts.reasons["number"]
    coverage.analysis_claims_argued = sum(1 for claim in claims if claim.assessment)
    return found, claims, thesis
