"""Which measures bear on each claim, decided by code, and the thesis's headline figures.

Pure. A measure bears on a claim for one or more stated reasons, in this order:

- ``test operand``: a measure the claim's computed test reads;
- ``cited by a finding``: a reported figure one of the claim's verified findings cites;
- ``named in the claim``: a measure of the catalogue the claim's words name
  (:func:`app.core.claimtest.measures_named`), whether or not they state a test;
- ``part named in the claim``: a segment, product line or geography the claim's test names,
  or whose name, as a tagged breakdown the run already read labels it, the claim's words
  contain.

The headline is the ordered list of reported figures (or, for a measure with none, its
latest-level analytic) those measures give, claim by claim; a reported figure no claim is
tied to stays on the record and is listed as not tied to a claim.
"""

from __future__ import annotations

import re
from collections.abc import Sequence

from app.core import analysis_policy as rules
from app.core.analysis_models import Analytic, HeadlineFigure, RelevantMeasure
from app.core.breakdown_models import BreakdownReport
from app.core.claimtest import METRICS, ClaimTest, Term, measures_named
from app.core.metric_models import Metric
from app.core.models import Claim, Finding

TEST_OPERAND = "test operand"
CITED = "cited by a finding"
NAMED = "named in the claim"
PART_NAMED = "part named in the claim"
CHANGE_SUFFIXES = ("_yoy", "_qoq")
PART_BREAKDOWNS = {
    "revenue_by_segment": "segment",
    "revenue_by_product": "segment",
    "revenue_by_geography": "geography",
}


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
    """The reported figures of ``key`` (and of its growth) in the newest quarter and fiscal
    year the run reported, quarter first."""
    keys = {key, *(f"{key}{suffix}" for suffix in CHANGE_SUFFIXES)}
    of_key = [m for m in metrics if m.key in keys and m.value is not None]
    out: list[str] = []
    for period in ("quarter", "instant", "annual"):
        here = [m for m in of_key if m.period == period]
        if not here:
            continue
        newest = max(m.period_end for m in here)
        ordered = sorted(
            (m for m in here if m.period_end == newest),
            key=lambda m: (m.key != key, m.key),
        )
        out += [m.id for m in ordered]
    return out


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
    lowered = claim.text.casefold()
    for axis, label in parts:
        if re.search(rf"(?<!\w){re.escape(label.casefold())}(?!\w)", lowered):
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


def headline(
    claims: Sequence[Claim],
    relevant: dict[str, list[RelevantMeasure]],
    metrics: Sequence[Metric],
    analytics: Sequence[Analytic],
) -> list[HeadlineFigure]:
    """The thesis's headline figures, claim by claim and measure by measure, without repeats.

    A measure with reported figures gives them; one without gives its latest-level analytic
    when it has one. At most :data:`~app.core.analysis_policy.MAX_HEADLINE` figures.
    """
    by_id = {metric.id: metric for metric in metrics}
    levels = {item.measure: item for item in analytics if item.kind == "level" and item.available}
    out: dict[str, HeadlineFigure] = {}
    for claim in claims:
        for measure in relevant.get(claim.id, []):
            ids = measure.metric_ids
            if ids:
                for metric_id in ids:
                    metric = by_id[metric_id]
                    figure = out.setdefault(
                        metric_id,
                        HeadlineFigure(
                            id=metric_id,
                            source="metric",
                            label=metric.label,
                            period_label=metric.period_label,
                            value=metric.value,
                            unit=metric.unit,
                            display=metric.display,
                        ),
                    )
                    if claim.id not in figure.claim_ids:
                        figure.claim_ids.append(claim.id)
                continue
            level = levels.get(measure.key)
            if level is None:
                continue
            figure = out.setdefault(
                level.id,
                HeadlineFigure(
                    id=level.id,
                    source="analytic",
                    label=level.label,
                    period_label=level.period,
                    value=level.value,
                    unit=level.unit,
                    display=level.display,
                ),
            )
            if claim.id not in figure.claim_ids:
                figure.claim_ids.append(claim.id)
    return list(out.values())[: rules.MAX_HEADLINE]


def untied_metric_ids(
    metrics: Sequence[Metric], relevant: dict[str, list[RelevantMeasure]]
) -> list[str]:
    """The reported figures of measures no claim bears on, in report order."""
    tied = {measure.key for measures in relevant.values() for measure in measures}
    return [metric.id for metric in metrics if base_key(metric.key) not in tied]
