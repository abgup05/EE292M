"""The analysis of a run, after its verdicts are final: relevance, analytics, odds, corollaries
and the argued analysis.

One job, called by :func:`app.services.thesis_run.execute_run` once the computed tests have
entered the verdicts. In order:

1. relevance (:mod:`app.core.relevance`): the measures that bear on each claim, the
   thesis's headline figures, and the reported figures no claim is tied to;
2. analytics from every provider in ``providers`` (this version:
   :class:`~app.core.analytics.FactsProvider`, from the run's dated facts);
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
from app.core.claim_eval import HistoryBooks, Measures, newest_periods
from app.core.claimtest import ClaimTest
from app.core.corollaries import FactsAt, corollaries, flag
from app.core.models import Claim, Run
from app.core.persistence import persistence
from app.core.ports import Analyser, AnalysisBrief, BriefClaim, BriefItem
from app.core.relevance import claim_relevance, headline, part_names, untied_metric_ids
from app.engines.transport import EngineError
from app.services.computed import Computed
from app.services.numbers import NumbersResult

MAX_WHY_CHARS = 320
MAX_FINDINGS_SHOWN = 6
MAX_QUOTE_CHARS = 300
DEFAULT_PROVIDERS: tuple[AnalyticsProvider, ...] = (FactsProvider(),)


@dataclass(frozen=True)
class _Claimed:
    """One claim's relevance, analytics and odds, before any model is asked."""

    relevant: list[RelevantMeasure]
    analytic_ids: list[str]
    odds: Persistence


def _why(exc: Exception) -> str:
    # An EngineError's message is safe to show (its contract); it is cut, never echoed whole.
    return str(exc)[:MAX_WHY_CHARS] or exc.__class__.__name__


def _provide(
    run: Run, providers: Sequence[AnalyticsProvider], request: AnalyticsRequest
) -> tuple[list[Analytic], list[str]]:
    analytics: list[Analytic] = []
    names: list[str] = []
    for provider in providers:
        names.append(provider.name)
        try:
            analytics += provider.provide(request)
        except Exception as exc:  # a provider's failure is recorded, and the others still run
            run.errors.append(
                f"The analytics provider {provider.name} failed ({exc.__class__.__name__}); "
                "its analytics are missing."
            )
    return analytics, names


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
    return f"{item.label}: {item.display}. {item.reading}"


def _brief(
    run: Run,
    analytics: Sequence[Analytic],
    claimed: dict[str, _Claimed],
    found: Sequence[Corollary],
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
        claims.append(
            BriefClaim(
                id=claim.id,
                text=claim.text,
                verdict=claim.verdict.value if claim.verdict else "none",
                test=_test_line(claim),
                findings=tuple(
                    BriefItem(
                        f.id,
                        f"[{f.stance.value}] {f.statement}"
                        + (f' Quote: "{quotes[f.id][:MAX_QUOTE_CHARS]}"' if f.id in quotes else ""),
                    )
                    for f in findings
                ),
                analytics=tuple(
                    BriefItem(i, _analytic_text(by_id[i]))
                    for i in mine.analytic_ids
                    if by_id[i].available
                ),
                corollaries=tuple(
                    BriefItem(
                        c.id,
                        f"{c.sentence} (expected to {c.expect} if the claim holds; read by "
                        f"{c.read_by}): "
                        + (
                            f"{c.computed.bound or c.computed.canonical}: "
                            f"{c.computed.outcome_label}, {c.result_label}."
                            if c.computed is not None
                            else "not computed."
                        ),
                    )
                    for c in found
                    if c.claim_id == claim.id
                ),
                odds=(
                    (BriefItem(odds.id, odds.note or odds.warning),)
                    if odds.applicable and (odds.note or odds.warning)
                    else ()
                ),
            )
        )
    thesis_wide = tuple(
        BriefItem(item.id, _analytic_text(item))
        for item in analytics
        if item.available and not item.claim_ids
    )
    figures = tuple(
        BriefItem(m.id, f"{m.label}, {m.period_label}: {m.display}")
        for m in run.metrics
        if m.value is not None
    )[: rules.MAX_METRICS_SHOWN]
    events = tuple(
        BriefItem(
            e.id,
            f"8-K filed {e.filed_date}; "
            + "; ".join(f"Item {i.number} {i.title}" for i in e.items)
            + (f" (categories: {', '.join(e.categories)})" if e.categories else ""),
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
        analytics=thesis_wide,
        figures=figures,
        events=events,
    )


def analyse_run(
    run: Run,
    numbers: NumbersResult,
    computed: Computed,
    analyser: Analyser,
    *,
    providers: Sequence[AnalyticsProvider] = DEFAULT_PROVIDERS,
    out_of_time: Callable[[], bool] = lambda: False,
    on_step: Callable[[str], None] = lambda step: None,
) -> None:
    """Set ``run.analysis`` and each claim's ``analysis``, and count them (see the module
    docstring). ``on_step`` is told before each model request, to show progress."""
    coverage = run.coverage
    tests: dict[str, tuple[ClaimTest, object]] = {}
    for claim in run.claims:
        test = computed.tests.get(claim.id)
        if test is not None and claim.computed is not None:
            tests[claim.id] = (test, claim.computed)
    parts = part_names(computed.reports)
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
        tests={claim_id: pair for claim_id, pair in tests.items()},  # type: ignore[misc]
        reports=computed.reports,
        error=numbers.error or "",
    )
    analytics, providers_used = _provide(run, providers, request)
    coverage.analytics_computed = sum(1 for item in analytics if item.available)
    measures = Measures(numbers.book, numbers.calendar) if numbers.book is not None else None
    claimed: dict[str, _Claimed] = {}
    for claim in run.claims:
        mine = [item.id for item in analytics if claim.id in item.claim_ids]
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
    analysis = Analysis(
        headline=headline(run.claims, relevant, run.metrics, analytics),
        untied_metric_ids=untied_metric_ids(run.metrics, relevant),
        untied_note=rules.UNTIED,
        analytics=analytics,
        providers=providers_used,
        corollary_rule=rules.COROLLARY_RULE,
        persistence_method=rules.PERSISTENCE_METHOD.format(
            paths=rules.PERSISTENCE_PATHS,
            horizon=rules.PERSISTENCE_HORIZON,
            changes="N",
            step="differences in points for a percent, growth rates for an amount",
            seed=rules.PERSISTENCE_SEED,
        ),
    )
    if not analysis.headline:
        analysis.headline_note = rules.NO_HEADLINE
    found, argument_claims, thesis = _model_steps(
        run, numbers, computed, analyser, analytics, claimed, analysis, out_of_time, on_step
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
        if argument is not None and argument.lean_flag:
            analysis.flags.append(f"{claim.id}: {argument.lean_flag}")
            coverage.analysis_lean_flags += 1
    analysis.thesis = thesis
    run.analysis = analysis


def _model_steps(
    run: Run,
    numbers: NumbersResult,
    computed: Computed,
    analyser: Analyser,
    analytics: list[Analytic],
    claimed: dict[str, _Claimed],
    analysis: Analysis,
    out_of_time: Callable[[], bool],
    on_step: Callable[[str], None],
) -> tuple[list[Corollary], list[ClaimArgument], ThesisArgument | None]:
    """The two model requests, when there is a model and time; each failure recorded."""
    coverage = run.coverage
    why = ""
    if analyser.name == "none":
        why = rules.NO_MODEL_WHY
    elif out_of_time():
        why = rules.OUT_OF_TIME_WHY
    elif run.company is None:
        why = "the company could not be read"
    if why:
        analysis.corollaries_note = rules.NO_PROPOSER.format(why=why)
        analysis.argument_note = rules.NO_ARGUMENT.format(why=why)
        return [], [], None
    found: list[Corollary] = []
    on_step("Analysing: proposing corollaries")
    try:
        proposed = analyser.propose(_brief(run, analytics, claimed, []))
    except EngineError as exc:
        analysis.corollaries_note = rules.PROPOSE_FAILED.format(why=_why(exc))
        run.errors.append(rules.PROPOSE_FAILED_ERROR.format(why=_why(exc)))
    else:
        facts = FactsAt(
            book=numbers.book,
            calendar=numbers.calendar,
            payload=numbers.payload,
            as_of=numbers.as_of,
            books=HistoryBooks(numbers.payload) if numbers.payload is not None else None,
            reports=computed.reports,
            error=numbers.error or "",
        )
        newest = (
            newest_periods(numbers.book, numbers.calendar) if numbers.book is not None else None
        )
        found = corollaries(proposed.implications, facts, newest)
        analysis.corollaries_by = analyser.detail
        if proposed.problems:
            dropped = "; ".join(proposed.problems)
            analysis.corollaries_note = f"Dropped from the proposal: {dropped}."
        coverage.corollaries_proposed = len(found)
        coverage.corollaries_as_expected = sum(1 for c in found if c.result == "as_expected")
        coverage.corollaries_against = sum(1 for c in found if c.result == "against")
        coverage.corollaries_computed = (
            coverage.corollaries_as_expected + coverage.corollaries_against
        )
    if out_of_time():
        analysis.argument_note = rules.NO_ARGUMENT.format(why=rules.OUT_OF_TIME_WHY)
        return found, [], None
    on_step("Analysing: writing the argument")
    try:
        draft = analyser.analyse(_brief(run, analytics, claimed, found))
    except EngineError as exc:
        analysis.argument_note = rules.NO_ARGUMENT.format(why=f"the request failed ({_why(exc)})")
        run.errors.append(rules.ANALYSE_FAILED_ERROR.format(why=_why(exc)))
        return found, [], None
    odds = [mine.odds for mine in claimed.values()]
    known = citables(run, analytics, found, odds)
    withheld = {finding.id for finding in run.unsupported_findings}
    verdicts = {claim.id: claim.verdict for claim in run.claims}
    claims, thesis, counts = audit_argument(draft.claims, draft.thesis, known, withheld, verdicts)
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
    return found, claims, thesis
