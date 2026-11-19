"""The audit of the argued analysis: every sentence a model writes is checked against the run.

Pure. A sentence is verified when

- every id it cites is in this run and of a kind it may cite (a verified finding, an
  analytic, a reported figure, a computed test, a corollary, odds, an 8-K event, or a claim);
  a finding the run withheld may not be cited;
- at least one id it cites is evidence (a claim id is not: it names what the sentence is
  about);
- every number it writes is carried by evidence it cites, by the numeric check the
  findings pass (:func:`app.core.numcheck.check_numbers`, with its rules for signs, units
  and the precision written), or is a threshold restated (below).

What carries a number: a verified finding's statement, quotes and cited figures; an
analytic's value, inputs and reading; a computed test's operands, their arithmetic and
its margin; a reported figure; an 8-K event's text; odds. What does not: the claim's own
words when its id is cited (a claim id names what a sentence is about), and the sentence
a model wrote for a corollary (only what code computed for the corollary carries).

A threshold is neither a fact nor a failure. A computed test compares a measure with a
constant the claim's author wrote; a corollary's test with one the proposing model wrote;
a condition that would change a verdict states one of its own (``Condition.threshold``).
When a number of a sentence is carried by no evidence it cites but equals the threshold
of a test or corollary it cites (or of the test an analytic it cites was computed from:
``an:c2:history``), or the condition's own, the sentence is not failed for it and
``ArgSentence.thresholds`` lists it, with whose threshold it is. So "Gross margin was
70%" citing ``test:c2`` is on the record as resting on a threshold, never as a number
the evidence carries. The wording is :data:`app.core.analysis_policy.AUDIT_RULE`, which
every analysis carries (``Analysis.audit_rule``).

A bare year ("the 2026 8-Ks") is carried by a cited item whose own date is in that year:
an event's filing or event date, the filing or period of a finding's source, a figure's
period, the period an analytic or a test is of. Only a number in a year's position is
excused so: four bare digits with no sign, currency, scale or unit, and not directly
before a thing a filing counts (:data:`app.core.numcheck.COUNTED_NOUNS`). "Costco's 2025
growth" and "peers' 2026 figures" are years; "2020 customers" beside an item dated 2020
is a count nothing carries, and so is "$2020". A year in none of them is flagged.

What the audit does not decide: whether a sentence follows from what it cites. A sentence
with no number that cites a real id passes; it is the reader, shown each citation, who
judges the inference.

A sentence that fails is kept and marked unverified, with one problem per reason. The
audit never changes a verdict: a model's lean that contradicts a claim's verdict is a flag.
"""

from __future__ import annotations

import re
from collections.abc import Iterable, Sequence
from dataclasses import dataclass, field, replace
from typing import Literal

from app.core import analysis_policy as rules
from app.core.analysis_models import (
    Analytic,
    ArgSentence,
    ClaimArgument,
    Condition,
    Corollary,
    Persistence,
    RestatedThreshold,
    ThesisArgument,
)
from app.core.claim_test_models import THRESHOLD_LABEL, ComputedTest, Operand
from app.core.metric_models import Metric, MetricUnit
from app.core.models import Run, Verdict
from app.core.numcheck import YEARS, Quantity, check_numbers, counts_a_listed_thing

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
class Threshold:
    """A constant a computed test compares against: whose it is, and the number.

    ``of`` is the id of the test or corollary ("test:c2", "cor:c2:1"); ``display`` the
    constant as written ("70%"); ``metric`` the same as a figure with a unit, or None
    for a unit the numeric check reads only as text (a count).
    """

    of: str
    display: str
    metric: Metric | None = None


@dataclass(frozen=True)
class Citable:
    """Something a sentence may cite: its kind, whether it is evidence, the numbers it
    carries (as text, and as figures with a unit), the thresholds a sentence citing it
    may restate, and the years of its own dates."""

    kind: Kind
    evidence: bool = True
    excerpts: tuple[str, ...] = ()
    metrics: tuple[Metric, ...] = ()
    years: frozenset[str] = frozenset()
    thresholds: tuple[Threshold, ...] = ()


@dataclass
class AuditCounts:
    """Sentences written, verified and unverified, each reason an unverified one has, and
    how many of the verified ones restate a threshold (``restating``)."""

    written: int = 0
    verified: int = 0
    unverified: int = 0
    restating: int = 0
    reasons: dict[Reason, int] = field(
        default_factory=lambda: {"no_evidence": 0, "unknown_id": 0, "disallowed_id": 0, "number": 0}
    )

    def merged(self, other: AuditCounts) -> AuditCounts:
        """The sum of two audits' counts."""
        return AuditCounts(
            self.written + other.written,
            self.verified + other.verified,
            self.unverified + other.unverified,
            self.restating + other.restating,
            {key: self.reasons[key] + other.reasons[key] for key in self.reasons},
        )


YEAR = re.compile(r"(?<!\d)((?:19|20)\d\d)(?!\d)")
# The last line of a single test's arithmetic: the two sides compared, and the outcome.
COMPARISON_LINE = re.compile(r": (?:holds|fails|cannot tell)$")


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


def is_constant(operand: Operand | None) -> bool:
    """True when ``operand`` is the constant a test compares against, not a value read."""
    return (
        operand is not None
        and operand.label == THRESHOLD_LABEL
        and not operand.inputs
        and not operand.formula
    )


def _test_texts(test: ComputedTest) -> list[str]:
    """The lines of a test's arithmetic that state values read or computed, and its margin.

    Left out: the test as bound to its periods ("gross_margin[Q2 FY2027] > 70%") and, for
    a test against a constant, the line that compares the two sides ("75.0% > 70%:
    holds"): both print the threshold, which is not a value the facts report.
    """
    if test.parts:
        of_parts = {line for part in test.parts for line in part.arithmetic}
        texts = [line for line in test.arithmetic if line not in of_parts]
        for part in test.parts:
            texts += _test_texts(part)
        return [text for text in texts if text]
    lines = list(test.arithmetic)
    if is_constant(test.right) and lines and COMPARISON_LINE.search(lines[-1]):
        lines.pop()
    return [text for text in [*lines, test.margin_display] if text]


def thresholds_of(of: str, test: ComputedTest) -> list[Threshold]:
    """The constants ``test`` and its parts compare against, each once, as ``of``'s."""
    found: dict[str, Threshold] = {}
    right = test.right
    if right is not None and is_constant(right):
        found[right.display] = Threshold(of, right.display, _operand_metric(right))
    for part in test.parts:
        for threshold in thresholds_of(of, part):
            found.setdefault(threshold.display, threshold)
    return list(found.values())


def _test_metrics(test: ComputedTest) -> list[Metric | None]:
    """The values a test read or computed, as figures: never the constant it compares with."""
    sides = [side for side in (test.left, test.right) if not is_constant(side)]
    found = [_operand_metric(side) for side in sides]
    found += [_operand_metric(operand) for operand in test.operands if not is_constant(operand)]
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
        # A claim id names what a sentence is about. Its words are the thesis's, not
        # evidence, so they carry no number.
        out[claim.id] = Citable("claim", False)
        if claim.computed is not None:
            test = claim.computed
            test_id = f"test:{claim.id}"
            out[test_id] = Citable(
                "computed_test",
                True,
                tuple(_test_texts(test)),
                _present(_test_metrics(test)),
                years_of(test.bound, test.as_of),
                tuple(thresholds_of(test_id, test)),
            )
    for item in analytics:
        # An analytic computed from a claim's test (its history, its headroom) is about
        # that test's line, so a sentence citing it may restate the test's threshold.
        of_tests = [
            threshold
            for test_id in dict.fromkeys(i.id for i in item.inputs if i.ref_kind == "computed_test")
            if test_id in out
            for threshold in out[test_id].thresholds
        ]
        out[item.id] = replace(analytic_citable(item), thresholds=tuple(of_tests))
    for corollary in corollaries:
        # The corollary's sentence is a model's (step "propose"): only what code computed
        # for it carries a number.
        texts: list[str] = []
        found: list[Metric | None] = []
        thresholds: list[Threshold] = []
        if corollary.computed is not None:
            texts += _test_texts(corollary.computed)
            found += _test_metrics(corollary.computed)
            thresholds = thresholds_of(corollary.id, corollary.computed)
        dated = years_of(corollary.computed.bound) if corollary.computed else frozenset()
        out[corollary.id] = Citable(
            "corollary", True, tuple(texts), _present(found), dated, tuple(thresholds)
        )
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
    check = check_numbers(sentence.text, texts, figures)
    lines = [threshold for item in valid for threshold in item.thresholds]
    if isinstance(sentence, Condition) and sentence.measure and sentence.unit != "none":
        own = as_metric(
            "threshold", "the condition's own threshold", sentence.threshold, sentence.unit, ""
        )
        lines += [Threshold(rules.OWN_THRESHOLD, "", own)] if own is not None else []
    carried = frozenset().union(*(item.years for item in valid))
    restated: list[RestatedThreshold] = []
    unmatched: list[str] = []
    for index, (quantity, found) in enumerate(zip(check.quantities, check.found, strict=True)):
        a_year = _could_be_year(quantity) and not counts_a_listed_thing(
            sentence.text, check.offsets[index]
        )
        if found or (a_year and quantity.raw.strip() in carried):
            continue
        whose = _threshold_of(sentence.text, index, lines)
        if whose is None:
            unmatched.append(quantity.raw)
        else:
            note = rules.THRESHOLD_RESTATED.format(raw=quantity.raw, of=whose)
            restated.append(RestatedThreshold(raw=quantity.raw, of=whose, note=note))
    for raw in unmatched:
        problems.append(NUMBER.format(raw=raw))
    if unmatched:
        reasons.append("number")
    counts.written += 1
    verified = not reasons
    counts.verified += verified
    counts.unverified += not verified
    counts.restating += verified and bool(restated)
    for reason in dict.fromkeys(reasons):
        counts.reasons[reason] += 1
    return sentence.model_copy(
        update={"verified": verified, "problems": problems, "thresholds": restated}
    )


def _could_be_year(quantity: Quantity) -> bool:
    """True when ``quantity`` is four bare digits from 1900 to 2100: no sign, currency,
    scale or unit ("$2020" is an amount). The word after it is the caller's to judge."""
    raw = quantity.raw.strip()
    bare = quantity.unit in ("plain", "count") and not quantity.signed
    return bare and len(raw) == 4 and raw.isdigit() and int(raw) in YEARS


def _threshold_of(text: str, index: int, lines: Sequence[Threshold]) -> str | None:
    """Whose threshold the ``index``-th quantity of ``text`` restates, or None.

    Matched as every number is (units, the precision written), against the constants
    alone, one owner at a time in the order cited.
    """
    for line in lines:
        figures = [line.metric] if line.metric is not None else []
        excerpts = [] if line.metric is not None else [line.display]
        check = check_numbers(text, excerpts, figures)
        if index < len(check.found) and check.found[index]:
            return line.of
    return None


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
