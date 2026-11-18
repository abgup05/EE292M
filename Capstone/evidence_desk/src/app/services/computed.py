"""Compile each claim of a run and compute the compiled ones from the run's own facts.

One job, after the run has read its XBRL facts (:mod:`app.services.numbers`): every
claim goes through :func:`app.core.claimtest.compile_claim`; a compiled claim is
evaluated (:func:`app.core.claim_eval.evaluate`) from the run's
:class:`~app.core.facts.FactBook` (as of the run's date when it has one) and given its
history (:func:`app.core.claim_eval.claim_history`) from the same facts, with no
request of its own. A share of revenue reads the newest filings' tagged breakdowns,
which the run has at hand or in its cache. Nothing here asks the engine anything.

With the model parser on (a :class:`~app.core.ports.ClaimReader`), each claim is read a
second time, and a computed test counts toward the verdict only when both readings are
the same test (:func:`app.core.policy.reading_counts`); otherwise the test is still
computed and shown, with both readings, and counts as nothing.
"""

from __future__ import annotations

from collections.abc import Callable, Collection

from app.core import policy
from app.core.breakdown_models import BreakdownReport
from app.core.claim_eval import HistoryBooks, claim_history, evaluate
from app.core.claim_test_models import ClaimReading, ComputedTest
from app.core.claimtest import ClaimTest, NotNumeric, compile_claim
from app.core.models import Claim, Run
from app.core.ports import ClaimReader
from app.engines.transport import EngineError
from app.services.numbers import NumbersResult

NO_FACTS = "The run could not read the company's XBRL facts{why}, so nothing could be computed."
SHARES = ("share", "max_share")
MAX_WHY_CHARS = 320

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


def _reading(reader: str, result: ClaimTest | NotNumeric) -> ClaimReading:
    if isinstance(result, NotNumeric):
        return ClaimReading(reader=reader, canonical=policy.NO_TEST, reason=result.reason)  # type: ignore[arg-type]
    return ClaimReading(reader=reader, canonical=result.canonical)  # type: ignore[arg-type]


def _model_reading(run: Run, claim: Claim, reader: ClaimReader) -> ClaimReading:
    """The model parser's reading of ``claim``; a failure to ask is recorded, never raised."""
    try:
        return _reading(policy.MODEL_READER, reader.read(claim.text))
    except EngineError as exc:  # its message is safe to show (EngineError's contract)
        why = str(exc)[:MAX_WHY_CHARS]
        run.errors.append(policy.READER_ERROR.format(claim_id=claim.id, why=why))
        reason = policy.COMPUTED_READER_FAILED.format(why=why)
        return ClaimReading(reader="model", canonical=policy.NO_TEST, reason=reason)


def read_claims(run: Run, reader: ClaimReader | None = None) -> dict[str, ClaimTest]:
    """Read every claim's test, record the readings, and return the grammar's tests by id.

    A claim the grammar does not compile gets ``compile_note``; with ``reader``, one that
    only the model reads says so there too.
    """
    run.claim_readers = policy.GRAMMAR_READER
    if reader is not None:
        run.claim_readers = f"{policy.GRAMMAR_READER} and {policy.MODEL_READER}"
        run.claim_reader_detail = str(reader.detail or "")
    tests: dict[str, ClaimTest] = {}
    for claim in run.claims:
        compiled = compile_claim(claim.text)
        claim.readings = [_reading(policy.GRAMMAR_READER, compiled)]
        if reader is not None:
            claim.readings.append(_model_reading(run, claim, reader))
        if isinstance(compiled, ClaimTest):
            tests[claim.id] = compiled
            continue
        reason = compiled.reason.removeprefix("not compiled: ")
        claim.compile_note = policy.COMPUTED_NOT_NUMERIC.format(reason=reason)
        if reader is not None and claim.readings[1].canonical != policy.NO_TEST:
            claim.compile_note += " " + _differ(claim)
    return tests


def _differ(claim: Claim) -> str:
    grammar, model = claim.readings[0], claim.readings[1]

    def said(reading: ClaimReading) -> str:
        if reading.canonical != policy.NO_TEST:
            return reading.canonical
        return f"no test ({reading.reason})" if reading.reason else "no test"

    return policy.COMPUTED_READINGS_DIFFER.format(grammar=said(grammar), model=said(model))


def _counts(claim: Claim) -> bool:
    model = claim.readings[1].canonical if len(claim.readings) > 1 else None
    return policy.reading_counts(claim.readings[0].canonical, model)


def compute_claims(
    run: Run,
    numbers: NumbersResult,
    read_reports: ReportReader,
    reader: ClaimReader | None = None,
) -> None:
    """Set ``computed`` or ``compile_note`` on every claim, and count the outcomes.

    ``read_reports`` gives the newest filings' tagged breakdowns and any failure to read
    them; it is called only when a claim is a share of revenue. ``reader`` is the model
    parser, when it is on: a test counts only when it reads the same test as the grammar.
    """
    tests = read_claims(run, reader)
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
        claim.computed = _attributed(claim, claim.computed)
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


def _attributed(claim: Claim, computed: ComputedTest) -> ComputedTest:
    """``computed`` with who read it, and not counted when the readings differ."""
    if _counts(claim):
        read_by = [reading.reader for reading in claim.readings]
        return computed.model_copy(update={"read_by": read_by})
    note = " ".join(text for text in (_differ(claim), computed.note) if text)
    return computed.model_copy(
        update={"read_by": [policy.GRAMMAR_READER], "counted_as": "", "note": note}
    )
