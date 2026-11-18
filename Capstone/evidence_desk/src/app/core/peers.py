"""Peer standing: where a company's value of a measure sits among its industry, from frames.

Pure. For one measure and one frame year, every member of the class with a value is
ranked, highest first; the company's ``rank`` is one plus the number of members with a
higher value, and its ``percentile`` the share of the other members with a lower value:
``100 × lower ÷ (n − 1)``. The company is ranked even when its revenue is under the
class's floor, and the result says so. The members next to it are named, with the class
median. The same is done for the year before, so a reader sees whether it moved.
"""

from __future__ import annotations

from collections.abc import Sequence

from app.core.analysis_models import Neighbour, PeerStanding, ResultInput, Standing
from app.core.base_rates import RefClass, Value, growth_value, percentile, value_text
from app.core.facts import GROUPS
from app.core.frames import MEASURES, Panel, frame_source

NEIGHBOURS = 2
MIN_CLASS = 3
PEER_MEASURES: tuple[str, ...] = (
    "revenue",
    "revenue_growth",
    "gross_margin",
    "operating_margin",
    "net_margin",
    "rnd_ratio",
    "operating_cash_flow",
    "capex",
    "capex_ratio",
    "free_cash_flow",
    "fcf_margin",
    "cash_conversion",
)


def label_of(key: str) -> str:
    """The label of a peer measure."""
    return "Revenue growth, year over year" if key == "revenue_growth" else MEASURES[key].label


def unit_of(key: str) -> str:
    """The unit of a peer measure: percent, USD or ratio."""
    return "percent" if key == "revenue_growth" else MEASURES[key].unit


def peer_value(panel: Panel, key: str, cik: int, year: int) -> Value:
    """A filer's value of a peer measure in a year: a frame measure or revenue growth."""
    if key == "revenue_growth":
        return growth_value(panel, "revenue", cik, year, 1, compound=False)
    found = panel.measure(key, cik, year)
    if found.value is None:
        return Value(None, reason=found.reason)
    return Value(found.value, found.used[0].row.end.isoformat())


def standing(panel: Panel, key: str, cik: int, year: int, ref: RefClass) -> Standing:
    """The company's rank among ``ref`` on ``key`` in ``year``, with its neighbours."""
    own = peer_value(panel, key, cik, year)
    if own.value is None:
        return Standing(year=year, reason=f"The company's value cannot be computed: {own.reason}.")
    values: dict[int, float] = {cik: own.value}
    for member in panel.filers(year):
        if member == cik or not ref.admits(panel, member, year):
            continue
        found = peer_value(panel, key, member, year)
        if found.value is not None:
            values[member] = found.value
    n = len(values)
    unit = unit_of(key)
    if n < MIN_CLASS:
        return Standing(
            year=year,
            period_end=own.end,
            n=n,
            value=own.value,
            display=value_text(own.value, unit),
            reason=f"Fewer than {MIN_CLASS} members have a value; no ranking is made.",
        )
    ordered = sorted(values.items(), key=lambda item: (-item[1], item[0]))
    higher = sum(v > own.value for v in values.values())
    lower = sum(v < own.value for v in values.values())
    rank = higher + 1
    position = next(i for i, (member, _) in enumerate(ordered) if member == cik)

    def neighbour(index: int) -> Neighbour:
        member, value = ordered[index]
        return Neighbour(
            rank=1 + sum(v > value for v in values.values()),
            name=panel.names.get(member, str(member)),
            cik=member,
            value=value,
            display=value_text(value, unit),
        )

    median = percentile(list(values.values()), 50)
    return Standing(
        year=year,
        period_end=own.end,
        n=n,
        rank=rank,
        percentile=100 * lower / (n - 1),
        value=own.value,
        display=value_text(own.value, unit),
        median=median,
        median_display=value_text(median, unit),
        above=[neighbour(i) for i in range(max(0, position - NEIGHBOURS), position)],
        below=[neighbour(i) for i in range(position + 1, min(n, position + 1 + NEIGHBOURS))],
    )


def _phrase(found: Standing) -> str:
    if found.rank is None:
        return f"cannot be ranked in {found.year} ({found.reason.rstrip('.')})"
    return (
        f"ranks {found.rank} of {found.n} in {found.year} at {found.display} "
        f"(above {found.percentile:.0f}% of the others; class median {found.median_display})"
    )


def peer_standing(
    panel: Panel,
    key: str,
    cik: int,
    year: int,
    ref: RefClass,
    *,
    as_of: str,
    result_id: str,
) -> PeerStanding:
    """The company's standing on ``key`` among ``ref`` in ``year`` and the year before."""
    now = standing(panel, key, cik, year, ref)
    before = standing(panel, key, cik, year - 1, ref)
    label = label_of(key)
    groups = MEASURES["revenue" if key == "revenue_growth" else key].groups
    inputs = [
        ResultInput(
            label=f"{GROUPS[g].label}: every class member's row",
            value=None,
            display="",
            source=frame_source("|".join(GROUPS[g].concepts), f"CY{year - 1} and CY{year}"),
            date=f"CY{year - 1} and CY{year}",
        )
        for g in groups
    ]
    definition = MEASURES["revenue"].definition if key == "revenue_growth" else MEASURES[key].definition
    assumptions = [
        f"Class: {ref.definition}",
        f"Measure: {definition}",
        "Rank 1 is the highest value; the percentile is the share of the other members with a "
        "lower value.",
        "Frames carry no filing date: a value restated later is the restated value.",
    ]
    own_revenue = panel.get("revenue", cik, year)
    if own_revenue is not None and own_revenue.value < ref.floor:
        assumptions.append("The company's own revenue is under the class floor; it is ranked anyway.")
    computed = now.rank is not None
    reading = f"{label} {_phrase(now)} among {ref.name}; a year earlier it {_phrase(before)}."
    return PeerStanding(
        id=result_id,
        kind="peer_standing",
        label=f"{label} among {ref.name}",
        outcome="computed" if computed else "cannot_compute",
        reason="" if computed else now.reason,
        value=now.percentile,
        unit="percent",
        display=(f"rank {now.rank} of {now.n}" if computed else "n/a"),
        formula=(
            f"percentile = 100 × lower ÷ (n − 1) = 100 × {now.n - now.rank - _ties(now)} ÷ "
            f"{now.n - 1}"
            if computed and now.rank is not None
            else ""
        ),
        inputs=inputs,
        assumptions=assumptions,
        reading=reading,
        data_origin="sec_frames",
        as_of=as_of,
        measure=key,
        class_name=ref.name,
        class_definition=ref.definition,
        now=now,
        year_before=before,
    )


def _ties(found: Standing) -> int:
    """How many other members tie the company's value (they are neither higher nor lower)."""
    if found.rank is None or found.percentile is None or found.n < 2:
        return 0
    lower = round(found.percentile * (found.n - 1) / 100)
    return found.n - found.rank - lower


def latest_year(panel: Panel, cik: int, years: Sequence[int]) -> int | None:
    """The newest of ``years`` in which the company has a revenue row."""
    return max((y for y in years if panel.get("revenue", cik, y) is not None), default=None)
