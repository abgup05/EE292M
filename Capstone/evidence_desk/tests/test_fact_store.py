"""The fact store: every us-gaap fact of a company, kept and given back in EDGAR's shape."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

import httpx
import pytest

from app.core.fact_models import CompanyProfile
from app.core.facts import FactBook
from app.core.metrics import build_report
from app.facts_load import load
from app.services.numbers import content_hash, load_numbers
from app.sources.edgar import EdgarClient
from app.store import FactStore
from tests.fakes import NVIDIA, FakeFilings
from tests.test_facts import companyfacts, fact, load_fixture

LOADED = datetime(2026, 11, 18, 9, 0, tzinfo=UTC)
PROFILE = CompanyProfile(
    cik=NVIDIA.cik,
    ticker="NVDA",
    name="NVIDIA CORP",
    sic="3674",
    sic_description="Semiconductors & Related Devices",
)


def _count(payload: dict) -> int:
    return sum(
        len(entries)
        for concept in payload["facts"]["us-gaap"].values()
        for entries in concept["units"].values()
    )


def test_every_fact_is_kept_and_the_book_built_from_the_store_is_the_same(
    tmp_path: Path,
) -> None:
    payload = load_fixture("NVDA")
    store = FactStore(tmp_path / "facts.sqlite")
    stored = store.save_company(PROFILE, payload, content_hash(payload), LOADED)
    assert stored.facts == _count(payload) and stored.skipped == 0
    assert stored.sic == "3674" and stored.sic_description == "Semiconductors & Related Devices"
    rebuilt = store.payload(NVIDIA.cik)
    assert rebuilt is not None and _count(rebuilt) == _count(payload)
    assert build_report(FactBook(rebuilt)) == build_report(FactBook(payload))


def test_the_same_body_again_is_not_rewritten_and_a_new_one_replaces_the_old(
    tmp_path: Path,
) -> None:
    store = FactStore(tmp_path / "facts.sqlite")
    first = companyfacts({"Revenues": [fact(1.0, "2024-12-31", "2024-01-01")]}, cik=NVIDIA.cik)
    store.save_company(PROFILE, first, content_hash(first), LOADED)
    later = datetime(2026, 11, 19, tzinfo=UTC)
    again = store.save_company(PROFILE, first, content_hash(first), later)
    assert again.loaded_at == LOADED.isoformat() and again.facts == 1
    second = companyfacts(
        {
            "Revenues": [
                fact(1.0, "2024-12-31", "2024-01-01"),
                fact(2.0, "2025-12-31", "2025-01-01", filed="2026-02-01", accn="b"),
            ]
        },
        cik=NVIDIA.cik,
    )
    replaced = store.save_company(PROFILE, second, content_hash(second), later)
    assert replaced.facts == 2 and store.fact_count(NVIDIA.cik) == 2
    assert replaced.loaded_at == later.isoformat()


def test_an_unusable_entry_is_counted_not_stored() -> None:
    store = FactStore()
    body = companyfacts(
        {
            "Revenues": [
                fact(1.0, "2024-12-31", "2024-01-01"),
                {"end": "2024-12-31", "val": "lots", "accn": "x", "form": "10-K", "filed": "x"},
                {"end": "2024-12-31", "val": 5.0, "form": "10-K", "filed": "2025-01-01"},
            ]
        },
        cik=NVIDIA.cik,
    )
    stored = store.save_company(PROFILE, body, content_hash(body), LOADED)
    assert (stored.facts, stored.skipped) == (1, 2)


def test_filings_and_companies_are_listed() -> None:
    store = FactStore()
    payload = load_fixture("NVDA")
    store.save_company(PROFILE, payload, content_hash(payload), LOADED)
    periodic = store.filings(NVIDIA.cik, ("10-K", "10-Q"))
    assert periodic[0].filed == "2009-08-20" and periodic[-1].filed == "2026-08-26"
    assert {filing.form for filing in periodic} == {"10-K", "10-Q"}
    assert [c.ticker for c in store.companies()] == ["NVDA"]
    assert store.company_by_ticker("nvda") is not None
    assert store.company(1) is None and store.payload(1) is None


def test_a_run_s_facts_are_kept_with_the_industry_code() -> None:
    store = FactStore()
    filings = FakeFilings.nvidia()
    result = load_numbers(NVIDIA, filings, facts_store=store)
    assert result.report is not None and result.payload is not None
    stored = store.company(NVIDIA.cik)
    assert stored is not None and stored.sic == "3674"
    assert stored.facts == _count(result.payload)
    assert filings.profile_calls == 1


def test_a_failed_profile_keeps_the_facts_without_a_code() -> None:
    store = FactStore()
    filings = FakeFilings.nvidia()
    from app.core.ports import SourceError

    filings.index_error = SourceError("EDGAR answered HTTP 503")
    result = load_numbers(NVIDIA, filings, facts_store=store)
    assert result.report is not None
    stored = store.company(NVIDIA.cik)
    assert stored is not None and stored.sic == ""


def test_without_a_store_nothing_is_kept_and_no_profile_is_asked() -> None:
    filings = FakeFilings.nvidia()
    load_numbers(NVIDIA, filings)
    assert filings.profile_calls == 0


def test_facts_load_prints_what_was_kept(capsys: pytest.CaptureFixture[str]) -> None:
    store = FactStore()
    failed = load(["NVDA", "ZZZZ"], FakeFilings.nvidia(), store)
    out = capsys.readouterr().out
    assert failed == 1
    assert "NVDA NVIDIA CORP (CIK 1045810, SIC 3674 Semiconductors & Related Devices)" in out
    assert "ZZZZ could not be read" in out


def test_the_edgar_client_reads_the_code_from_the_index_it_just_fetched() -> None:
    requests: list[str] = []
    index = {
        "sic": "3674",
        "sicDescription": "Semiconductors & Related Devices",
        "filings": {
            "recent": {
                "form": ["10-K"],
                "filingDate": ["2026-02-25"],
                "reportDate": ["2026-01-25"],
                "accessionNumber": ["0001045810-26-000021"],
                "primaryDocument": ["nvda-20260125.htm"],
            }
        },
    }

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(str(request.url))
        return httpx.Response(200, json=index)

    client = EdgarClient(
        client=httpx.Client(transport=httpx.MockTransport(handler)), sleep=lambda _: None
    )
    client.periodic_filings(NVIDIA, 3)
    profile = client.company_profile(NVIDIA)
    assert (profile.sic, profile.sic_description) == ("3674", "Semiconductors & Related Devices")
    assert len(requests) == 1
