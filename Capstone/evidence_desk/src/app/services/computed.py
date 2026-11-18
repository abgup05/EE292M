"""Compile each claim of a run and compute the compiled ones from the run's own facts.

One job, after the run has read its XBRL facts (:mod:`app.services.numbers`): every
claim goes through :func:`app.core.claimtest.compile_claim`; a compiled claim is
evaluated (:func:`app.core.claim_eval.evaluate`) from the run's
:class:`~app.core.facts.FactBook` (as of the run's date when it has one) and given its
history (:func:`app.core.claim_eval.claim_history`) from the same facts, with no
request of its own. A share of revenue reads the newest filings' tagged breakdowns,
which the run has at hand or in its cache. Nothing here asks the engine anything.
"""

from __future__ import annotations

from collections.abc import Callable, Collection

from app.core import policy
from app.core.breakdown_models import BreakdownReport
from app.core.claim_eval import HistoryBooks, claim_history, evaluate
from app.core.claim_test_models import ComputedTest
from app.core.claimtest import ClaimTest, NotNumeric, compile_claim
from app.core.models import Run
from app.services.numbers import NumbersResult

NO_FACTS = "The run could not read the company's XBRL facts{why}, so nothing could be computed."
SHARES = ("share", "max_share")

ReportReader = Callable[[], tuple[list[BreakdownReport], list[str]]]


def _not_computed(test: ClaimTest, reason: str) -> ComputedTest:
    return ComputedTest(
        canonical=test.canonical,
        form=test.form,
        outcome="cannot_compute",
        outcome_label=policy.COMPUTED_LABELS["cannot_compute"],
        reason=reason,
        comparison=test.op,
    )


def compute_claims(run: Run, numbers: NumbersResult, read_reports: ReportReader) -> None:
    """Set ``computed`` or ``compile_note`` on every claim, and count the outcomes.

    ``read_reports`` gives the newest filings' tagged breakdowns and any failure to read
    them; it is called only when a claim is a share of revenue.
    """
    tests: dict[str, ClaimTest] = {}
    for claim in run.claims:
        compiled = compile_claim(claim.text)
        if isinstance(compiled, NotNumeric):
            reason = compiled.reason.removeprefix("not compiled: ")
            claim.compile_note = policy.COMPUTED_NOT_NUMERIC.format(reason=reason)
        else:
            tests[claim.id] = compiled
    coverage = run.coverage
    coverage.claims_compiled = len(tests)
    if not tests:
        return
    reports: list[BreakdownReport] = []
    report_errors: list[str] = []
    if any(test.left.fn in SHARES for test in tests.values()):
        reports, report_errors = read_reports()
    books = HistoryBooks(numbers.payload) if numbers.payload is not None else None
    for claim in run.claims:
        test = tests.get(claim.id)
        if test is None:
            continue
        if numbers.book is None or books is None:
            why = f" ({numbers.error})" if numbers.error else ""
            claim.computed = _not_computed(test, NO_FACTS.format(why=why))
        else:
            result = evaluate(test, numbers.book, calendar=numbers.calendar, reports=reports)
            history, note = claim_history(test, books.payload, as_of=numbers.as_of, books=books)
            extra = " ".join(report_errors) if test.left.fn in SHARES and report_errors else ""
            claim.computed = result.model_copy(
                update={
                    "history": history,
                    "history_note": note,
                    "note": " ".join(text for text in (result.note, extra) if text),
                }
            )
        outcome = claim.computed.outcome
        coverage.computed_holds += outcome == "holds"
        coverage.computed_fails += outcome == "fails"
        coverage.computed_cannot += outcome == "cannot_compute"


def count_computed(run: Run, unassessed: Collection[str] = ()) -> None:
    """Each computed claim's verdict from its findings and its computed test.

    Called after the summary is written, so the summariser is shown the verdicts of the
    findings alone, exactly as before computed tests existed. A claim the run did not
    assess (the time limit, by id in ``unassessed``) keeps no verdict: its findings were
    never sought, and its computed test is shown on its own.
    """
    for claim in run.claims:
        if claim.computed is None or claim.id in unassessed:
            continue
        own = [finding for finding in run.findings if finding.claim_id == claim.id]
        claim.verdict = policy.claim_verdict(own, claim.computed)
