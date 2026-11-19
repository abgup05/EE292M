"""The audit of the argued analysis: every sentence a model writes is checked against the run.

Pure. A sentence is verified when

- every id it cites is in this run and of a kind it may cite (a verified finding, an
  analytic, a reported figure, a computed test, a corollary, odds, an 8-K event, or a claim);
  a finding the run withheld may not be cited;
- at least one id it cites is evidence (a claim id is not: it names what the sentence is
  about);
- every number it writes is a value of something it cites, by the numeric check the
  findings pass (:func:`app.core.numcheck.check_numbers`, with its rules for signs, units
  and the precision written). One exception, stated on the record: a condition that would
  change a verdict may write its own threshold (``Condition.threshold``), which is a line
  the model proposes to watch, not a statement about the record. And a bare year ("the 2026
  8-Ks") is carried by a cited item whose own date is in that year: an event's filing or
  event date, the filing or period of a finding's source, a figure's period, the period an
  analytic or a test is of. A year in none of them is still flagged.

What the audit does not decide: whether a sentence follows from what it cites. A sentence
with no number that cites a real id passes; it is the reader, shown each citation, who
judges the inference.

A sentence that fails is kept and marked unverified, with one problem per reason. The
audit never changes a verdict: a model's lean that contradicts a claim's verdict is a flag.
"""

from __future__ import annotations

import re
from collections.abc import Iterable, Sequence
from dataclasses import dataclass, field
from typing import Literal

from app.core import analysis_policy as rules
from app.core.analysis_models import (
    Analytic,
    ArgSentence,
    ClaimArgument,
    Condition,
    Corollary,
    Persistence,
    ThesisArgument,
)
from app.core.claim_test_models import ComputedTest, Operand
from app.core.metric_models import Metric, MetricUnit
from app.core.models import Run, Verdict
from app.core.numcheck import check_numbers

Kind = Literal[
    "finding", "analytic", "metric", "computed_test", "corollary", "odds", "event", "claim"
]
Reason = Literal["no_evidence", "unknown_id", "disallowed_id", "number"]
NO_EVIDENCE = "cites nothing that is evidence"
UNKNOWN = "cites {id}, which is not in this run"
DISALLOWED = "cites {id}, a finding the run withheld"
NUMBER = "writes {raw}, which nothing it cites carries"
METRIC_UNITS: dict[str, MetricUnit] = {
    "USD": "USD",
    "USD_per_share": "USD_per_share",
    "percent": "percent",
    "points": "percent",
    "probability": "percent",
}
CONTRADICTS = {
    ("supports", Verdict.challenged),
    ("challenges", Verdict.supported),
}


@dataclass(frozen=True)
class Citable:
    """Something a sentence may cite: its kind, whether it is evidence, its numbers (as
    text, and as figures with a unit) and the years of its own dates."""

    kind: Kind
    evidence: bool = True
    excerpts: tuple[str, ...] = ()
    metrics: tuple[Metric, ...] = ()
    years: frozenset[str] = frozenset()


@dataclass
class AuditCounts:
    """Sentences written, verified and unverified, and each reason an unverified one has."""

    written: int = 0
    verified: int = 0
    unverified: int = 0
    reasons: dict[Reason, int] = field(
        default_factory=lambda: {"no_evidence": 0, "unknown_id": 0, "disallowed_id": 0, "number": 0}
    )

    def merged(self, other: AuditCounts) -> AuditCounts:
        """The sum of two audits' counts."""
        return AuditCounts(
            self.written + other.written,
            self.verified + other.verified,
            self.unverified + other.unverified,
            {key: self.reasons[key] + other.reasons[key] for key in self.reasons},
        )


YEAR = re.compile(r"(?<!\d)((?:19|20)\d\d)(?!\d)")


def years_of(*texts: str | None) -> frozenset[str]:
    """Every four-digit year written in ``texts`` (dates, period labels such as FY2026)."""
    return frozenset(year for text in texts if text for year in YEAR.findall(text))


def as_metric(
    item_id: str, label: str, value: float | None, unit: str, shown: str
) -> Metric | None:
    """A figure the numeric check can match, or None for a unit it reads only as text."""
    metric_unit = METRIC_UNITS.get(unit)
    if metric_unit is None or value is None:
        return None
    return Metric(
        id=item_id,
        key=item_id,
        label=label,
        period="quarter",
        period_end="",
        period_label="as cited",
        value=value,
        unit=metric_unit,
        display=shown,
    )


def _present(items: Iterable[Metric | None]) -> tuple[Metric, ...]:
    return tuple(item for item in items if item is not None)


def _operand_metric(operand: Operand | None) -> Metric | None:
    if operand is None:
        return None
    return as_metric(operand.term, operand.label, operand.value, operand.unit, operand.display)


def _test_texts(test: ComputedTest) -> list[str]:
    texts = [*test.arithmetic, test.margin_display, test.bound]
    for part in test.parts:
        texts += _test_texts(part)
    return [text for text in texts if text]


def _test_metrics(test: ComputedTest) -> list[Metric | None]:
    found = [_operand_metric(test.left), _operand_metric(test.right)]
    found += [_operand_metric(operand) for operand in test.operands]
    if test.margin is not None and test.left is not None:
        found.append(
            as_metric(
                "margin",
                "margin",
                test.margin,
                "points" if test.left.unit == "percent" else test.left.unit,
                test.margin_display,
            )
        )
    for part in test.parts:
        found += _test_metrics(part)
    return found


def analytic_citable(item: Analytic) -> Citable:
    """An analytic: its value, its reading and its inputs' values."""
    texts = [item.display, item.reading, *(i.display for i in item.inputs if i.display)]
    metrics = [as_metric(item.id, item.label, item.value, item.unit, item.display)]
    metrics += [
        as_metric(i.id, i.label, i.value, "USD", i.display)
        for i in item.inputs
        if i.ref_kind == "fact" and i.display.startswith(("$", "-$"))
    ]
    dated = years_of(item.period, *(i.filed for i in item.inputs))
    return Citable("analytic", True, tuple(texts), _present(metrics), dated)


def citables(
    run: Run,
    analytics: Sequence[Analytic],
    corollaries: Sequence[Corollary],
    odds: Sequence[Persistence],
) -> dict[str, Citable]:
    """Everything in ``run`` a sentence may cite, by id."""
    out: dict[str, Citable] = {}
    metrics = {metric.id: metric for metric in run.metrics}
    for metric in run.metrics:
        dated = years_of(metric.period_end, metric.period_label)
        out[metric.id] = Citable("metric", True, (), (metric,), dated)
    sources = {source.id: source for source in run.sources}
    excerpts: dict[str, list[str]] = {}
    filed: dict[str, set[str]] = {}
    for item in run.evidence:
        excerpts.setdefault(item.finding_id, []).append(item.excerpt)
        source = sources.get(item.source_id)
        if source is not None:
            filed.setdefault(item.finding_id, set()).update(
                years_of(source.published_date, source.period_end)
            )
    for finding in run.findings:
        cited = tuple(metrics[i] for i in finding.metric_ids if i in metrics)
        texts = (finding.statement, *excerpts.get(finding.id, []))
        dated = frozenset(filed.get(finding.id, set())) | years_of(*(m.period_end for m in cited))
        out[finding.id] = Citable("finding", True, texts, cited, dated)
    for claim in run.claims:
        out[claim.id] = Citable("claim", False, (claim.text,))
        if claim.computed is not None:
            test = claim.computed
            out[f"test:{claim.id}"] = Citable(
                "computed_test",
                True,
                tuple(_test_texts(test)),
                _present(_test_metrics(test)),
                years_of(test.bound, test.as_of),
            )
    for item in analytics:
        out[item.id] = analytic_citable(item)
    for corollary in corollaries:
        texts = [corollary.sentence, corollary.result_label]
        found: list[Metric | None] = []
        if corollary.computed is not None:
            texts += _test_texts(corollary.computed)
            found += _test_metrics(corollary.computed)
        dated = years_of(corollary.computed.bound) if corollary.computed else frozenset()
        out[corollary.id] = Citable("corollary", True, tuple(texts), _present(found), dated)
    for record in odds:
        texts = (record.display, record.note, record.start_display, record.warning, record.method)
        metric = as_metric(record.id, "odds", record.probability, "probability", record.display)
        out[record.id] = Citable("odds", True, tuple(t for t in texts if t), _present([metric]))
    for event in run.timeline:
        texts = [event.filed_label, event.filed_date, event.event_date]
        for item in event.items:
            texts += [f"Item {item.number} {item.title}", *item.opening]
        dated = years_of(event.filed_date, event.event_date)
        out[event.id] = Citable("event", True, tuple(text for text in texts if text), years=dated)
    return out


def audit_sentence(
    sentence: ArgSentence, known: dict[str, Citable], withheld: set[str], counts: AuditCounts
) -> ArgSentence:
    """``sentence`` with ``verified`` and ``problems`` set, and counted."""
    problems = list(sentence.problems)
    reasons: list[Reason] = []
    valid: list[Citable] = []
    for cite in sentence.cites:
        if cite in withheld:
            problems.append(DISALLOWED.format(id=cite))
            reasons.append("disallowed_id")
        elif cite not in known:
            problems.append(UNKNOWN.format(id=cite))
            reasons.append("unknown_id")
        else:
            valid.append(known[cite])
    if not any(item.evidence for item in valid):
        problems.append(NO_EVIDENCE)
        reasons.append("no_evidence")
    texts = [text for item in valid for text in item.excerpts]
    figures = [metric for item in valid for metric in item.metrics]
    if isinstance(sentence, Condition) and sentence.measure and sentence.unit != "none":
        own = as_metric(
            "threshold", "the condition's own threshold", sentence.threshold, sentence.unit, ""
        )
        figures += [own] if own is not None else []
    check = check_numbers(sentence.text, texts, figures)
    carried = frozenset().union(*(item.years for item in valid))
    unmatched = [raw for raw in check.unmatched if raw.strip() not in carried]
    for raw in unmatched:
        problems.append(NUMBER.format(raw=raw))
    if unmatched:
        reasons.append("number")
    counts.written += 1
    verified = not reasons
    counts.verified += verified
    counts.unverified += not verified
    for reason in dict.fromkeys(reasons):
        counts.reasons[reason] += 1
    return sentence.model_copy(update={"verified": verified, "problems": problems})


def _audited(
    sentences: Sequence[ArgSentence],
    known: dict[str, Citable],
    withheld: set[str],
    counts: AuditCounts,
) -> list:
    return [audit_sentence(s, known, withheld, counts) for s in sentences]


def lean_flag(lean: str, verdict: Verdict | None) -> str:
    """The flag when a model's lean contradicts the claim's verdict; empty otherwise."""
    if verdict is None or (lean, verdict) not in CONTRADICTS:
        return ""
    return rules.LEAN_FLAG.format(lean=lean, verdict=verdict.value)


def audit_argument(
    claims: Sequence[ClaimArgument],
    thesis: ThesisArgument | None,
    known: dict[str, Citable],
    withheld: set[str],
    verdicts: dict[str, Verdict | None],
) -> tuple[list[ClaimArgument], ThesisArgument | None, AuditCounts]:
    """Every sentence audited, and each claim's lean compared with its verdict."""
    counts = AuditCounts()
    audited: list[ClaimArgument] = []
    for argument in claims:
        audited.append(
            argument.model_copy(
                update={
                    "lean_flag": lean_flag(argument.lean, verdicts.get(argument.claim_id)),
                    "assessment": _audited(argument.assessment, known, withheld, counts),
                    "case_for": _audited(argument.case_for, known, withheld, counts),
                    "case_against": _audited(argument.case_against, known, withheld, counts),
                    "decides": _audited(argument.decides, known, withheld, counts),
                    "would_change": _audited(argument.would_change, known, withheld, counts),
                }
            )
        )
    if thesis is not None:
        thesis = thesis.model_copy(
            update={
                "weakest_why": _audited(thesis.weakest_why, known, withheld, counts),
                "strongest_for": _audited(thesis.strongest_for, known, withheld, counts),
                "strongest_against": _audited(thesis.strongest_against, known, withheld, counts),
                "bottom_line": _audited(thesis.bottom_line, known, withheld, counts),
                "scenarios": [
                    scenario.model_copy(
                        update={
                            "conditions": _audited(scenario.conditions, known, withheld, counts)
                        }
                    )
                    for scenario in thesis.scenarios
                ],
            }
        )
    return audited, thesis, counts
