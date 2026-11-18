"""The committed market examples are what the code writes, and their arithmetic checks by hand."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from tests import market_examples


@pytest.fixture(scope="module")
def written(tmp_path_factory: pytest.TempPathFactory) -> dict[str, Any]:
    out = tmp_path_factory.mktemp("market")
    market_examples.write(out)
    return {name: json.loads((out / name).read_text()) for name in market_examples.FILES}


def test_committed_examples_are_up_to_date(written: dict[str, Any]) -> None:
    for name, payload in written.items():
        committed = json.loads((market_examples.OUT / name).read_text())
        assert committed == payload, f"{name} is stale: run make market-examples"
    for name, text in market_examples.texts(written).items():
        assert (market_examples.OUT / name).read_text() == text, f"{name} is stale"


def _by_kind(view: dict[str, Any]) -> dict[str, dict[str, Any]]:
    return {result["kind"]: result for result in view["valuation"]}


def _sum(result: dict[str, Any], word: str) -> float:
    return sum(i["value"] for i in result["inputs"] if i["label"].startswith(word))


def test_valuation_agrees_with_its_own_inputs(written: dict[str, Any]) -> None:
    results = _by_kind(written["market-view.json"])
    market = results["market_value"]
    shares = _sum(market, "Shares outstanding")
    # The price is the manager's position value ÷ its shares, both inputs of the result.
    position = next(i["value"] for i in market["inputs"] if "value of the position" in i["label"])
    held = next(i["value"] for i in market["inputs"] if "shares held" in i["label"])
    assert market["value"] == pytest.approx(position / held * shares)
    ev = results["enterprise_value"]
    expected_ev = (
        market["value"]
        + _sum(ev, "Total debt")
        - _sum(ev, "Cash")
        - _sum(ev, "Marketable securities")
    )
    assert ev["value"] == pytest.approx(expected_ev)
    assert results["ev_sales"]["value"] == pytest.approx(
        expected_ev / _sum(results["ev_sales"], "Revenue")
    )
    assert results["pe"]["value"] == pytest.approx(
        market["value"] / _sum(results["pe"], "Net income")
    )
    fcf_inputs = results["p_fcf"]["inputs"]
    ocf = sum(i["value"] for i in fcf_inputs if "NetCashProvided" in i["label"])
    capex = sum(i["value"] for i in fcf_inputs if "NetCashProvided" not in i["label"])
    assert results["p_fcf"]["value"] == pytest.approx(market["value"] / (ocf - capex))
    assert results["fcf_yield"]["value"] == pytest.approx((ocf - capex) / market["value"] * 100)
    assert all(r["data_origin"] == "market_prices" for r in results.values())


def test_reverse_dcf_growth_discounts_back_to_the_enterprise_value(written: dict[str, Any]) -> None:
    view = written["market-view.json"]
    dcf = view["reverse_dcf"]
    ev = _by_kind(view)["enterprise_value"]["value"]
    revenue = _sum(_by_kind(view)["ev_sales"], "Revenue")
    income = sum(i["value"] for i in dcf["inputs"] if i["label"].startswith("Operating income"))
    margin, tax, rate, terminal = income / revenue, 0.21, 0.09, 0.03
    s2c = float(
        next(a for a in dcf["assumptions"] if a.startswith("Sales-to-capital"))
        .split()[1]
        .rstrip(":")
    )
    growth = dcf["value"] / 100
    # Year by year, written out again here rather than calling present_value.
    total, previous, flow = 0.0, revenue, 0.0
    for year in range(1, 11):
        current = previous * (1 + growth)
        flow = current * margin * (1 - tax) - (current - previous) / s2c
        total += flow / (1 + rate) ** year
        previous = current
    following = previous * (1 + terminal)
    last = following * margin * (1 - tax) - (following - previous) / s2c
    total += last / (rate - terminal) / (1 + rate) ** 10
    # s2c is printed to two decimals, so allow the rounding.
    assert total == pytest.approx(ev, rel=2e-3)
    assert len(dcf["grid"]) == 15
    assert "not a forecast" in dcf["label_note"]


def test_reaction_is_the_close_to_close_arithmetic(written: dict[str, Any]) -> None:
    stocks, indexes = market_examples.made_up_closes()
    stock = {c["date"]: c["close"] for c in stocks}
    index = {c["date"]: c["close"] for c in indexes}
    reactions = written["reactions.json"]["reactions"]
    assert [r["filed"] for r in reactions] == ["2026-11-12", "2026-07-02", "2026-05-08"]
    dropped = next(r for r in reactions if r["filed"] == market_examples.DROP_AFTER)
    window = dropped["windows"][0]
    # The last close before the filing day (2026-07-01) to the third trading day after.
    assert (window["start"], window["end"]) == ("2026-07-01", "2026-07-06")
    own = stock["2026-07-06"] / stock["2026-07-01"] - 1
    market = index["2026-07-06"] / index["2026-07-01"] - 1
    assert window["excess"] == pytest.approx((own - market) * 100)
    # The hand-made 10% drop shows through the made-up noise.
    assert window["excess"] < -3


def test_outside_view_counts_are_stated_with_their_denominators(written: dict[str, Any]) -> None:
    view = written["outside-view.json"]
    assert view["test"] == "yoy(revenue)[FY2026] > 50%"
    for rate in view["base_rates"]:
        assert rate["data_origin"] == "sec_frames"
        assert rate["computable"] >= rate["held"] > 0
        assert f"{rate['held']} of {rate['computable']}" in rate["reading"]
    revenue = next(p for p in view["peers"] if p["measure"] == "revenue")
    assert revenue["now"]["rank"] == 1 and revenue["now"]["n"] >= 3


def test_examples_read_nothing_live(written: dict[str, Any]) -> None:
    assert not any("not on disk" in note for note in written["outside-view.json"]["notes"])
    assert not any("not on disk" in note for note in written["market-view.json"]["notes"])


def test_example_files_are_where_the_docs_say() -> None:
    assert sorted(p.name for p in Path(market_examples.OUT).glob("*.json")) == sorted(
        market_examples.FILES
    )
    assert sorted(p.name for p in Path(market_examples.OUT).glob("*.txt")) == sorted(
        market_examples.TEXTS
    )


def test_reverse_dcf_by_a_closed_form(written: dict[str, Any]) -> None:
    # A second route to the same value, with no loop: the ten years are a geometric series.
    # With q = (1 + g) ÷ (1 + r), k = margin × (1 − tax) and s the sales-to-capital ratio,
    #   years 1..10: R0 × (k − g ÷ (s × (1 + g))) × q × (1 − q^10) ÷ (1 − q)
    #   after:       R0 × (1 + g)^10 × ((1 + gt) × k − gt ÷ s) ÷ (r − gt) ÷ (1 + r)^10
    view = written["market-view.json"]
    dcf = view["reverse_dcf"]
    results = _by_kind(view)
    ev = results["enterprise_value"]
    revenue = _sum(results["ev_sales"], "Revenue")
    income = sum(i["value"] for i in dcf["inputs"] if i["label"].startswith("Operating income"))
    debt = _sum(ev, "Total debt")
    cash = _sum(ev, "Cash") + _sum(ev, "Marketable securities")
    equity = float(
        next(a for a in dcf["assumptions"] if a.startswith("Sales-to-capital"))
        .split("(equity $")[1]
        .split("B")[0]
    )
    s2c = revenue / (equity * 1e9 + debt - cash)
    k, g, r, gt = income / revenue * (1 - 0.21), dcf["value"] / 100, 0.09, 0.03
    q = (1 + g) / (1 + r)
    years = revenue * (k - g / (s2c * (1 + g))) * q * (1 - q**10) / (1 - q)
    after = revenue * (1 + g) ** 10 * ((1 + gt) * k - gt / s2c) / (r - gt) / (1 + r) ** 10
    # Equity is read back from a figure printed to 10 million dollars: allow that rounding.
    assert years + after == pytest.approx(ev["value"], rel=1e-3)
    assert dcf["implied_revenue"] == pytest.approx(revenue * (1 + g) ** 10)


def test_the_price_implied_growth_is_set_beside_what_filers_of_its_size_did(
    written: dict[str, Any],
) -> None:
    dcf = written["market-view.json"]["reverse_dcf"]
    spread = dcf["distribution"]
    assert spread["n"] > 0 and f"Of {spread['n']} ten-year spans" in dcf["reading"]
    assert spread["band"] in dcf["reading"] and spread["window"] in dcf["reading"]
    assert f"{spread['at_least']} grew at least that fast" in dcf["reading"]
    assert spread["at_least_of"] == dcf["value"]
    kinds = [s["kind"] for s in dcf["scenarios"]]
    assert kinds == ["reverse_dcf_peer_median_margin", "reverse_dcf_peer_p90_margin"]
    top = dcf["scenarios"][1]
    # A lower margin needs more growth for the same price, when growth adds value at all.
    assert top["value"] > dcf["value"]
