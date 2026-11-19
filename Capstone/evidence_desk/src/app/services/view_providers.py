"""The outside view and the market view as analytics providers of a run's analysis.

:class:`OutsideProvider` asks, of a claim's own test, how often it has been true of
comparable companies and whether it lasted (base rates from SEC's XBRL frames), and where
the company stands among its industry on the measures a claim bears on.
:class:`MarketProvider` asks what is being paid at the last price SEC's Form 13F filings
give, and what growth that price already assumes (a reverse DCF under stated assumptions).

Both read EDGAR during a run (frames, 13F tables; each kept on disk once read), so each has
a time budget (:mod:`app.core.analysis_policy`) and :func:`app.services.analysis` records
one that fails or runs out of time and carries on. Both honour the run's ``as_of``: the
views admit no frame, price or fact after it, and the company's facts are the run's own
payload, cut again by the views at the dates they use.

Not every result of a view becomes an analytic. Kept: what answers a question about a claim
or about the decision. Left out as inputs of the others, as repeats or as a table: the
market value, enterprise value, EV to sales and price to free cash flow (the free cash flow
yield says the last); the persistence count and the two margin scenarios as lines of their
own (the base rate's and the implied growth's readings carry them); a peer standing by
dollars (it says only that the company is large) or of a measure no claim bears on. The
valuation is about the decision and is tied to no claim; the implied growth is also set
beside each claim about revenue. ``GET /api/companies/{ticker}/analytics``
serves all of them.
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any

from app.core import analysis_policy as rules
from app.core.analysis_models import Analytic, AnalyticInput, AnalyticUnit
from app.core.analytics import AnalyticsProvider, AnalyticsRequest, FactsProvider
from app.core.fact_models import CompanyProfile
from app.core.models import Company
from app.core.ports import FilingSource
from app.services import view_analytics
from app.services.market_view import market_view
from app.services.outside_view import outside_view
from app.sources import reference
from app.sources.frames import FramesSource
from app.sources.reference import PACK_NOTE, Pack, PackFrames, PackThirteenF
from app.sources.thirteenf import QuarterEndPrices, ThirteenFSource

Q_BASE_RATE = "How often has this been true of comparable companies, and did it last?"
Q_PEER = "Where does the company stand among its industry on this?"
Q_PE = "What is being paid for a dollar of earnings?"
Q_FCF_YIELD = "What does its free cash flow yield at this price?"
Q_IMPLIED = "What growth does the price already assume?"
Q_PRICE = "What is the company priced at?"
BASE_RATE_CAVEAT = (
    "A base rate is a count of what happened to other companies in past years; it is not a "
    "probability for this company and not a forecast."
)
IMPLIED_CAVEAT = (
    "An implied growth is arithmetic: the growth at which a discounted cash flow under the "
    "stated assumptions equals the price. Change an assumption and it changes; it is not a "
    "forecast and not a price target."
)
MAX_PEERS_PER_CLAIM = 2
UNITS: dict[str, AnalyticUnit] = {
    "USD": "USD",
    "USD_per_share": "USD_per_share",
    "percent": "percent",
    "multiple": "multiple",
    "shares": "shares",
}
# The valuation lines kept, and the question each answers about the decision.
VALUATION: dict[str, str] = {"pe": Q_PE, "fcf_yield": Q_FCF_YIELD}
GROWTH_MEASURES = ("revenue",)
# Peer standings never shown: a rank by dollars says only that the company is large.
AMOUNTS = ("revenue", "operating_cash_flow", "capex", "free_cash_flow")
# A catalogue measure, and the peer standings that bear on a claim about it. An amount in
# dollars is ranked through its rate (a rank by size says only that the company is large).
PEERS_OF: dict[str, tuple[str, ...]] = {
    "revenue": ("revenue_growth",),
    "free_cash_flow": ("fcf_margin", "cash_conversion"),
    "operating_cash_flow": ("cash_conversion",),
    "net_income": ("net_margin",),
    "capex": ("capex_ratio",),
    "gross_profit": ("gross_margin",),
    "operating_income": ("operating_margin",),
    "rnd": ("rnd_ratio",),
}


class _RunFilings:
    """The run's filing source, answering for the company's facts with the payload the run
    already read and for its industry code from the reference pack when the pack lists it
    (no request for either); everything else is the source's own."""

    def __init__(
        self,
        inner: FilingSource,
        company: Company,
        payload: dict[str, Any] | None,
        pack: Pack | None = None,
    ):
        self._inner, self._company, self._payload, self._pack = inner, company, payload, pack

    def company_profile(self, company: Company) -> CompanyProfile:
        """The pack's industry code for a filer it lists; else the source's."""
        frames = self._pack.frames if self._pack else None
        listed = frames.filers.get(company.cik) if frames else None
        if frames is None or listed is None or not listed[1]:
            return self._inner.company_profile(company)
        return CompanyProfile(
            cik=company.cik,
            ticker=company.ticker,
            name=company.name,
            sic=listed[1],
            sic_description=frames.sic_names.get(listed[1], ""),
        )

    def company_facts(self, company: Company) -> dict[str, Any]:
        """The run's payload for the run's company; the source's for any other."""
        if self._payload is not None and company.cik == self._company.cik:
            return self._payload
        return self._inner.company_facts(company)

    def __getattr__(self, name: str) -> Any:
        return getattr(self._inner, name)


def adapt(
    found: view_analytics.Analytic,
    question: str,
    claim_ids: Sequence[str],
    *,
    scope: str = "claim",
    caveat: str = "",
) -> Analytic:
    """A view's analytic in the run's shape: the same numbers and sentences, with the
    question it answers, the claims it bears on and, in ``note``, what the number is not."""
    return Analytic(
        id=f"an:{found.id}",
        provider=found.provider,
        data_origin=found.data_origin,
        kind=found.kind,
        label=found.label,
        question=question,
        scope=scope,  # type: ignore[arg-type]
        claim_ids=list(claim_ids),
        measure=found.measure,
        period=found.period,
        value=found.value,
        unit=UNITS.get(found.unit, "count"),
        display=found.display,
        formula=found.formula,
        inputs=[
            AnalyticInput(
                ref_kind=item.ref_kind,
                id=item.id,
                label=item.label,
                value=item.value,
                display=item.display,
                accession=item.accession,
                form=item.form,
                filed=item.filed,
            )
            for item in found.inputs
        ],
        reading=found.reading,
        available=found.available,
        note=" ".join(part for part in (found.note, caveat) if part),
    )


def _dated(items: list[Analytic], source: object) -> list[Analytic]:
    """``items`` with the reference pack's date in each note, when ``source`` answered from
    the pack: a reader must know the numbers are SEC's as of that day."""
    pack = getattr(source, "pack", None)
    if pack is None or not getattr(source, "used", False):
        return items
    said = PACK_NOTE.format(built=pack.built.isoformat())
    for item in items:
        if said not in item.note:
            item.note = f"{item.note} {said}".strip()
    return items


def _merged(items: Sequence[Analytic]) -> list[Analytic]:
    """One analytic per id, its claims those of every copy, in order."""
    out: dict[str, Analytic] = {}
    for item in items:
        kept = out.setdefault(item.id, item)
        kept.claim_ids = list(dict.fromkeys([*kept.claim_ids, *item.claim_ids]))
    return list(out.values())


class OutsideProvider:
    """Base rates of each computed claim's test and the company's standing among its peers."""

    name = view_analytics.OUTSIDE_PROVIDER
    budget_seconds: float = rules.OUTSIDE_BUDGET_SECONDS

    def __init__(
        self, filings: FilingSource, frames: FramesSource, pack: Pack | None = None
    ) -> None:
        self.filings, self.frames, self.pack = filings, frames, pack

    def provide(self, request: AnalyticsRequest) -> list[Analytic]:
        """For a claim with a computed test: the base rate of the test in each reference
        class. For every claim: its measures' peer standings, at most
        :data:`MAX_PEERS_PER_CLAIM`. Nothing for a claim with neither a test nor a measure."""
        company = request.company
        if company is None or request.today is None:
            return []
        filings = _RunFilings(self.filings, company, request.payload, self.pack)
        frames = (
            PackFrames(self.pack.frames, self.frames, company.cik) if self.pack else self.frames
        )
        asking = {
            claim_id: text
            for claim_id, text in request.claims.items()
            if claim_id in request.tests or request.measures.get(claim_id)
        }
        out: list[Analytic] = []
        for claim_id, text in asking.items():
            view = outside_view(
                company,
                text if claim_id in request.tests else "",
                filings,  # type: ignore[arg-type]
                frames,
                today=request.today,
                as_of=request.as_of,
            )
            for item in view_analytics.outside_analytics(view, [claim_id]):
                if item.kind == "base_rate":
                    out.append(adapt(item, Q_BASE_RATE, [claim_id], caveat=BASE_RATE_CAVEAT))
            by_measure = {peer.measure: peer for peer in view.peers}
            wanted = self._peer_measures(view.test_measures, request.measures.get(claim_id, []))
            standings = [
                view_analytics.peer_analytic(by_measure[key], [claim_id])
                for key in wanted
                if key in by_measure
            ]
            out += [adapt(item, Q_PEER, [claim_id]) for item in standings if item.available][
                :MAX_PEERS_PER_CLAIM
            ]
        return _merged(_dated(out, frames))

    @staticmethod
    def _peer_measures(test_measures: Sequence[str], keys: Sequence[str]) -> list[str]:
        wanted: list[str] = []
        for key in [*test_measures, *keys]:
            for measure in PEERS_OF.get(key, (key,)):
                if measure not in wanted and measure not in AMOUNTS:
                    wanted.append(measure)
        return wanted


class MarketProvider:
    """What is paid at the last price SEC's 13F filings give, and the growth it assumes."""

    name = view_analytics.MARKET_PROVIDER
    budget_seconds: float = rules.MARKET_BUDGET_SECONDS

    def __init__(
        self,
        filings: FilingSource,
        frames: FramesSource | None,
        thirteenf: ThirteenFSource,
        pack: Pack | None = None,
    ) -> None:
        self.filings, self.frames, self.thirteenf, self.pack = filings, frames, thirteenf, pack

    def provide(self, request: AnalyticsRequest) -> list[Analytic]:
        """Price to earnings, the free cash flow yield and the growth the price implies, about
        the company as a whole; the implied growth also for each claim about revenue. With
        no price, one line saying why."""
        company = request.company
        if company is None or request.today is None:
            return []
        day = request.as_of or request.today
        frames, thirteenf = self.frames, self.thirteenf
        if self.pack is not None:
            thirteenf = PackThirteenF(self.pack.prices, self.thirteenf, day)
            if frames is not None:
                frames = PackFrames(self.pack.frames, frames, company.cik)
        view = market_view(
            company,
            _RunFilings(self.filings, company, request.payload, self.pack),  # type: ignore[arg-type]
            frames,
            prices=QuarterEndPrices(thirteenf),
            today=request.today,
            as_of=request.as_of,
        )

        def tied(measures: Sequence[str]) -> list[str]:
            return [c for c, keys in request.measures.items() if set(measures) & set(keys)]

        out: list[Analytic] = []
        found = view_analytics.market_analytics(view, [])
        # Without a market value nothing else can be had: one line says why, not five.
        priced = any(item.kind == "market_value" and item.available for item in found)
        for item in found:
            if item.kind == "market_value" and not item.available:
                out.append(adapt(item, Q_PRICE, [], scope="company"))
            elif item.kind in VALUATION:
                out.append(adapt(item, VALUATION[item.kind], [], scope="company"))
            elif item.kind == "reverse_dcf" and (item.available or priced):
                growth = tied(GROWTH_MEASURES)
                out.append(adapt(item, Q_IMPLIED, growth, scope="company", caveat=IMPLIED_CAVEAT))
        price = (
            f" The price is {view.price_source}, of {view.price_day}"
            + (f" (public {view.price_known})" if view.price_known else "")
            + "."
            if view.price_day
            else ""
        )
        for item in out:
            if item.available and price and item.kind in VALUATION:
                item.note = (item.note + price).strip()
        stale = getattr(thirteenf, "stale", "")
        if stale:
            for item in out:
                item.note = f"{item.note} {stale}".strip()
        return _dated(_dated(out, thirteenf), frames)


USE_SHIPPED_PACK = "shipped"


def run_providers(
    filings: FilingSource,
    frames: FramesSource,
    thirteenf: ThirteenFSource,
    pack: Pack | None | str = USE_SHIPPED_PACK,
) -> tuple[AnalyticsProvider, ...]:
    """The providers of a run that may read EDGAR: the run's own facts, then the outside view
    and the market view. Both views read the reference pack shipped with the app first
    (``pack``; None for none, as the offline examples ask, whose fixtures stand in for it)
    and ``frames`` and ``thirteenf`` only for what it lacks."""
    found = reference.load() if pack == USE_SHIPPED_PACK else pack
    assert found is None or isinstance(found, Pack)
    return (
        FactsProvider(),
        OutsideProvider(filings, frames, found),
        MarketProvider(filings, frames, thirteenf, found),
    )
