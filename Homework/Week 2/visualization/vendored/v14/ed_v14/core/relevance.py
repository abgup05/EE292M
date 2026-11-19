"""Which measures bear on each claim, decided by code, and the thesis's headline figures.

Pure. A measure bears on a claim for one or more stated reasons, in this order:

- ``test operand``: a measure the claim's computed test reads;
- ``cited by a finding``: a reported figure one of the claim's verified findings cites;
- ``named in the claim``: a measure of the catalogue the claim's words name
  (:func:`app.core.claimtest.measures_named`), whether or not they state a test;
- ``part named in the claim``: a segment, product line or geography the claim's test names,
  or whose name, as a tagged breakdown the run already read labels it, the claim's words
  contain;
- ``growth compared with peers in the claim``: revenue, for a claim that compares the
  company's growth with its peers, competitors or industry and names no measure.

The headline is drawn from the claims, in claim order: the sides of a claim's computed test
(the figures the claim is about, for the period it is about); for a claim with no test, the
newest reported figure of each measure it bears on with its change on a year earlier, and
the growth of a part it names. A reported figure no claim is tied to stays on the record
and is listed as not tied to a claim.
"""

from __future__ import annotations

import re
from collections.abc import Sequence

from ed_v14.core import analysis_policy as rules
from ed_v14.core.analysis_models import Analytic, HeadlineFigure, RelevantMeasure
from ed_v14.core.analytics import PART_BREAKDOWNS
from ed_v14.core.breakdown_models import BreakdownReport
from ed_v14.core.claim_test_models import Operand
from ed_v14.core.claimtest import METRICS, ClaimTest, Number, Term, measures_named
from ed_v14.core.metric_models import Metric
from ed_v14.core.models import Claim, Finding

TEST_OPERAND = "test operand"
CITED = "cited by a finding"
NAMED = "named in the claim"
PART_NAMED = "part named in the claim"
PEER_GROWTH = "growth compared with peers in the claim"
PEERS = re.compile(
    r"\b(?:peers?|competitors?|rivals?|comparable companies|its (?:industry|sector)|"
    r"the (?:industry|sector)|industry average|other (?:retailers|companies|filers))\b",
    re.IGNORECASE,
)
GROWS = re.compile(r"\b(?:grow(?:s|ing|n|th)?|grew|outgrow\w*|expanding)\b", re.IGNORECASE)


def compares_with_peers(text: str) -> bool:
    """True when a claim's words compare the company with peers, competitors or its industry."""
    return PEERS.search(text) is not None


CHANGE_SUFFIXES = ("_yoy", "_qoq")
SHORT_LABEL = 3


def base_key(metric_key: str) -> str:
    """The measure a reported figure is of: "revenue" for "revenue_yoy"."""
    for suffix in CHANGE_SUFFIXES:
        if metric_key.endswith(suffix) and metric_key.removesuffix(suffix) in METRICS:
            return metric_key.removesuffix(suffix)
    return metric_key


def part_key(subject: str, axis: str, member: str) -> str:
    """The key of a part: 'revenue(segment "Data Center")'."""
    return f'{subject}({axis} "{member}")'


def _term_keys(term: Term) -> list[tuple[str, str]]:
    if term.axis:
        part = part_key(term.subject, term.axis, term.member)
        return [(part, PART_NAMED), (term.subject, TEST_OPERAND)]
    if term.fn == "share":
        part = part_key("revenue", term.subject, term.member)
        return [(part, PART_NAMED), ("revenue", TEST_OPERAND)]
    if term.fn == "max_share":
        return [("revenue", TEST_OPERAND)]
    return [(term.subject, TEST_OPERAND)] if term.subject in METRICS else []


def part_names(reports: Sequence[BreakdownReport]) -> list[tuple[str, str]]:
    """(axis, label) of every part a breakdown the run read tags, without repeats."""
    found: dict[tuple[str, str], None] = {}
    for report in reports:
        for item in report.breakdowns:
            axis = PART_BREAKDOWNS.get(item.id)
            if axis is None:
                continue
            for row in item.rows:
                found[(axis, row.label)] = None
    return list(found)


def _label(key: str, metrics: dict[str, Metric]) -> str:
    if key in METRICS:
        return METRICS[key][0]
    match = re.fullmatch(r'(\w+)\((\w+) "(.+)"\)', key)
    if match:
        return f"{METRICS.get(match[1], (match[1],))[0]}, {match[2]} {match[3]}"
    for metric in metrics.values():
        if metric.key == key:
            return metric.label
    return key


def newest_metric_ids(key: str, metrics: Sequence[Metric]) -> list[str]:
    """The newest reported figure of ``key`` and its change on a year earlier: the newest
    quarter (a balance: the newest date), or the newest fiscal year when no quarter is
    reported."""
    keys = {key, f"{key}_yoy"}
    of_key = [m for m in metrics if m.key in keys and m.value is not None]
    for period in ("quarter", "instant", "annual"):
        here = [m for m in of_key if m.period == period]
        if not here:
            continue
        newest = max(m.period_end for m in here)
        ordered = sorted(
            (m for m in here if m.period_end == newest),
            key=lambda m: (m.key != key, m.key),
        )
        return [m.id for m in ordered]
    return []


def claim_relevance(
    claim: Claim,
    test: ClaimTest | None,
    findings: Sequence[Finding],
    metrics: Sequence[Metric],
    parts: Sequence[tuple[str, str]] = (),
) -> list[RelevantMeasure]:
    """The measures that bear on ``claim``, each with why (see the module docstring)."""
    by_id = {metric.id: metric for metric in metrics}
    reasons: dict[str, list[str]] = {}

    def add(key: str, reason: str) -> None:
        listed = reasons.setdefault(key, [])
        if reason not in listed:
            listed.append(reason)

    if test is not None:
        for term in test.terms:
            for key, reason in _term_keys(term):
                add(key, reason)
    for finding in findings:
        if finding.claim_id != claim.id:
            continue
        for metric_id in finding.metric_ids:
            metric = by_id.get(metric_id)
            if metric is not None:
                add(base_key(metric.key), CITED)
    for key in measures_named(claim.text):
        add(key, NAMED)
    # "Growing faster than its peers" names no measure; growth with none named is revenue's.
    if not reasons and compares_with_peers(claim.text) and GROWS.search(claim.text):
        add("revenue", PEER_GROWTH)
    lowered = claim.text.casefold()
    for axis, label in parts:
        # A short label ("US") is matched as written, so that the word "us" is not a country.
        short = len(label) <= SHORT_LABEL
        haystack, needle = (claim.text, label) if short else (lowered, label.casefold())
        if re.search(rf"(?<!\w){re.escape(needle)}(?!\w)", haystack):
            add(part_key("revenue", axis, label), PART_NAMED)
            add("revenue", PART_NAMED)
    return [
        RelevantMeasure(
            key=key,
            label=_label(key, by_id),
            reasons=why,
            metric_ids=newest_metric_ids(key, metrics),
        )
        for key, why in reasons.items()
    ]


def _side_figure(claim_id: str, side: Operand) -> HeadlineFigure:
    return HeadlineFigure(
        id=f"test:{claim_id}",
        source="computed_test",
        label=side.label,
        value=side.value,
        unit=side.unit,
        display=side.display,
        claim_ids=[claim_id],
    )


def headline(
    claims: Sequence[Claim],
    relevant: dict[str, list[RelevantMeasure]],
    metrics: Sequence[Metric],
    analytics: Sequence[Analytic],
    tests: dict[str, ClaimTest] | None = None,
) -> list[HeadlineFigure]:
    """The thesis's headline figures, claim by claim, without repeats (see the module
    docstring). At most :data:`~app.core.analysis_policy.MAX_HEADLINE` figures."""
    by_id = {metric.id: metric for metric in metrics}
    growth = {item.measure: item for item in reversed(analytics) if item.kind == "part_growth"}
    out: dict[tuple[str, str], HeadlineFigure] = {}

    def add(figure: HeadlineFigure, claim_id: str) -> None:
        kept = out.setdefault((figure.id, figure.label), figure)
        if claim_id not in kept.claim_ids:
            kept.claim_ids.append(claim_id)

    for claim in claims:
        computed = claim.computed
        test = (tests or {}).get(claim.id)
        if computed is not None and computed.outcome != "cannot_compute":
            newest = computed.parts[0] if computed.parts else computed
            if newest.left is not None:
                add(_side_figure(claim.id, newest.left), claim.id)
            measured = test is not None and not isinstance(test.right, Number)
            if measured and newest.right is not None:
                add(_side_figure(claim.id, newest.right), claim.id)
            continue
        for measure in relevant.get(claim.id, []):
            for metric_id in measure.metric_ids:
                metric = by_id[metric_id]
                add(
                    HeadlineFigure(
                        id=metric_id,
                        source="metric",
                        label=metric.label,
                        period_label=metric.period_label,
                        value=metric.value,
                        unit=metric.unit,
                        display=metric.display,
                    ),
                    claim.id,
                )
            part = growth.get(measure.key)
            if part is not None:
                add(
                    HeadlineFigure(
                        id=part.id,
                        source="analytic",
                        label=part.label,
                        period_label=part.period,
                        value=part.value,
                        unit=part.unit,
                        display=part.display,
                    ),
                    claim.id,
                )
    return list(out.values())[: rules.MAX_HEADLINE]


def untied_metric_ids(
    metrics: Sequence[Metric], relevant: dict[str, list[RelevantMeasure]]
) -> list[str]:
    """The reported figures of measures no claim bears on, in report order."""
    tied = {measure.key for measures in relevant.values() for measure in measures}
    return [metric.id for metric in metrics if base_key(metric.key) not in tied]
