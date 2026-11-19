"""What may carry a number in the argued analysis (seventh referee, finding 1).

Only evidence: a verified finding's quotes and cited figures, an analytic's value, inputs
and reading, a computed test's operands and result, a reported figure, an event's text.
Not the claim's own words, not the sentence a model wrote for a corollary. A threshold (a
computed test's constant, a condition's own) is a third thing: a sentence that restates
one is not failed for it, and the record says, per sentence, that it did.
"""

from __future__ import annotations

from datetime import UTC, datetime

from app.core.analysis_audit import AuditCounts, audit_sentence, citables
from app.core.analysis_models import Analytic, AnalyticInput, ArgSentence, Condition, Corollary
from app.core.claim_test_models import ComputedTest, Operand
from app.core.event_models import Event
from app.core.models import Claim, Run, RunStatus, ThesisRequest

WHEN = datetime(2026, 11, 19, tzinfo=UTC)


def _margin(quarter: str, value: float) -> Operand:
    return Operand(
        term=f"gross_margin[{quarter}]",
        label=f"Gross margin, {quarter}",
        value=value,
        unit="percent",
        display=f"{value:.1f}%",
        formula="72,142 ÷ 96,221; USD millions",
    )


def _threshold(percent: int) -> Operand:
    display = f"{percent}%"
    return Operand(
        term=display, label="the threshold", value=float(percent), unit="percent", display=display
    )


def _single(quarter: str, value: float, percent: int = 70) -> ComputedTest:
    return ComputedTest(
        canonical=f"gross_margin[Q] > {percent}%",
        form="threshold",
        bound=f"gross_margin[{quarter}] > {percent}%",
        outcome="holds",
        outcome_label="Holds",
        comparison=">",
        left=_margin(quarter, value),
        right=_threshold(percent),
        operands=[_margin(quarter, value)],
        arithmetic=[
            f"gross_margin[{quarter}] = 72,142 ÷ 96,221; USD millions = {value:.1f}%",
            f"{value:.1f}% > {percent}%: holds",
        ],
        margin=value - percent,
        margin_display=f"+{value - percent:.1f} points",
    )


PARTS = [_single("Q2 FY2027", 75.0), _single("Q1 FY2027", 74.9), _single("Q4 FY2026", 73.4)]
EACH = ComputedTest(
    canonical="each(3): gross_margin[Q] > 70%",
    form="threshold",
    bound=" and ".join(f"({part.bound})" for part in PARTS),
    outcome="holds",
    outcome_label="Holds",
    comparison=">",
    left=PARTS[0].left,
    right=PARTS[0].right,
    operands=[operand for part in PARTS for operand in part.operands],
    arithmetic=[
        *(line for part in PARTS for line in part.arithmetic),
        "each of 3 tests: 3 hold, 0 fail, 0 cannot be told: holds",
    ],
    combines="each",
    parts=PARTS,
)
HISTORY = Analytic(
    id="an:c2:history",
    kind="history",
    label="How often the test held before",
    claim_ids=["c2"],
    measure="gross_margin",
    period=EACH.bound,
    value=30.0,
    unit="percent",
    display="6 of 20",
    formula="6 ÷ 20",
    inputs=[
        AnalyticInput(ref_kind="computed_test", id="test:c2", label=EACH.canonical, display="Holds")
    ],
    reading="The test gave 20 distinct readings and held in 6 of them (30.0%).",
)
TREND = Analytic(
    id="an:gross_margin:trend8",
    kind="trend8",
    label="Gross margin over eight quarters",
    value=75.0,
    unit="percent",
    display="75.0%",
    reading="Gross margin was 75.0% in the latest quarter and 60.5% at its lowest.",
)
INVENTED = Corollary(
    id="cor:c2:1",
    claim_id="c2",
    sentence="Gross margin over the last four quarters is above 80%.",
    expect="holds",
    computed=_single("TTM to Q2 FY2027", 74.7, percent=72),
)
RUN = Run(
    id="run-1",
    inputs=ThesisRequest(
        ticker="NVDA", decision="Hold NVIDIA through 2027.", claims=["Gross margin is above 70%."]
    ),
    status=RunStatus.complete,
    started_at=WHEN,
    claims=[
        Claim(id="c1", text="Revenue will exceed $300 billion and 2020 customers."),
        Claim(id="c2", text="Gross margin has stayed above 70%.", computed=EACH),
    ],
    timeline=[],
)
KNOWN = citables(RUN, [HISTORY, TREND], [INVENTED], [])


def _audit(text: str, *cites: str) -> ArgSentence:
    return audit_sentence(ArgSentence(text=text, cites=list(cites)), KNOWN, set(), AuditCounts())


def _restated(sentence: ArgSentence) -> list[tuple[str, str]]:
    return [(item.raw, item.of) for item in sentence.thresholds]


# The referee's two inputs ------------------------------------------------------------------------


def test_a_cited_claim_id_does_not_carry_the_claims_own_numbers() -> None:
    """ "Gross margin was 70%." citing an analytic and the claim "... above 70%" was verified."""
    sentence = _audit("Gross margin was 70%.", "an:gross_margin:trend8", "c2")
    assert not sentence.verified
    assert sentence.problems == ["writes 70%, which nothing it cites carries"]
    assert sentence.thresholds == []
    other = _audit("Revenue reached $300 billion.", "an:gross_margin:trend8", "c1")
    assert not other.verified


def test_a_corollarys_model_written_sentence_carries_no_number() -> None:
    """A model writes the corollary's sentence, so it could cite its own 80% as a fact."""
    sentence = _audit("Gross margin over four quarters was 80%.", "cor:c2:1")
    assert not sentence.verified
    assert sentence.problems == ["writes 80%, which nothing it cites carries"]
    # What code computed for the corollary still carries: its operand and its margin.
    computed = _audit("Over four quarters gross margin was 74.7%.", "cor:c2:1")
    assert computed.verified and computed.thresholds == []


# Thresholds: not failed, and said --------------------------------------------------------------


def test_a_tests_threshold_is_listed_as_restated_and_is_not_a_plain_pass() -> None:
    sentence = _audit("Gross margin was 70%.", "test:c2")
    assert sentence.verified and sentence.problems == []
    assert _restated(sentence) == [("70%", "test:c2")]
    assert sentence.thresholds[0].note == (
        "restates a threshold: 70% (test:c2); not checked as a fact"
    )
    plain = _audit("Gross margin was 75.0% in the latest quarter.", "test:c2")
    assert plain.verified and plain.thresholds == []
    both = _audit("All three quarters clear 70%, the lowest at 73.4%.", "test:c2")
    assert both.verified and _restated(both) == [("70%", "test:c2")]


def test_a_corollary_tests_threshold_is_listed_under_the_corollary() -> None:
    sentence = _audit("The four-quarter margin clears the 72% line.", "cor:c2:1")
    assert sentence.verified and _restated(sentence) == [("72%", "cor:c2:1")]


def test_an_analytic_of_a_computed_test_carries_that_tests_threshold_as_a_threshold() -> None:
    """The page's false alarm: "The 70% gross margin line has held in only 6 of 20 past
    readings" citing the test's history was marked "writes 70%, which nothing it cites
    carries"."""
    sentence = _audit(
        "The 70% gross margin line has held in only 6 of 20 past readings.", "an:c2:history"
    )
    assert sentence.verified, sentence.problems
    assert _restated(sentence) == [("70%", "test:c2")]
    # An analytic of no test carries no threshold.
    assert not _audit("The 70% line matters.", "an:gross_margin:trend8").verified


def test_a_number_in_nothing_cited_is_still_marked() -> None:
    for text, cite in (
        ("Gross margin was 71%.", "test:c2"),
        ("The 65% line has held in 6 of 20 readings.", "an:c2:history"),
        ("It has held in 6 of 20 readings, and 3% is a low bar.", "an:c2:history"),
    ):
        sentence = _audit(text, cite)
        assert not sentence.verified, text
        assert sentence.thresholds == []


def test_a_conditions_own_threshold_is_listed_not_silently_passed() -> None:
    condition = Condition(
        text="Gross margin below 65% would change the verdict.",
        cites=["an:gross_margin:trend8"],
        measure="gross_margin",
        comparison="<",
        threshold=65.0,
        unit="percent",
    )
    audited = audit_sentence(condition, KNOWN, set(), AuditCounts())
    assert audited.verified
    assert _restated(audited) == [("65%", "this condition's own threshold")]


def test_the_counts_say_how_many_verified_sentences_restate_a_threshold() -> None:
    counts = AuditCounts()
    for text in ("Gross margin was 70%.", "Gross margin was 75.0%.", "Gross margin was 71%."):
        audit_sentence(ArgSentence(text=text, cites=["test:c2"]), KNOWN, set(), counts)
    assert (counts.written, counts.verified, counts.unverified) == (3, 2, 1)
    assert counts.restating == 1


# The year exemption ----------------------------------------------------------------------------


def test_a_year_is_excused_only_where_a_year_stands() -> None:
    event = Event(
        id="ev1",
        accession="0001045810-20-000001",
        form="8-K",
        filed_date="2020-11-10",
        event_date="2020-11-09",
        filed_label="8-K filed 2020-11-10",
        url="https://www.sec.gov/Archives/edgar/data/1045810/x.htm",
    )
    known = citables(RUN.model_copy(update={"timeline": [event]}), [], [], [])

    def audit(text: str) -> ArgSentence:
        return audit_sentence(ArgSentence(text=text, cites=["ev1"]), known, set(), AuditCounts())

    assert audit("The 2020 8-K names a new chief executive.").verified
    counted = audit("The 8-K says it serves 2020 customers.")
    assert not counted.verified
    assert counted.problems == ["writes 2020, which nothing it cites carries"]
    assert not audit("The 8-K reports $2020 of fees.").verified


def test_the_brief_says_a_verified_sentence_restates_a_threshold() -> None:
    from app.services.export import _sentence_line

    line = _sentence_line(_audit("Gross margin was 70%.", "test:c2"))
    assert line.endswith("*Restates a threshold: 70% (test:c2); not checked as a fact.*")
    assert "Unverified" not in line
    plain = _sentence_line(_audit("Gross margin was 75.0%.", "test:c2"))
    assert "threshold" not in plain and "Unverified" not in plain
