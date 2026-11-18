"""The outside-view and market-view routes: validation at the boundary, as-of, failures."""

from __future__ import annotations

from datetime import date
from typing import Any

import pytest
from fastapi.testclient import TestClient

from app.api import create_app
from app.core.ports import SourceError
from app.sources.frames import FramesSource
from tests import market_examples

GOOD = {"price": 150, "price_date": "2026-11-17"}


@pytest.fixture
def http() -> TestClient:
    return market_examples.client()


def _fields(response: Any) -> set[str]:
    assert response.status_code == 422, response.text
    return {detail["field"] for detail in response.json()["details"]}


@pytest.mark.parametrize(
    ("params", "field"),
    [
        ({**GOOD, "price": 0}, "price"),
        ({**GOOD, "price": -3}, "price"),
        ({"price_date": "2026-11-17"}, "price"),
        ({**GOOD, "price_date": "2026-11-19"}, "price_date"),
        ({**GOOD, "as_of": "2026-06-01"}, "price_date"),
        ({**GOOD, "discount_rate": 3, "terminal_growth": 3}, "terminal_growth"),
        ({**GOOD, "tax_rate": 100}, "tax_rate"),
        ({**GOOD, "sales_to_capital": 0}, "sales_to_capital"),
        ({**GOOD, "claim": "x" * 401}, "claim"),
        ({**GOOD, "price_date": "not a date"}, "price_date"),
    ],
)
def test_market_refuses_bad_input(http: TestClient, params: dict[str, Any], field: str) -> None:
    fields = _fields(http.get("/api/companies/NVDA/market", params=params))
    assert any(f.split(".")[-1] == field for f in fields), fields


@pytest.mark.parametrize(
    ("params", "field"),
    [
        ({"years": 0}, "years"),
        ({"years": 17}, "years"),
        ({"min_revenue": -1}, "min_revenue"),
        ({"as_of": "2027-01-01"}, "as_of"),
    ],
)
def test_outside_refuses_bad_input(http: TestClient, params: dict[str, Any], field: str) -> None:
    fields = _fields(http.get("/api/companies/NVDA/outside", params=params))
    assert any(f.split(".")[-1] == field for f in fields), fields


def test_unknown_ticker_is_refused(http: TestClient) -> None:
    assert _fields(http.get("/api/companies/ZZZZZZ/market", params=GOOD)) == {"ticker"}


def test_market_uses_only_facts_filed_by_the_price_date(http: TestClient) -> None:
    response = http.get(
        "/api/companies/NVDA/market",
        params={"price": 100, "price_date": "2026-03-02", "as_of": "2026-03-02"},
    )
    assert response.status_code == 200, response.text
    for result in response.json()["valuation"]:
        for item in result["inputs"]:
            if item["filed"]:
                assert item["filed"] <= "2026-03-02", (result["id"], item)
            assert item["date"] <= "2026-03-02", (result["id"], item)


def test_market_answers_503_when_edgar_fails() -> None:
    broken = market_examples._filings()
    broken.facts_error = SourceError("EDGAR is down")
    app = create_app(filings=broken, frames=FramesSource(None, market_examples.FRAMES))
    response = TestClient(app).get("/api/companies/NVDA/market", params=GOOD)
    assert response.status_code == 503


def _closes(days: list[str], start: float = 100.0) -> list[dict[str, Any]]:
    return [{"date": d, "close": start + i} for i, d in enumerate(days)]


@pytest.mark.parametrize(
    ("body", "field"),
    [
        ({"closes": []}, "closes"),
        ({"closes": _closes(["2026-01-02", "2026-01-05"]), "extra": 1}, "extra"),
        ({"closes": _closes(["2026-01-02", "2026-01-05"]), "index": "supplied"}, "index_closes"),
        ({"closes": _closes(["2026-01-05", "2026-01-05"])}, "closes"),
        ({"closes": _closes(["2026-01-02", "2026-01-05"]), "accession": "x"}, "accession"),
        ({"closes": _closes(["2026-01-02", "2026-01-05"]), "days": 0}, "days"),
        (
            {"closes": [{"date": "2026-01-02", "close": -1}, {"date": "2026-01-05", "close": 1}]},
            "close",
        ),
    ],
)
def test_reactions_refuse_bad_bodies(http: TestClient, body: dict[str, Any], field: str) -> None:
    fields = _fields(http.post("/api/companies/NVDA/market/reactions", json=body))
    assert any(field in f for f in fields), fields


def test_reactions_read_no_close_after_as_of(http: TestClient) -> None:
    stocks, indexes = market_examples.made_up_closes()
    response = http.post(
        "/api/companies/NVDA/market/reactions",
        json={
            "closes": stocks,
            "index": "supplied",
            "index_closes": indexes,
            "claim": market_examples.MARKET_CLAIM,
            "as_of": "2026-07-10",
        },
    )
    assert response.status_code == 200, response.text
    reactions = response.json()["reactions"]
    assert [r["filed"] for r in reactions] == ["2026-07-02", "2026-05-08", "2026-04-27"]
    for reaction in reactions:
        assert all(w["end"] <= "2026-07-10" for w in reaction["windows"])
    assert reactions[0]["windows"][-1]["end"] == "2026-07-10"


def test_reaction_to_a_named_accession(http: TestClient) -> None:
    stocks, _ = market_examples.made_up_closes()
    response = http.post(
        "/api/companies/NVDA/market/reactions",
        json={"closes": stocks, "accession": "0001045810-26-000060"},
    )
    assert response.status_code == 200, response.text
    (only,) = response.json()["reactions"]
    assert only["filed"] == "2026-07-02"
    assert only["windows"][0]["index_return"] is None


def test_outside_view_as_of_admits_only_years_a_year_old(http: TestClient) -> None:
    response = http.get(
        "/api/companies/NVDA/outside",
        params={"claim": market_examples.OUTSIDE_CLAIM, "as_of": "2025-06-30"},
    )
    assert response.status_code == 200, response.text
    view = response.json()
    assert max(view["years_read"]) <= 2023
    assert date.fromisoformat(view["as_of"]) == date(2025, 6, 30)
