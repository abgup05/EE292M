"""The outside view and the market view as a flat list of analytics, one shape for both.

A run's analysis is a list of analytics from several providers. :func:`outside_analytics`
and :func:`market_analytics` are this module's two: each takes a view already computed
and returns its results as :class:`Analytic` records, the shape a provider list expects
(``model_dump()`` gives the plain dict):

    id, provider, data_origin ("sec_frames" | "market_prices"), kind, label, claim_ids,
    measure, period, value, unit, display, formula,
    inputs [{ref_kind, id, label, value, display, accession, form, filed}],
    reading (one templated sentence), reading_origin ("code"), available, note

Nothing is computed here: every value, display, formula and sentence is the view's own.
``note`` carries what a reader must know to use the number: why it is not available, or
the reference class and the assumptions, joined. Not every result of a view becomes an
analytic: of the twelve peer standings only those of the measures the claim's test
names (else :data:`DEFAULT_PEER_MEASURES`), so that a claim gets the standings that bear
on it and not a table.
"""

from __future__ import annotations

import re
from collections.abc import Sequence
from typing import Literal

from pydantic import BaseModel, Field

from app.core.metrics import percent_text
from app.core.view_models import (
    AnalysisResult,
    BaseRate,
    MarketView,
    OutsideView,
    PeerStanding,
    ResultInput,
)

OUTSIDE_PROVIDER = "outside_view"
MARKET_PROVIDER = "market_view"
DEFAULT_PEER_MEASURES: tuple[str, ...] = ("revenue_growth", "operating_margin", "fcf_margin")
MAX_PEER_ANALYTICS = 4
RefKind = Literal["frame", "fact", "filing", "price", "computed", "other"]

_FILING = re.compile(r"\b((?:10-[KQ]|8-K|20-F|40-F|13F-HR)(?:/A)?) (\d{10}-\d{2}-\d{6})\b")
_CONCEPT = re.compile(r"\(([A-Za-z][A-Za-z0-9:]+)(?:, derived)?\)\s*$")


class AnalyticInput(BaseModel):
    """One number an analytic used, and the record it can be traced to.

    ``ref_kind`` says what ``id`` names: a ``frame`` (``us-gaap/Revenues/USD/CY2024``), a
    ``fact`` (its concept), a ``filing`` (its accession), a ``price`` (its date), or a
    value ``computed`` from the inputs before it.
    """

    ref_kind: RefKind
    id: str
    label: str
    value: float | None
    display: str
    accession: str = ""
    form: str = ""
    filed: str = ""


class Analytic(BaseModel):
    """One result in the shape every analytics provider returns."""

    id: str
    provider: str
    data_origin: Literal["sec_frames", "market_prices"]
    kind: str
    label: str
    claim_ids: list[str] = Field(default_factory=list)
    measure: str = ""
    period: str = ""
    value: float | None = None
    unit: str = ""
    display: str = "n/a"
    formula: str = ""
    inputs: list[AnalyticInput] = Field(default_factory=list)
    reading: str = ""
    reading_origin: Literal["code"] = "code"
    available: bool = True
    note: str = ""


def analytic_input(found: ResultInput) -> AnalyticInput:
    """A view's input as an analytic's: its kind and id read from the source it names."""
    filing = _FILING.search(found.source)
    form, accession = (filing.group(1), filing.group(2)) if filing else ("", "")
    concept = _CONCEPT.search(found.label)
    kind: RefKind
    if found.source.startswith("SEC XBRL frame "):
        kind, ref = "frame", found.source.removeprefix("SEC XBRL frame ")
    elif found.source.startswith("SEC company facts"):
        kind, ref = "fact", concept.group(1) if concept else found.label
    elif found.source.startswith("SEC Form "):
        kind, ref = "filing", accession
    elif "price" in found.source or "close" in found.label.lower():
        kind, ref = "price", found.date
    elif found.source.startswith("computed"):
        kind, ref = "computed", found.label
    else:
        kind, ref = "other", found.label
    return AnalyticInput(
        ref_kind=kind,
        id=ref,
        label=found.label,
        value=found.value,
        display=found.display,
        accession=accession,
        form=form,
        filed=found.filed,
    )


def _note(result: AnalysisResult, *more: str) -> str:
    first = result.reason if result.outcome != "computed" else result.note
    return " ".join(part for part in (first, *more, *result.assumptions) if part)


def _analytic(
    result: AnalysisResult,
    provider: str,
    claim_ids: Sequence[str],
    *,
    measure: str = "",
    period: str = "",
    note: str | None = None,
) -> Analytic:
    return Analytic(
        id=result.id,
        provider=provider,
        data_origin=result.data_origin,
        kind=result.kind,
        label=result.label,
        claim_ids=list(claim_ids),
        measure=measure,
        period=period,
        value=result.value,
        unit=result.unit,
        display=result.display,
        formula=result.formula,
        inputs=[analytic_input(i) for i in result.inputs],
        reading=result.reading or result.reason,
        available=result.outcome == "computed",
        note=_note(result) if note is None else note,
    )


def _persistence(rate: BaseRate, claim_ids: Sequence[str], measure: str, period: str) -> Analytic:
    """How often the test, once true, was still true a year later: its own analytic."""
    available = rate.outcome == "computed" and rate.persist_base > 0
    share = rate.persisted / rate.persist_base * 100 if available else None
    return Analytic(
        id=f"{rate.id}:persistence",
        provider=OUTSIDE_PROVIDER,
        data_origin="sec_frames",
        kind="persistence",
        label=f"Persistence of {rate.annual_test} among {rate.class_name}",
        claim_ids=list(claim_ids),
        measure=measure,
        period=period,
        value=share,
        unit="percent",
        display=(
            f"{rate.persisted} of {rate.persist_base} ({percent_text(share)})"
            if share is not None
            else "n/a"
        ),
        formula=(
            f"still held a year later ÷ held and readable a year later = {rate.persisted} ÷ "
            f"{rate.persist_base}"
            if available
            else ""
        ),
        inputs=[analytic_input(i) for i in rate.inputs],
        reading=(
            f"Of the {rate.persist_base} company-years among {rate.class_name} in which "
            f"{rate.annual_test} held and the next year could be read, it held again in "
            f"{rate.persisted}."
            if available
            else "No company-year in which the test held could be read a year later."
        ),
        available=available,
        note=(
            f"Class: {rate.class_definition}. A company-year whose next year cannot be read "
            "(the filer stopped filing or was bought) is in neither count."
        ),
    )


def outside_analytics(view: OutsideView, claim_ids: Sequence[str]) -> list[Analytic]:
    """The outside view's results for a claim: each base rate, its persistence, the standings.

    A view with no test (the claim did not compile, or frames cannot hold its test) gives
    one unavailable analytic that says why, then the default standings.
    """
    found: list[Analytic] = []
    measure = view.test_measures[0] if view.test_measures else ""
    for rate in view.base_rates:
        years = [y.year for y in rate.years]
        period = f"CY{min(years)} to CY{max(years)}" if years else ""
        found.append(_analytic(rate, OUTSIDE_PROVIDER, claim_ids, measure=measure, period=period))
        found.append(_persistence(rate, claim_ids, measure, period))
    if not view.base_rates and view.claim.strip():
        found.append(
            Analytic(
                id=f"base_rate:{view.company.ticker}:none:{view.as_of}",
                provider=OUTSIDE_PROVIDER,
                data_origin="sec_frames",
                kind="base_rate",
                label="Base rate of the claim's test",
                claim_ids=list(claim_ids),
                reading=view.compile_note or "No base rate was computed.",
                available=False,
                note=view.compile_note,
            )
        )
    by_measure = {peer.measure: peer for peer in view.peers}
    wanted = [m for m in peer_measures(view.test_measures) if m in by_measure]
    for key in wanted[:MAX_PEER_ANALYTICS]:
        peer = by_measure[key]
        period = f"CY{peer.now.year}" if peer.now else ""
        found.append(_analytic(peer, OUTSIDE_PROVIDER, claim_ids, measure=key, period=period))
    return found


def peer_analytic(peer: PeerStanding, claim_ids: Sequence[str]) -> Analytic:
    """One peer standing as an analytic (a run's provider chooses which standings it wants)."""
    period = f"CY{peer.now.year}" if peer.now else ""
    return _analytic(peer, OUTSIDE_PROVIDER, claim_ids, measure=peer.measure, period=period)


def peer_measures(test_measures: Sequence[str]) -> list[str]:
    """Which standings bear on a test of ``test_measures``: its own, with revenue's growth."""
    wanted: list[str] = []
    for measure in test_measures:
        for key in ("revenue_growth", "revenue") if measure == "revenue" else (measure,):
            if key not in wanted:
                wanted.append(key)
    return wanted or list(DEFAULT_PEER_MEASURES)


def market_analytics(view: MarketView, claim_ids: Sequence[str]) -> list[Analytic]:
    """The market view's results: the valuation, what the price implies, each reaction."""
    found = [
        _analytic(result, MARKET_PROVIDER, claim_ids, measure=result.kind, period=view.price_day)
        for result in view.valuation
    ]
    dcf = view.reverse_dcf
    if dcf is not None:
        found.append(
            _analytic(
                dcf,
                MARKET_PROVIDER,
                claim_ids,
                measure="revenue",
                period=view.price_day,
                note=_note(dcf, dcf.label_note),
            )
        )
        found += [
            _analytic(s, MARKET_PROVIDER, claim_ids, measure="revenue", period=view.price_day)
            for s in dcf.scenarios
        ]
    found += [
        _analytic(r, MARKET_PROVIDER, claim_ids, measure="price", period=r.filed)
        for r in view.reactions
    ]
    return found
