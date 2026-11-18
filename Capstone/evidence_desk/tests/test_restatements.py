"""The restatement ledger: every metric and period whose value differs between filings.

Synthetic facts test each rule; the recorded fixtures test two restatements known
from the companies' own reports (Microsoft's fiscal 2016 revenue restated for ASC 606
from 85,320 to 91,154 USD millions in its fiscal 2018 10-K; NVIDIA's fiscal 2024
diluted EPS first reported as $11.93 and as $1.19 after the ten-for-one split).
"""

from __future__ import annotations

from datetime import date

import pytest

from app.core.facts import FactBook
from app.core.restatements import build_ledger, same_value
from tests.lookahead import late_refs, pruned
from tests.test_facts import companyfacts, fact, load_fixture

MILLION = 1_000_000


def _ledger(concepts: dict, as_of: date | None = None):
    return build_ledger(FactBook(companyfacts(concepts), as_of=as_of), ticker="TEST")


def test_a_value_changed_by_a_later_filing_is_listed_with_both_filings() -> None:
    ledger = _ledger(
        {
            "Revenues": [
                fact(100 * MILLION, "2024-12-31", "2024-01-01", filed="2025-02-01", accn="a-1"),
                fact(100 * MILLION, "2024-12-31", "2024-01-01", filed="2025-05-01", accn="q-1"),
                fact(90 * MILLION, "2024-12-31", "2024-01-01", filed="2026-02-01", accn="a-2"),
            ]
        }
    )
    assert ledger.periods_checked == 1 and ledger.periods_restated == 1
    (entry,) = ledger.entries
    assert (entry.key, entry.period, entry.start, entry.end) == (
        "revenue",
        "annual",
        "2024-01-01",
        "2024-12-31",
    )
    assert entry.reports == 3
    first, later = entry.values
    assert (first.accession, first.filed, first.value, first.change) == (
        "a-1",
        "2025-02-01",
        100 * MILLION,
        None,
    )
    assert (later.accession, later.value, later.change) == ("a-2", 90 * MILLION, -10 * MILLION)
    assert later.change_percent == pytest.approx(-10.0)
    assert later.display == "$90.0M" and later.change_display == "-$10.0M"
    assert later.change_percent_display == "-10.0%"


def test_a_difference_within_the_tolerance_is_rounding_not_a_restatement() -> None:
    ledger = _ledger(
        {
            "Revenues": [
                fact(96_221 * MILLION, "2026-07-26", "2026-04-27", filed="2026-08-26", accn="a"),
                fact(96_222 * MILLION, "2026-07-26", "2026-04-27", filed="2027-08-26", accn="b"),
            ]
        }
    )
    assert ledger.periods_checked == 1 and ledger.entries == []
    assert same_value(1.19, 1.195, "USD/shares") and not same_value(1.19, 1.21, "USD/shares")
    assert "1,000,000" in ledger.tolerance_note and "0.01" in ledger.tolerance_note


def test_a_value_that_goes_back_to_an_earlier_one_is_marked() -> None:
    ledger = _ledger(
        {
            "Revenues": [
                fact(4170 * MILLION, "2017-07-30", "2017-01-30", filed="2017-08-23", accn="q"),
                fact(2230 * MILLION, "2017-07-30", "2017-01-30", filed="2018-02-28", accn="k"),
                fact(4170 * MILLION, "2017-07-30", "2017-01-30", filed="2018-08-16", accn="q2"),
            ]
        }
    )
    (entry,) = ledger.entries
    assert [v.returns_to_earlier for v in entry.values] == [False, False, True]


def test_a_period_reported_once_is_not_checked() -> None:
    ledger = _ledger({"Revenues": [fact(1.0, "2024-12-31", "2024-01-01")]})
    assert ledger.periods_checked == 0 and ledger.entries == []


def test_one_filing_tagging_two_concepts_counts_once_by_the_preferred_concept() -> None:
    ledger = _ledger(
        {
            "RevenueFromContractWithCustomerExcludingAssessedTax": [
                fact(80 * MILLION, "2024-12-31", "2024-01-01", filed="2025-02-01", accn="a"),
                fact(80 * MILLION, "2024-12-31", "2024-01-01", filed="2026-02-01", accn="b"),
            ],
            # A broader total in the same filings: not a restatement of the preferred concept.
            "Revenues": [
                fact(95 * MILLION, "2024-12-31", "2024-01-01", filed="2025-02-01", accn="a"),
                fact(95 * MILLION, "2024-12-31", "2024-01-01", filed="2026-02-01", accn="b"),
            ],
        }
    )
    assert ledger.periods_checked == 1 and ledger.entries == []


def test_a_restatement_under_a_new_concept_is_listed_and_says_the_concept_changed() -> None:
    ledger = _ledger(
        {
            "SalesRevenueNet": [
                fact(85 * MILLION, "2016-06-30", "2015-07-01", filed="2016-07-28", accn="k16"),
            ],
            "RevenueFromContractWithCustomerExcludingAssessedTax": [
                fact(91 * MILLION, "2016-06-30", "2015-07-01", filed="2018-08-03", accn="k18"),
            ],
        }
    )
    (entry,) = ledger.entries
    assert entry.concept_changed
    assert [v.concept for v in entry.values] == [
        "SalesRevenueNet",
        "RevenueFromContractWithCustomerExcludingAssessedTax",
    ]


def test_as_of_a_date_before_the_restatement_there_is_nothing_to_list() -> None:
    concepts = {
        "Revenues": [
            fact(100 * MILLION, "2024-12-31", "2024-01-01", filed="2025-02-01", accn="a-1"),
            fact(90 * MILLION, "2024-12-31", "2024-01-01", filed="2026-02-01", accn="a-2"),
        ]
    }
    ledger = _ledger(concepts, as_of=date(2025, 12, 31))
    assert ledger.as_of == "2025-12-31" and ledger.entries == [] and ledger.periods_checked == 0


def test_microsoft_fiscal_2016_revenue_restated_for_asc_606() -> None:
    ledger = build_ledger(FactBook(load_fixture("MSFT")), ticker="MSFT")
    entry = next(
        e
        for e in ledger.entries
        if e.key == "revenue" and (e.start, e.end) == ("2015-07-01", "2016-06-30")
    )
    assert [round(v.value / MILLION) for v in entry.values] == [85_320, 91_154]
    assert entry.values[0].form == "10-K" and entry.values[1].form == "10-K"
    assert entry.values[0].filed < "2017-01-01" < entry.values[1].filed


def test_nvidia_fiscal_2024_eps_restated_for_the_split() -> None:
    ledger = build_ledger(FactBook(load_fixture("NVDA")), ticker="NVDA")
    entry = next(
        e
        for e in ledger.entries
        if e.key == "eps_diluted" and (e.start, e.end) == ("2023-01-30", "2024-01-28")
    )
    assert [v.value for v in entry.values] == [11.93, 1.19]


@pytest.mark.parametrize("ticker", ["NVDA", "AAPL", "MSFT"])
def test_the_ledger_as_of_a_date_sees_nothing_filed_later(ticker: str) -> None:
    payload = load_fixture(ticker)
    for day in (date(2015, 6, 30), date(2019, 3, 1), date(2023, 11, 1)):
        ledger = build_ledger(FactBook(payload, as_of=day), ticker=ticker)
        assert late_refs(ledger, day) == []
        assert ledger == build_ledger(FactBook(pruned(payload, day)), ticker=ticker).model_copy(
            update={"as_of": day.isoformat()}
        )


# The route and the command line


def _client(tmp_path, filings=None):
    from fastapi.testclient import TestClient

    from app.api import create_app
    from app.engines.extractive import ExtractiveAnalyst
    from app.store import Store
    from tests.fakes import FakeFilings, FakePages

    app = create_app(
        store=Store(tmp_path / "record.sqlite"),
        filings=filings or FakeFilings.nvidia(),
        analyst=ExtractiveAnalyst(),
        fetch_page=FakePages({}),
    )
    return TestClient(app)


def test_the_route_returns_the_ledger_and_honours_as_of(tmp_path) -> None:
    with _client(tmp_path) as client:
        whole = client.get("/api/companies/NVDA/restatements")
        assert whole.status_code == 200
        body = whole.json()
        assert body["ticker"] == "NVDA" and body["periods_restated"] == len(body["entries"]) > 0
        early = client.get("/api/companies/nvda/restatements?as_of=2015-01-01").json()
        assert early["as_of"] == "2015-01-01"
        assert all(v["filed"] <= "2015-01-01" for e in early["entries"] for v in e["values"])


@pytest.mark.parametrize(
    ("query", "field"),
    [
        ("as_of=2999-01-01", "as_of"),
        ("as_of=2008-12-31", "as_of"),
        # The schema refuses a malformed date before the route runs, and names the query.
        ("as_of=yesterday", "query.as_of"),
    ],
)
def test_the_route_refuses_a_date_it_cannot_use(tmp_path, query: str, field: str) -> None:
    with _client(tmp_path) as client:
        answer = client.get(f"/api/companies/NVDA/restatements?{query}")
    assert answer.status_code == 422
    assert [d["field"] for d in answer.json()["details"]] == [field]


def test_the_route_is_503_when_edgar_cannot_give_the_facts(tmp_path) -> None:
    from app.core.ports import SourceError
    from tests.fakes import FakeFilings

    filings = FakeFilings.nvidia()
    filings.facts_error = SourceError("EDGAR answered HTTP 503")
    with _client(tmp_path, filings) as client:
        answer = client.get("/api/companies/NVDA/restatements")
    assert answer.status_code == 503


def test_the_command_line_prints_and_writes_the_ledger(tmp_path, capsys) -> None:
    from app.restatements import main
    from tests.fakes import FakeFilings

    assert main(["NVDA"], filings=FakeFilings.nvidia(), out=tmp_path) == 0
    out = capsys.readouterr().out
    assert "Restatements of NVIDIA CORP (NVDA)" in out
    assert "Diluted EPS, Fiscal year ended 2024-01-28" in out
    assert len(list(tmp_path.glob("restatements-NVDA-*.json"))) == 1
    assert main(["NVDA", "--as-of", "2999-01-01"], filings=FakeFilings.nvidia(), out=tmp_path) == 2
