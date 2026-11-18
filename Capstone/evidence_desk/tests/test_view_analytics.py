"""The two views as analytics: the shape a provider list expects, and nothing recomputed."""

from __future__ import annotations

from typing import Any

import pytest

from app.core.view_models import MarketView, OutsideView, ResultInput
from app.services.view_analytics import (
    Analytic,
    analytic_input,
    market_analytics,
    outside_analytics,
    peer_measures,
)
from tests import market_examples

SHAPE = {
    "id",
    "provider",
    "data_origin",
    "kind",
    "label",
    "claim_ids",
    "measure",
    "period",
    "value",
    "unit",
    "display",
    "formula",
    "inputs",
    "reading",
    "reading_origin",
    "available",
    "note",
}
INPUT_SHAPE = {"ref_kind", "id", "label", "value", "display", "accession", "form", "filed"}


@pytest.fixture(scope="module")
def views() -> tuple[OutsideView, MarketView]:
    found = market_examples.payloads()
    return (
        OutsideView.model_validate(found["outside-view.json"]),
        MarketView.model_validate(found["market-view.json"]),
    )


def test_every_analytic_is_the_agreed_shape(views: tuple[OutsideView, MarketView]) -> None:
    outside, market = views
    found = [*outside_analytics(outside, ["c1"]), *market_analytics(market, ["c1", "c2"])]
    assert len({a.id for a in found}) == len(found), "ids are unique"
    for analytic in found:
        plain: dict[str, Any] = analytic.model_dump()
        assert set(plain) == SHAPE
        assert all(set(i) == INPUT_SHAPE for i in plain["inputs"])
        assert plain["reading_origin"] == "code" and plain["reading"]
        assert plain["data_origin"] == (
            "sec_frames" if plain["provider"] == "outside_view" else "market_prices"
        )
        assert plain["available"] or plain["note"], "an unavailable analytic says why"
        assert plain["available"] == (plain["value"] is not None)


def test_outside_analytics_carry_the_views_own_numbers(
    views: tuple[OutsideView, MarketView],
) -> None:
    outside, _ = views
    found = {a.id: a for a in outside_analytics(outside, ["c1"])}
    for rate in outside.base_rates:
        analytic = found[rate.id]
        assert (analytic.value, analytic.display, analytic.reading) == (
            rate.value,
            rate.display,
            rate.reading,
        )
        assert analytic.measure == "revenue" and analytic.period == "CY2011 to CY2025"
        assert f"Class: {rate.class_definition}" in analytic.note
        persistence = found[f"{rate.id}:persistence"]
        assert persistence.display.startswith(f"{rate.persisted} of {rate.persist_base} (")
        assert persistence.value == pytest.approx(rate.persisted / rate.persist_base * 100)
    # A revenue claim gets revenue's two standings, not all twelve.
    assert [a.measure for a in found.values() if a.kind == "peer_standing"] == [
        "revenue_growth",
        "revenue",
    ]


def test_market_analytics_trace_each_input_to_its_filing(
    views: tuple[OutsideView, MarketView],
) -> None:
    _, market = views
    found = {a.kind: a for a in market_analytics(market, ["c1"])}
    value = found["market_value"]
    kinds = [(i.ref_kind, i.form) for i in value.inputs]
    filing = ("filing", "13F-HR")
    assert kinds == [("price", "13F-HR"), filing, filing, ("fact", "10-Q")]
    shares = value.inputs[-1]
    assert shares.id == "dei:EntityCommonStockSharesOutstanding"
    assert shares.accession == "0001045810-26-000075" and shares.filed == "2026-08-26"
    assert value.period == "2026-09-30"
    dcf = found["reverse_dcf"]
    assert "not a forecast and not advice" in dcf.note and "Discount rate 9%" in dcf.note
    assert found["reverse_dcf_peer_median_margin"].available is False


def test_a_claim_that_is_not_numeric_gets_an_unavailable_base_rate_and_the_default_standings() -> (
    None
):
    http = market_examples.client()
    payload = http.get(
        "/api/companies/NVDA/outside", params={"claim": "Management is trustworthy"}
    ).json()
    found = outside_analytics(OutsideView.model_validate(payload), ["c9"])
    first = found[0]
    assert (first.kind, first.available, first.value) == ("base_rate", False, None)
    assert "does not compile" in first.note
    assert [a.measure for a in found[1:]] == ["revenue_growth", "operating_margin", "fcf_margin"]


def test_an_input_is_classified_by_the_source_it_names() -> None:
    frame = analytic_input(
        ResultInput(
            label="Revenue: every filer's row",
            value=None,
            display="",
            source="SEC XBRL frame us-gaap/Revenues/USD/CY2024",
        )
    )
    assert (frame.ref_kind, frame.id) == ("frame", "us-gaap/Revenues/USD/CY2024")
    fact = analytic_input(
        ResultInput(
            label="Total debt (LongTermDebtNoncurrent)",
            value=1.0,
            display="$1",
            source="SEC company facts, 10-K/A 0000000001-26-000002",
            filed="2026-02-02",
        )
    )
    assert (fact.ref_kind, fact.id, fact.form, fact.accession) == (
        "fact",
        "LongTermDebtNoncurrent",
        "10-K/A",
        "0000000001-26-000002",
    )
    supplied = analytic_input(
        ResultInput(
            label="Price per share",
            value=9.0,
            display="$9.00",
            source="price supplied on the request for 2026-01-02; not checked against any source",
            date="2026-01-02",
        )
    )
    assert (supplied.ref_kind, supplied.id, supplied.accession) == ("price", "2026-01-02", "")


def test_which_standings_bear_on_a_test() -> None:
    assert peer_measures(["revenue"]) == ["revenue_growth", "revenue"]
    assert peer_measures(["gross_margin", "operating_margin"]) == [
        "gross_margin",
        "operating_margin",
    ]
    assert peer_measures([]) == ["revenue_growth", "operating_margin", "fcf_margin"]
    assert Analytic.model_fields["reading_origin"].default == "code"
