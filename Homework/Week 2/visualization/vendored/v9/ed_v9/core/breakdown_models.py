"""Record types for the facts tagged in one filing's inline XBRL and the breakdowns made from them.

Pure data. :mod:`app.sources.ixbrl` reads a filing's HTML into
:class:`TaggedFacts`; :mod:`app.core.breakdowns` turns those into a
:class:`BreakdownReport`, which the command line prints and saves. The input
records are frozen dataclasses (thousands per filing, never serialised); the
output records are pydantic models, written as JSON.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date

from pydantic import BaseModel, Field

from ed_v9.core.models import Company

# Read from the filing


@dataclass(frozen=True, slots=True)
class XbrlContext:
    """One ``xbrli:context``: the period a fact is about and its dimension members.

    ``start`` is None for an instant, whose date is ``end``. ``dimensions`` maps
    each explicit axis to its member (both as qualified names, such as
    ``srt:ProductOrServiceAxis`` -> ``nvda:DataCenterMember``). ``typed_axes``
    names the axes with a typed member, whose value this reader does not keep.
    """

    id: str
    start: date | None
    end: date
    dimensions: dict[str, str] = field(default_factory=dict)
    typed_axes: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class TaggedFact:
    """One ``ix:nonFraction`` fact whose number was read.

    ``shown`` is the text as the filing displays it (tags removed, entities
    decoded, whitespace collapsed). ``value`` is that number with ``scale``
    applied (multiplied by ten to the power of ``scale``) and made negative when
    ``negative`` (the ``sign="-"`` attribute). ``decimals`` is the attribute as
    written ("-6", "INF") or None.
    """

    concept: str
    context_ref: str
    unit_ref: str | None
    shown: str
    scale: int
    negative: bool
    format: str | None
    decimals: str | None
    value: float
    fact_id: str | None = None


@dataclass(frozen=True, slots=True)
class UnreadFact:
    """One ``ix:nonFraction`` fact whose number could not be read, and why."""

    concept: str
    context_ref: str
    shown: str
    format: str | None
    reason: str


@dataclass(frozen=True)
class TaggedFacts:
    """Everything numeric a filing tags: contexts by id, units by id, facts read and not read.

    ``units`` maps a unit id to its measure's local name ("USD", "pure",
    "USD/shares"). ``problems`` describes contexts or units that could not be
    read. ``reason`` is set, and everything else empty, when the document has
    no inline XBRL.
    """

    contexts: dict[str, XbrlContext] = field(default_factory=dict)
    units: dict[str, str] = field(default_factory=dict)
    facts: list[TaggedFact] = field(default_factory=list)
    unparsed: list[UnreadFact] = field(default_factory=list)
    problems: list[str] = field(default_factory=list)
    reason: str | None = None

    @property
    def facts_read(self) -> int:
        """How many numeric facts the document tags: read and not read."""
        return len(self.facts) + len(self.unparsed)


# The breakdowns


class BreakdownValue(BaseModel):
    """One member's (or the total's) value for one period, and its change.

    ``period_start`` is None for an instant. ``value`` is the number with the
    tag's scale and sign applied, in ``unit`` ("USD"; "pure" for a fraction,
    0.22 for 22%). ``shown`` is the text exactly as the filing displays it.
    ``change`` is the per-cent change from the comparable earlier period (68.2
    for +68.2%), or None; ``change_formula`` writes the arithmetic out in words
    with the numbers used, or says why there is no change. ``display`` is the
    value as a table shows it, in the breakdown's ``unit_label`` ("193,737" in
    USD millions, "22.0%"), whatever scale the tag used; ``change_display`` is
    the change as shown ("+68.2%"), or "" when there is none. A view draws these
    two strings and computes nothing.
    """

    period_start: str | None
    period_end: str
    value: float
    unit: str
    shown: str
    display: str
    change: float | None = None
    change_display: str = ""
    change_formula: str = ""


class PeriodColumn(BaseModel):
    """One period a breakdown shows, and its column heading ("Fiscal year ended 2026-01-25").

    ``period_start`` is None for an instant ("As of 2026-01-25").
    """

    period_start: str | None
    period_end: str
    label: str


class BreakdownRow(BaseModel):
    """One member of the breakdown's axis and its values, newest period first.

    ``member`` is the tag's qualified name; ``label`` is derived from that name
    (not the company's own label; the breakdown's notes say so).
    """

    member: str
    label: str
    values: list[BreakdownValue] = Field(default_factory=list)


class Breakdown(BaseModel):
    """One concept split along one axis in one filing, such as revenue by segment.

    ``concept`` is the tagged concept used (revenue concepts differ by company).
    ``period_kind`` names the periods shown ("fiscal year", "three months",
    "six months year to date", "instant"); ``periods`` are the columns, newest
    first, with their headings. ``unit_label`` is the unit every ``display`` is
    in ("USD millions", "percent of revenue"). ``total`` is the concept's value with
    no dimension, per period, when the filing tags it. ``adds_up`` is True when
    the members add up to the total in every period checked (directly, with
    members that are sums of others counted once, as two splits of the total,
    or with the reconciling items the filing tags; ``notes`` says which), False
    when they do not in at least one, and None when nothing could be checked.
    """

    id: str
    title: str
    concept: str
    axis: str
    period_kind: str
    unit_label: str
    periods: list[PeriodColumn] = Field(default_factory=list)
    rows: list[BreakdownRow] = Field(default_factory=list)
    total: list[BreakdownValue] = Field(default_factory=list)
    adds_up: bool | None = None
    notes: list[str] = Field(default_factory=list)


class FilingInfo(BaseModel):
    """The filing the breakdowns were read from."""

    form: str
    period_end: str
    filed_date: str
    accession: str
    url: str


class BreakdownReport(BaseModel):
    """The breakdowns tagged in one filing, with counts of the facts read and not read.

    ``facts_read`` counts every numeric fact the filing tags; ``facts_unparsed``
    those whose number could not be read (``notes`` says why).
    """

    company: Company
    filing: FilingInfo
    breakdowns: list[Breakdown] = Field(default_factory=list)
    facts_read: int = 0
    facts_unparsed: int = 0
    notes: list[str] = Field(default_factory=list)
