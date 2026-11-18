"""Corollaries: implications a model proposes for a claim, read and computed by code.

Pure. A proposing model (:mod:`app.engines.analyser`, step "propose") writes, for each
claim, a few observable implications: each a sentence in the claim-test language, the
outcome it should have if the claim holds, and (unless
:data:`~app.core.analysis_policy.PROPOSE_TYPED_FORM` is off) the typed test it means,
validated by :func:`app.core.claim_reading.from_reading`. Here each is read by two readers,
the grammar (:func:`app.core.claimtest.compile_claim`) and the proposer's typed form, and
compared in normal form (:func:`app.core.claim_normal.normal_form`):

- the same test: "agreed", computed;
- one reader only: computed and labelled with that reader ("the proposing model only");
- different tests: "not agreed"; the proposer's test is computed and both are shown, and it
  counts toward nothing;
- neither: shown as proposed and not computable.

Two readers is weaker than the two-of-three rule the thesis's own claims are read under
(the model readers are not asked: the proposer is one of the two). A corollary never moves
a verdict; a claim most of whose counted corollaries come out against it is flagged.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date
from typing import Any, Literal

from app.core import analysis_policy as rules
from app.core import policy
from app.core.analysis_models import Corollary, CorollaryStatus
from app.core.breakdown_models import BreakdownReport
from app.core.claim_eval import HistoryBooks, claim_history, evaluate
from app.core.claim_normal import Newest, normal_form
from app.core.claim_test_models import ComputedTest
from app.core.claimtest import ClaimTest, NotNumeric, compile_claim
from app.core.facts import FactBook
from app.core.periods import FiscalCalendar

COUNTED: tuple[CorollaryStatus, ...] = ("agreed", "grammar_only", "proposer_only")


@dataclass(frozen=True)
class Implication:
    """One implication as the proposing model wrote it, its typed form validated.

    ``test`` is the proposer's typed test, a :class:`NotNumeric` saying why it did not
    validate, or None when the typed form was not asked for.
    """

    claim_id: str
    sentence: str
    expect: Literal["holds", "fails"]
    why: str
    test: ClaimTest | NotNumeric | None


@dataclass(frozen=True)
class FactsAt:
    """The facts a corollary is computed from: the run's book, as of its date."""

    book: FactBook | None
    calendar: FiscalCalendar | None
    payload: dict[str, Any] | None
    as_of: date | None
    books: HistoryBooks | None
    reports: Sequence[BreakdownReport] = ()
    error: str = ""


def _reason(result: ClaimTest | NotNumeric | None) -> str:
    if result is None:
        return "no typed form was asked for"
    return result.reason if isinstance(result, NotNumeric) else ""


def read(
    implication: Implication, newest: Newest | None
) -> tuple[CorollaryStatus, ClaimTest | None, str, str, str, str]:
    """(status, the test to compute, grammar canonical, its reason, proposer canonical, its
    reason) for one implication."""
    grammar = compile_claim(implication.sentence)
    proposer = implication.test
    g_test = grammar if isinstance(grammar, ClaimTest) else None
    p_test = proposer if isinstance(proposer, ClaimTest) else None
    g_text = g_test.canonical if g_test else policy.NO_TEST
    p_text = p_test.canonical if p_test else policy.NO_TEST
    reasons = (_reason(grammar), _reason(proposer))
    if g_test and p_test:
        if normal_form(g_test, newest) == normal_form(p_test, newest):
            return "agreed", g_test, g_text, "", p_text, ""
        return "not_agreed", p_test, g_text, "", p_text, ""
    if g_test:
        return "grammar_only", g_test, g_text, "", p_text, reasons[1]
    if p_test:
        return "proposer_only", p_test, g_text, reasons[0], p_text, ""
    return "not_computable", None, g_text, reasons[0], p_text, reasons[1]


def compute(test: ClaimTest, facts: FactsAt) -> ComputedTest:
    """``test`` computed from the run's facts, with its history."""
    if facts.book is None or facts.payload is None:
        why = f" ({facts.error})" if facts.error else ""
        return ComputedTest(
            canonical=test.canonical,
            form=test.form,
            outcome="cannot_compute",
            outcome_label=policy.COMPUTED_LABELS["cannot_compute"],
            reason=f"The run could not read the company's XBRL facts{why}.",
            comparison=test.op,
        )
    result = evaluate(test, facts.book, calendar=facts.calendar, reports=facts.reports)
    history, note = claim_history(test, facts.payload, as_of=facts.as_of, books=facts.books)
    return result.model_copy(update={"history": history, "history_note": note})


def corollaries(
    implications: Sequence[Implication], facts: FactsAt, newest: Newest | None
) -> list[Corollary]:
    """Every implication read, computed when a reader read a test, and compared with what
    the claim implies. Ids are ``cor:<claim>:<n>``, numbered per claim from 1."""
    out: list[Corollary] = []
    numbers: dict[str, int] = {}
    for implication in implications:
        numbers[implication.claim_id] = numbers.get(implication.claim_id, 0) + 1
        status, test, g_text, g_why, p_text, p_why = read(implication, newest)
        computed = compute(test, facts) if test is not None else None
        result = "not_computed"
        if computed is not None:
            if computed.outcome == "cannot_compute":
                result = "cannot_tell"
            else:
                result = "as_expected" if computed.outcome == implication.expect else "against"
        out.append(
            Corollary(
                id=f"cor:{implication.claim_id}:{numbers[implication.claim_id]}",
                claim_id=implication.claim_id,
                sentence=implication.sentence,
                expect=implication.expect,
                why=implication.why,
                grammar=g_text,
                grammar_reason=g_why,
                proposer=p_text,
                proposer_reason=p_why,
                status=status,
                read_by=rules.READ_BY[status],
                computed=computed,
                result=result,  # type: ignore[arg-type]
                result_label=rules.RESULT_LABELS[result],
            )
        )
    return out


def flag(items: Sequence[Corollary]) -> str:
    """The claim's flag when most of its counted, computed corollaries came out against it."""
    known = [c for c in items if c.status in COUNTED and c.result in ("as_expected", "against")]
    against = sum(1 for c in known if c.result == "against")
    if len(known) >= rules.COROLLARY_FLAG_MIN and against * 2 > len(known):
        return rules.COROLLARY_FLAG.format(against=against, known=len(known))
    return ""
