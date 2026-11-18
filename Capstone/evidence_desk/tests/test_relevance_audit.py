"""Relevance decided by code, and the audit of one sentence, on hand-built records."""

from __future__ import annotations

from app.core.analysis_audit import AuditCounts, Citable, as_metric, audit_sentence, lean_flag
from app.core.analysis_models import ArgSentence, Condition
from app.core.claim_test_models import ComputedTest, Operand
from app.core.claimtest import ClaimTest, compile_claim
from app.core.metric_models import Metric
from app.core.models import Claim, Confidence, Finding, Stance, Verdict
from app.core.relevance import claim_relevance, headline, untied_metric_ids


def _metric(key: str, period: str, end: str, value: float) -> Metric:
    return Metric(
        id=f"{key}:{period}:{end}",
        key=key,
        label=key,
        period=period,  # type: ignore[arg-type]
        period_end=end,
        period_label=end,
        value=value,
        unit="percent" if key.endswith(("margin", "_yoy")) else "USD",
        display=str(value),
    )


METRICS = [
    _metric("revenue", "quarter", "2026-04-26", 1.0),
    _metric("revenue", "quarter", "2026-07-26", 2.0),
    _metric("revenue_yoy", "quarter", "2026-07-26", 50.0),
    _metric("gross_margin", "quarter", "2026-07-26", 70.0),
    _metric("cash", "instant", "2026-07-26", 3.0),
]


def _finding(claim_id: str, metric_ids: list[str]) -> Finding:
    return Finding(
        id="f1",
        claim_id=claim_id,
        statement="s",
        stance=Stance.supports,
        evidence_ids=[],
        confidence=Confidence.high,
        rationale="r",
        verified=True,
        metric_ids=metric_ids,
    )


def test_each_reason_a_measure_bears_on_a_claim() -> None:
    claim = Claim(id="c1", text="Gross margin is expanding as data center grows.")
    test = compile_claim("Gross margin is expanding.")
    assert isinstance(test, ClaimTest)
    relevant = claim_relevance(
        claim,
        test,
        [_finding("c1", ["revenue_yoy:quarter:2026-07-26"]), _finding("c2", ["cash:instant:x"])],
        METRICS,
        parts=[("segment", "Data Center")],
    )
    reasons = {item.key: item.reasons for item in relevant}
    assert reasons["gross_margin"] == ["test operand", "named in the claim"]
    assert reasons["revenue"] == ["cited by a finding", "part named in the claim"]
    assert reasons['revenue(segment "Data Center")'] == ["part named in the claim"]
    assert "cash" not in reasons  # another claim's finding
    revenue = next(item for item in relevant if item.key == "revenue")
    # The newest quarter only, the measure before its growth.
    assert revenue.metric_ids == ["revenue:quarter:2026-07-26", "revenue_yoy:quarter:2026-07-26"]


def test_a_claim_with_no_measure_has_none_and_the_headline_follows_claim_order() -> None:
    first = Claim(id="c1", text="Management is excellent.")
    second = Claim(id="c2", text="Revenue is above $1.")
    relevant = {
        "c1": claim_relevance(first, None, [], METRICS),
        "c2": claim_relevance(second, None, [], METRICS),
    }
    assert relevant["c1"] == []
    figures = headline([first, second], relevant, METRICS, [])
    assert [f.id for f in figures] == [
        "revenue:quarter:2026-07-26",
        "revenue_yoy:quarter:2026-07-26",
    ]
    assert all(f.claim_ids == ["c2"] for f in figures)
    assert untied_metric_ids(METRICS, relevant) == [
        "gross_margin:quarter:2026-07-26",
        "cash:instant:2026-07-26",
    ]


KNOWN = {
    "an:x": Citable("analytic", True, ("Revenue grew 105.9% on a year earlier.",)),
    "m1": Citable(
        "metric", True, (), tuple(m for m in [as_metric("m1", "m", 46.74e9, "USD", "$46.74B")] if m)
    ),
    "c1": Citable("claim", False, ("Revenue more than doubled.",)),
}


def _audit(text: str, *cites: str, withheld: frozenset[str] = frozenset()) -> ArgSentence:
    return audit_sentence(
        ArgSentence(text=text, cites=list(cites)), KNOWN, set(withheld), AuditCounts()
    )


def test_a_sentence_is_verified_only_when_its_ids_and_numbers_hold() -> None:
    assert _audit("Revenue grew 105.9%.", "an:x").verified
    assert _audit("Revenue was $46.7 billion.", "m1").verified
    assert not _audit("Revenue grew 150%.", "an:x").verified
    assert _audit("Revenue grew 150%.", "an:x").problems == [
        "writes 150%, which nothing it cites carries"
    ]
    claim_only = _audit("It is about revenue.", "c1")
    assert claim_only.problems == ["cites nothing that is evidence"]
    withheld = _audit("A withheld finding says so.", "an:x", "f9", withheld=frozenset({"f9"}))
    assert not withheld.verified and withheld.problems == ["cites f9, a finding the run withheld"]


def test_a_lean_against_the_verdict_is_a_flag_and_mixed_never_is() -> None:
    assert lean_flag("challenges", Verdict.supported)
    assert lean_flag("supports", Verdict.challenged)
    assert not lean_flag("mixed", Verdict.supported)
    assert not lean_flag("supports", Verdict.supported)
    assert not lean_flag("challenges", None)


def test_a_short_part_label_is_matched_as_written() -> None:
    parts = [("geography", "US"), ("segment", "Data Center")]
    told = Claim(id="c1", text="Customers tell us that data center demand is strong.")
    keys = [m.key for m in claim_relevance(told, None, [], METRICS, parts)]
    assert keys == ['revenue(segment "Data Center")', "revenue"]
    named = Claim(id="c2", text="Revenue from the US is growing.")
    assert 'revenue(geography "US")' in [
        m.key for m in claim_relevance(named, None, [], METRICS, parts)
    ]


def _side(label: str, value: float) -> Operand:
    return Operand(term=label, label=label, value=value, unit="USD", display=f"${value}")


def test_the_headline_of_a_computed_claim_is_the_sides_of_its_test() -> None:
    test = compile_claim("Operating cash flow was above net income in the latest fiscal year.")
    assert isinstance(test, ClaimTest)
    computed = ComputedTest(
        canonical=test.canonical,
        form=test.form,
        outcome="fails",
        outcome_label="Fails",
        comparison=">",
        left=_side("Operating cash flow, FY", 1.0),
        right=_side("Net income, FY", 2.0),
    )
    claim = Claim(id="c1", text="x", computed=computed)
    figures = headline([claim], {"c1": []}, METRICS, [], {"c1": test})
    assert [(f.source, f.label, f.id) for f in figures] == [
        ("computed_test", "Operating cash flow, FY", "test:c1"),
        ("computed_test", "Net income, FY", "test:c1"),
    ]
    # Against a constant, the constant is not a figure.
    threshold = compile_claim("Gross margin is above 70%.")
    assert isinstance(threshold, ClaimTest)
    figures = headline([claim], {"c1": []}, METRICS, [], {"c1": threshold})
    assert [f.label for f in figures] == ["Operating cash flow, FY"]


def test_a_condition_may_state_its_own_threshold_and_nothing_else() -> None:
    def audit(text: str) -> ArgSentence:
        condition = Condition(
            text=text,
            cites=["an:x"],
            measure="gross_margin",
            comparison="<",
            threshold=65.0,
            unit="percent",
        )
        return audit_sentence(condition, KNOWN, set(), AuditCounts())

    assert audit("Gross margin below 65% would change the verdict.").verified
    wrong = audit("Gross margin below 60% would change the verdict.")
    assert not wrong.verified and "60%" in wrong.problems[0]
    plain = ArgSentence(text="Gross margin below 65% would change it.", cites=["an:x"])
    assert not audit_sentence(plain, KNOWN, set(), AuditCounts()).verified
