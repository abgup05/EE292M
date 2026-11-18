"""The outside view and the market view inside a run: tied to claims, bounded in time, as of a date.

Offline: SEC frames, 13F tables and company facts are the recorded fixtures, read from disk;
nothing is fetched and no model is asked.
"""

from __future__ import annotations

import gzip
import json
import re
import time
from datetime import date
from pathlib import Path
from typing import Any

from app.core import analysis_policy as rules
from app.core.analysis_models import Analytic
from app.core.analytics import AnalyticsRequest, FactsProvider
from app.core.models import Run, ThesisRequest
from app.core.ports import SourceError
from app.engines.extractive import ExtractiveAnalyst
from app.services.thesis_run import execute_run, new_run
from app.services.view_providers import MAX_PEERS_PER_CLAIM, run_providers
from app.sources.frames import FramesSource
from app.sources.thirteenf import ThirteenFSource
from app.store import FilingCache, Store
from tests.examples_analysis import CLAIMS, FRAMES, MARKET_FACTS, THIRTEENF
from tests.fakes import FakePages
from tests.replay_run import recorded_filings

DECISION = "Whether to buy NVIDIA now"


def _run(tmp_path: Path, name: str, providers: Any = None, as_of: date | None = None) -> Run:
    filings = recorded_filings()
    filings.facts = json.loads(gzip.decompress(MARKET_FACTS.read_bytes()))
    if providers is None:
        providers = run_providers(
            filings, FramesSource(None, FRAMES), ThirteenFSource(None, THIRTEENF)
        )
    request = ThesisRequest(ticker="NVDA", decision=DECISION, claims=CLAIMS, as_of=as_of)
    return execute_run(
        new_run(request),
        Store(tmp_path / f"{name}.sqlite"),
        filings=filings,
        analyst=ExtractiveAnalyst(),
        fetch_page=FakePages({}),
        cache=FilingCache(),
        analytics_providers=providers,
    )


def _of(run: Run, provider: str) -> list[Analytic]:
    return [item for item in run.analysis.analytics if item.provider == provider]


def test_base_rates_and_standings_are_tied_to_the_claims_they_bear_on(tmp_path: Path) -> None:
    run = _run(tmp_path, "views")
    analysis = run.analysis
    assert analysis.providers == ["facts", "outside_view", "market_view"]
    assert analysis.providers_failed == [] and analysis.provider_reasons == {}
    outside = _of(run, "outside_view")
    assert all(item.claim_ids and item.question and item.scope == "claim" for item in outside)
    rates = [item for item in outside if item.kind == "base_rate"]
    # c3 (revenue more than doubled in a fiscal year) and c4 (free cash flow above net income)
    # have a test frames can hold, in two reference classes each; c2's test (held in each of
    # four quarters) cannot be read on annual frames, and the record says so once.
    by_claim = {c: [r for r in rates if r.claim_ids == [c]] for c in ("c1", "c2", "c3", "c4")}
    assert by_claim["c1"] == []
    assert [r.available for r in by_claim["c2"]] == [False] and by_claim["c2"][0].reading
    assert len(by_claim["c3"]) == 2 and len(by_claim["c4"]) == 2
    assert all("not a probability for this company" in r.note for r in rates)
    doubled = next(r for r in by_claim["c3"] if ":size:" in r.id)
    assert doubled.display.startswith("0 of ") and "yoy(revenue)[t] > 100%" in doubled.reading
    peers = [item for item in outside if item.kind == "peer_standing"]
    assert peers and all(item.available for item in peers)
    # A rank by dollars is never shown, and no claim gets more than two standings.
    assert not {item.measure for item in peers} & {"revenue", "free_cash_flow", "capex"}
    for claim in run.claims:
        mine = [p for p in peers if claim.id in p.claim_ids]
        assert len(mine) <= MAX_PEERS_PER_CLAIM
    growth = next(p for p in peers if p.measure == "revenue_growth")
    assert growth.claim_ids == ["c3", "c5"]
    assert {p.measure for p in peers if "c4" in p.claim_ids} == {"fcf_margin", "cash_conversion"}


def test_the_valuation_is_about_the_company_and_implied_growth_sits_by_growth_claims(
    tmp_path: Path,
) -> None:
    run = _run(tmp_path, "market")
    market = {item.kind: item for item in _of(run, "market_view")}
    assert set(market) == {"pe", "fcf_yield", "reverse_dcf"}
    assert all(item.scope == "company" and item.available for item in market.values())
    assert market["pe"].claim_ids == [] and market["fcf_yield"].claim_ids == []
    implied = market["reverse_dcf"]
    assert implied.claim_ids == ["c3", "c5"]
    assert "not a forecast and not a price target" in implied.note
    assert "13F" in market["pe"].note and "2026-09-30" in market["pe"].note
    # Set beside the claim: listed under each claim about revenue, and for the thesis.
    assert implied.id in run.claims[2].analysis.analytic_ids
    assert implied.id not in run.claims[3].analysis.analytic_ids


class _Slow:
    name = "slow_view"
    budget_seconds = 0.2

    def __init__(self) -> None:
        self.finished = False

    def provide(self, request: AnalyticsRequest) -> list[Analytic]:
        time.sleep(1.5)
        self.finished = True
        return [Analytic(id="an:slow", kind="x", label="late")]


class _Down:
    name = "down_view"
    budget_seconds = 5.0

    def provide(self, request: AnalyticsRequest) -> list[Analytic]:
        raise SourceError("EDGAR did not answer (HTTP 503) for the frame Revenues/CY2025")


class _Broken:
    name = "broken_view"
    budget_seconds = 5.0

    def provide(self, request: AnalyticsRequest) -> list[Analytic]:
        raise KeyError("a secret-looking detail that must not reach the record")


def test_a_provider_out_of_time_or_unanswered_is_recorded_and_the_run_carries_on(
    tmp_path: Path,
) -> None:
    slow = _Slow()
    began = time.monotonic()
    run = _run(tmp_path, "failing", [FactsProvider(), slow, _Down(), _Broken()])
    assert not slow.finished, "the run did not wait for the slow provider"
    assert time.monotonic() - began < 30
    analysis = run.analysis
    assert analysis.providers == ["facts", "slow_view", "down_view", "broken_view"]
    assert analysis.providers_failed == ["slow_view", "down_view", "broken_view"]
    assert analysis.provider_reasons == {
        "slow_view": rules.PROVIDER_OUT_OF_TIME.format(seconds=0.2),
        "down_view": "EDGAR did not answer (HTTP 503) for the frame Revenues/CY2025",
        "broken_view": "it failed (KeyError)",
    }
    assert run.coverage.analytics_providers_failed == 3
    lines = [e for e in run.errors if "analytics provider" in e]
    assert len(lines) == 3 and "secret-looking" not in " ".join(run.errors)
    # The facts provider's analytics are all there, and nothing of the late one.
    assert _of(run, "facts") and "an:slow" not in {a.id for a in analysis.analytics}
    plain = _run(tmp_path, "plain", [FactsProvider()])
    assert [c.verdict for c in run.claims] == [c.verdict for c in plain.claims]
    assert run.status == plain.status


DATES = re.compile(r"\b(20\d\d-\d\d-\d\d)\b")


def test_as_of_a_date_neither_view_reads_anything_later(tmp_path: Path) -> None:
    as_of = date(2026, 6, 15)
    run = _run(tmp_path, "asof", as_of=as_of)
    assert run.analysis.providers_failed == []
    views = [*_of(run, "outside_view"), *_of(run, "market_view")]
    assert any(item.available for item in _of(run, "outside_view"))
    market = {item.kind: item for item in _of(run, "market_view")}
    assert market["pe"].available, market["pe"].note
    # The price is the quarter end before the date, from a 13F public by the date.
    assert market["pe"].period == "2026-03-31"
    for item in views:
        text = " ".join([item.id, item.period, item.reading, item.note, item.formula])
        text += " ".join(f"{i.id} {i.label} {i.filed}" for i in item.inputs)
        later = [day for day in DATES.findall(text) if day > as_of.isoformat()]
        assert not later, f"{item.id} names {later}"
        assert "CY2026" not in text and "FY2027" not in text
    # And the same run today does read the later quarter's price.
    today = {item.kind: item for item in _of(_run(tmp_path, "today"), "market_view")}
    assert today["pe"].period == "2026-09-30" and today["pe"].value != market["pe"].value
