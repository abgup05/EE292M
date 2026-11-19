"""Compile each claim of a run and compute the compiled ones from the run's own facts.

One job, after the run has read its XBRL facts (:mod:`app.services.numbers`): every
claim goes through :func:`app.core.claimtest.compile_claim`; a compiled claim is
evaluated (:func:`app.core.claim_eval.evaluate`) from the run's
:class:`~app.core.facts.FactBook` (as of the run's date when it has one) and given its
history (:func:`app.core.claim_eval.claim_history`) from the same facts, with no
request of its own. A share of revenue reads the newest filings' tagged breakdowns,
which the run has at hand or in its cache. Nothing here asks the engine anything.

With model readers on (one or two :class:`~app.core.ports.ClaimReader`, different models),
each claim is read again by each, every reading is put in one normal form
(:func:`app.core.claim_normal.normal_form`) and the counting rule
(:func:`app.core.policy.reading_agreement`) decides: a test at least two readers reach is
computed and counts (the grammar's own writing of it when the grammar is one of them); a
different test from the third reader is shown as a dissent; when no two agree, the
grammar's test (if it read one) is computed and shown with every reading, and counts as
nothing. With the grammar alone a compiled test counts as before, and the run says that is
one reader.
"""

from __future__ import annotations

from collections.abc import Callable, Collection, Sequence
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field

from app.core import analysis_policy as analysis_rules
from app.core import policy
from app.core.breakdown_models import BreakdownReport
from app.core.claim_eval import HistoryBooks, claim_history, evaluate, newest_periods
from app.core.claim_normal import Newest, normal_form
from app.core.claim_test_models import ClaimReading, ComputedTest
from app.core.claimtest import ClaimTest, NotNumeric, compile_claim
from app.core.models import Claim, Run
from app.core.ports import ClaimReader
from app.engines.transport import EngineError, answered_by, answers_mark
from app.services.numbers import NumbersResult

NO_FACTS = "The run could not read the company's XBRL facts{why}, so nothing could be computed."
SHARES = ("share", "max_share")
MAX_WHY_CHARS = 320

ReportReader = Callable[[], tuple[list[BreakdownReport], list[str]]]
Readers = ClaimReader | Sequence[ClaimReader] | None


@dataclass(frozen=True)
class Computed:
    """What computing the claims leaves for the analysis: each computed claim's test, by
    claim id, and the tagged breakdowns read for them (none when no test needed one)."""

    tests: dict[str, ClaimTest] = field(default_factory=dict)
    reports: list[BreakdownReport] = field(default_factory=list)


@dataclass(frozen=True)
class ReadClaim:
    """The test a claim's readings lead to computing, and the rule's conclusion."""

    test: ClaimTest
    agreement: policy.Agreement
    reader: str  # whose writing of the test is computed


def _not_computed(test: ClaimTest, reason: str) -> ComputedTest:
    return ComputedTest(
        canonical=test.canonical,
        form=test.form,
        outcome="cannot_compute",
        outcome_label=policy.COMPUTED_LABELS["cannot_compute"],
        reason=reason,
        comparison=test.op,
    )


def _as_list(readers: Readers) -> list[ClaimReader]:
    if readers is None:
        return []
    if isinstance(readers, Sequence):
        return list(readers)
    return [readers]


def _reading(reader: str, result: ClaimTest | NotNumeric, newest: Newest) -> ClaimReading:
    if isinstance(result, NotNumeric):
        return ClaimReading(
            reader=reader,  # type: ignore[arg-type]
            canonical=policy.NO_TEST,
            reason=result.reason,
            normal_form=policy.NO_TEST,
        )
    return ClaimReading(
        reader=reader,  # type: ignore[arg-type]
        canonical=result.canonical,
        normal_form=normal_form(result, newest),
    )


def _model_read(claim: Claim, reader: ClaimReader) -> tuple[ClaimTest | NotNumeric, str]:
    """A model reader's reading of ``claim`` and the error line to record ("" for none); a
    failure to ask is returned as a reading that says so, never raised."""
    try:
        return reader.read(claim.text), ""
    except EngineError as exc:  # its message is safe to show (EngineError's contract)
        why = str(exc)[:MAX_WHY_CHARS]
        return (
            NotNumeric(policy.COMPUTED_READER_FAILED.format(why=why)),
            policy.READER_ERROR.format(claim_id=claim.id, why=why),
        )


def _model_reads(
    run: Run, models: Sequence[ClaimReader]
) -> dict[tuple[str, str], ClaimTest | NotNumeric]:
    """Every model reader's reading of every claim, by (claim id, reader name). The requests
    share nothing, so several are sent at once; the readings and any error lines are put in
    claim and reader order whatever order the answers came in."""
    pairs = [(claim, reader) for claim in run.claims for reader in models]
    if not pairs:
        return {}
    with ThreadPoolExecutor(
        max_workers=analysis_rules.MAX_CONCURRENT_READS, thread_name_prefix="read"
    ) as pool:
        answers = list(pool.map(lambda pair: _model_read(*pair), pairs))
    run.errors.extend(error for _, error in answers if error)
    return {
        (claim.id, reader.name): reading
        for (claim, reader), (reading, _) in zip(pairs, answers, strict=True)
    }


def read_claims(
    run: Run, readers: Readers = None, newest: Newest | None = None
) -> dict[str, ReadClaim]:
    """Read every claim with every reader, record the readings, and say what to compute.

    ``newest`` (the newest fiscal year and quarter of the facts) lets a named period
    compare equal to the default one in the normal form. A claim with nothing to compute
    gets ``compile_note``: why the grammar read no test, and every other reading when a
    model read one.
    """
    models = _as_list(readers)
    names = [policy.GRAMMAR_READER, *(reader.name for reader in models)]
    run.claim_readers = names[0] if len(names) == 1 else f"{', '.join(names[:-1])} and {names[-1]}"
    run.claim_reading_rule = policy.reading_rule(names)
    marks = [answers_mark(reader) for reader in models]
    at = newest or Newest()
    to_compute: dict[str, ReadClaim] = {}
    read = _model_reads(run, models)
    if models:
        # Each reader's own answers in this run: a cassette may hold other readers' too.
        run.claim_reader_detail = "; ".join(
            answered_by(reader, [str(getattr(reader, "step", ""))], mark)
            for reader, mark in zip(models, marks, strict=True)
        )
    for claim in run.claims:
        compiled = compile_claim(claim.text)
        results: dict[str, ClaimTest | NotNumeric] = {policy.GRAMMAR_READER: compiled}
        for reader in models:
            results[reader.name] = read[(claim.id, reader.name)]
        claim.readings = [_reading(name, result, at) for name, result in results.items()]
        agreement = policy.reading_agreement({r.reader: r.normal_form for r in claim.readings})
        chosen = agreement.agreeing[0] if agreement.counts else policy.GRAMMAR_READER
        test = results[chosen]
        if isinstance(test, ClaimTest):
            to_compute[claim.id] = ReadClaim(test, agreement, chosen)
            continue
        reason = test.reason.removeprefix("not compiled: ")
        claim.compile_note = policy.COMPUTED_NOT_NUMERIC.format(reason=reason)
        if any(r.canonical != policy.NO_TEST for r in claim.readings[1:]):
            claim.compile_note += " " + _differ(claim.readings)
    return to_compute


def _said(reading: ClaimReading) -> str:
    if reading.canonical != policy.NO_TEST:
        return reading.canonical
    return f"no test ({reading.reason})" if reading.reason else "no test"


def _readings_text(readings: Sequence[ClaimReading], *, capital: bool = True) -> str:
    """ "The grammar read X; the model read Y", in reading order."""
    parts = [f"{policy.READER_WORDS.get(r.reader, r.reader)} read {_said(r)}" for r in readings]
    text = "; ".join(parts)
    return text[:1].upper() + text[1:] if capital else text


def _differ(readings: Sequence[ClaimReading]) -> str:
    return policy.COMPUTED_READINGS_DIFFER.format(readings=_readings_text(readings))


def compute_claims(
    run: Run,
    numbers: NumbersResult,
    read_reports: ReportReader,
    reader: Readers = None,
    read_part_reports: ReportReader | None = None,
) -> Computed:
    """Set ``computed`` or ``compile_note`` on every claim, and count the outcomes.

    ``read_reports`` gives the newest filings' tagged breakdowns and any failure to read
    them; it is called only when a test is a share of revenue. ``read_part_reports`` gives
    them with the breakdowns only a claim test reads (a segment's operating income), and
    is called only when a test names a part (``read_reports`` stands in when it is None).
    ``reader`` is the model reader, or the two, when they are on (the counting rule).
    Returns each computed claim's test and the breakdowns read (:class:`Computed`).
    """
    newest = newest_periods(numbers.book, numbers.calendar) if numbers.book is not None else None
    tests = read_claims(run, reader, newest)
    coverage = run.coverage
    coverage.claims_compiled = len(tests)
    if not tests:
        return Computed()
    reports: list[BreakdownReport] = []
    report_errors: list[str] = []
    terms = [term for read in tests.values() for term in read.test.terms]
    if any(term.axis for term in terms):
        reports, report_errors = (read_part_reports or read_reports)()
    elif any(term.fn in SHARES for term in terms):
        reports, report_errors = read_reports()
    books = HistoryBooks(numbers.payload) if numbers.payload is not None else None
    for claim in run.claims:
        read = tests.get(claim.id)
        if read is None:
            continue
        test = read.test
        if numbers.book is None or books is None:
            why = f" ({numbers.error})" if numbers.error else ""
            claim.computed = _not_computed(test, NO_FACTS.format(why=why))
        else:
            result = evaluate(test, numbers.book, calendar=numbers.calendar, reports=reports)
            history, note = claim_history(test, books.payload, as_of=numbers.as_of, books=books)
            extra = " ".join(report_errors) if test.from_filing and report_errors else ""
            claim.computed = result.model_copy(
                update={
                    "history": history,
                    "history_note": note,
                    "note": " ".join(text for text in (result.note, extra) if text),
                }
            )
        claim.computed = _attributed(claim, claim.computed, read)
        outcome = claim.computed.outcome
        coverage.computed_holds += outcome == "holds"
        coverage.computed_fails += outcome == "fails"
        coverage.computed_cannot += outcome == "cannot_compute"
    return Computed({claim_id: read.test for claim_id, read in tests.items()}, reports)


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


def _attributed(claim: Claim, computed: ComputedTest, read: ReadClaim) -> ComputedTest:
    """``computed`` with who read it and the rule's conclusion; not counted unless it counts."""
    agreement = read.agreement
    update: dict[str, object] = {
        "agreement": agreement.conclusion,
        "agreement_label": policy.AGREEMENT_LABELS[agreement.conclusion],
    }
    if agreement.counts:
        dissent = [r for r in claim.readings if r.reader in agreement.dissenting]
        note = computed.note
        if dissent:
            said = policy.COMPUTED_DISSENT.format(readings=_readings_text(dissent, capital=False))
            note = " ".join(text for text in (said, computed.note) if text)
        update |= {"read_by": list(agreement.agreeing), "dissent": dissent, "note": note}
        return computed.model_copy(update=update)
    note = " ".join(text for text in (_differ(claim.readings), computed.note) if text)
    update |= {"read_by": [read.reader], "counted_as": "", "note": note}
    return computed.model_copy(update=update)
