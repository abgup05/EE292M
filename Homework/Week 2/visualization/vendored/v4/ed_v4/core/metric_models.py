"""Record types for reported numbers read from SEC XBRL company facts.

Pure data: nothing here touches the network or computes a result. The values
are computed by :mod:`app.core.metrics` from a :class:`app.core.facts.FactBook`
and returned by the API; a view only draws them.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

PeriodKind = Literal["quarter", "annual", "instant"]
MetricUnit = Literal["USD", "percent", "USD_per_share"]


class FactRef(BaseModel):
    """One value as a filing reported it, or one value derived from such values.

    ``start`` is None for an instant (a balance-sheet date). ``accession``,
    ``form`` and ``filed`` name the filing the value was taken from; for a
    derived value they name the latest filing among its inputs, and ``note``
    says how it was derived. ``restated`` is True when an earlier filing gave a
    different value for the same concept and period.
    """

    concept: str
    unit: str
    start: str | None
    end: str
    value: float
    accession: str
    form: str
    filed: str
    derived: bool = False
    restated: bool = False
    note: str = ""


class Metric(BaseModel):
    """One computed number for one period, with the facts and arithmetic behind it.

    ``value`` is unrounded: USD in dollars, a percent as a percent number (55.6
    for 55.6%). It is None when the number cannot be computed, and ``note``
    then says why. ``formula`` writes the arithmetic out with the numbers used
    and is empty for a value read directly from one fact.
    """

    id: str
    key: str
    label: str
    period: PeriodKind
    period_end: str
    period_label: str
    value: float | None
    unit: MetricUnit
    display: str
    formula: str = ""
    inputs: list[FactRef] = Field(default_factory=list)
    note: str = ""


class SeriesPoint(BaseModel):
    """One period of a chart series."""

    period_end: str
    value: float | None
    display: str


class Series(BaseModel):
    """One metric over time for one period kind, oldest point first."""

    key: str
    label: str
    unit: MetricUnit
    period: PeriodKind
    points: list[SeriesPoint] = Field(default_factory=list)


class MetricsReport(BaseModel):
    """Every reported-number metric for one company, with notes on what was missing."""

    company: str
    cik: int
    metrics: list[Metric] = Field(default_factory=list)
    series: list[Series] = Field(default_factory=list)
    notes: list[str] = Field(default_factory=list)
