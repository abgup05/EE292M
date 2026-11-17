"""The SEC EDGAR client, against a mock transport (no network)."""

from __future__ import annotations

import json
from collections.abc import Callable
from datetime import UTC
from pathlib import Path

import httpx
import pytest

from app.core.documents import FilingRef
from app.core.models import Company
from app.core.ports import SourceError, UnknownTicker
from app.sources import edgar
from app.sources.edgar import EdgarClient

TICKERS = {
    "0": {"cik_str": 1045810, "ticker": "NVDA", "title": "NVIDIA CORP"},
    "1": {"cik_str": 320193, "ticker": "AAPL", "title": "Apple Inc."},
    "2": {"cik_str": 1067983, "ticker": "BRK-B", "title": "BERKSHIRE HATHAWAY INC"},
}
NVDA = Company(cik=1045810, ticker="NVDA", name="NVIDIA CORP")
PERIODS = {"2026-02-25": "2026-01-25", "2026-08-26": "2026-07-26"}

Handler = Callable[[httpx.Request], httpx.Response]


class FakeClock:
    """A monotonic clock that only moves when the client sleeps."""

    def __init__(self) -> None:
        self.now = 1000.0
        self.sleeps: list[float] = []

    def monotonic(self) -> float:
        return self.now

    def sleep(self, seconds: float) -> None:
        self.sleeps.append(seconds)
        self.now += seconds


def make_client(handler: Handler, clock: FakeClock | None = None, **kwargs) -> EdgarClient:
    clock = clock or FakeClock()
    return EdgarClient(
        client=httpx.Client(transport=httpx.MockTransport(handler)),
        sleep=clock.sleep,
        monotonic=clock.monotonic,
        **kwargs,
    )


def json_response(payload: object) -> httpx.Response:
    return httpx.Response(200, content=json.dumps(payload).encode())


def submissions(rows: list[tuple[str, str]]) -> dict:
    """An index in EDGAR's column-oriented shape from (form, filingDate) rows."""
    recent: dict[str, list[str]] = {
        "form": [],
        "filingDate": [],
        "reportDate": [],
        "accessionNumber": [],
        "primaryDocument": [],
    }
    for number, (form, filed) in enumerate(rows):
        recent["form"].append(form)
        recent["filingDate"].append(filed)
        recent["reportDate"].append(PERIODS.get(filed, ""))
        recent["accessionNumber"].append(f"0001045810-26-{number:06d}")
        recent["primaryDocument"].append(f"doc{number}.htm")
    return {"cik": "1045810", "name": "NVIDIA CORP", "filings": {"recent": recent, "files": []}}


def index_client(rows: list[tuple[str, str]]) -> EdgarClient:
    payload = submissions(rows)

    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url == "https://data.sec.gov/submissions/CIK0001045810.json"
        return json_response(payload)

    return make_client(handler)


def tickers_client(counter: list[int] | None = None) -> EdgarClient:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url == edgar.TICKERS_URL
        if counter is not None:
            counter.append(1)
        return json_response(TICKERS)

    return make_client(handler)


# Ticker lookup


def test_company_resolves_a_ticker_case_insensitively() -> None:
    client = tickers_client()
    assert client.company("nvda") == NVDA
    assert client.company(" AAPL ").cik == 320193


@pytest.mark.parametrize("ticker", ["BRK.B", "brk-b", "BRK-B"])
def test_company_treats_dot_and_hyphen_class_suffix_alike(ticker: str) -> None:
    company = tickers_client().company(ticker)
    assert company.cik == 1067983
    assert company.ticker == "BRK-B"


def test_unknown_ticker_is_refused_with_the_contract_message() -> None:
    with pytest.raises(UnknownTicker, match="Ticker XYZ is not in SEC's company list"):
        tickers_client().company("xyz")


def test_company_list_is_cached_in_memory() -> None:
    calls: list[int] = []
    client = tickers_client(calls)
    client.company("NVDA")
    client.company("AAPL")
    assert len(calls) == 1


def test_company_list_cache_expires_after_a_day() -> None:
    calls: list[int] = []
    clock = FakeClock()

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(1)
        return json_response(TICKERS)

    client = make_client(handler, clock)
    client.company("NVDA")
    clock.now += edgar.TICKER_CACHE_SECONDS + 1
    client.company("NVDA")
    assert len(calls) == 2


def test_malformed_company_list_is_a_source_error() -> None:
    client = make_client(lambda request: json_response(["not", "a", "dict"]))
    with pytest.raises(SourceError, match="company list"):
        client.company("NVDA")


# Filing selection

ROWS = [
    ("4", "2026-11-10"),
    ("10-Q", "2026-11-01"),
    ("10-Q/A", "2026-10-15"),
    ("10-Q", "2026-08-26"),
    ("8-K", "2026-08-20"),
    ("10-Q", "2026-05-20"),
    ("10-Q", "2026-04-01"),
    ("10-K/A", "2026-03-10"),
    ("10-K", "2026-02-25"),
    ("10-Q", "2025-11-19"),
    ("10-K", "2025-02-26"),
]


def forms_and_dates(refs: list[FilingRef]) -> list[tuple[str, str]]:
    return [(ref.form, ref.filed_date) for ref in refs]


def test_limit_one_returns_only_the_latest_annual_report() -> None:
    refs = index_client(ROWS).periodic_filings(NVDA, 1)
    assert forms_and_dates(refs) == [("10-K", "2026-02-25")]


def test_limit_three_returns_the_two_newest_quarterlies_and_the_annual_report() -> None:
    refs = index_client(ROWS).periodic_filings(NVDA, 3)
    assert forms_and_dates(refs) == [
        ("10-Q", "2026-11-01"),
        ("10-Q", "2026-08-26"),
        ("10-K", "2026-02-25"),
    ]


def test_limit_five_takes_every_quarterly_after_the_annual_report_and_no_older_one() -> None:
    refs = index_client(ROWS).periodic_filings(NVDA, 5)
    assert forms_and_dates(refs) == [
        ("10-Q", "2026-11-01"),
        ("10-Q", "2026-08-26"),
        ("10-Q", "2026-05-20"),
        ("10-Q", "2026-04-01"),
        ("10-K", "2026-02-25"),
    ]


def test_amendments_are_skipped() -> None:
    rows = [("10-Q/A", "2026-09-01"), ("10-K/A", "2026-03-01"), ("10-K", "2026-02-25")]
    refs = index_client(rows).periodic_filings(NVDA, 5)
    assert forms_and_dates(refs) == [("10-K", "2026-02-25")]


def test_filing_reference_carries_the_archive_url_and_metadata() -> None:
    (ref,) = index_client(ROWS).periodic_filings(NVDA, 1)
    assert ref == FilingRef(
        cik=1045810,
        accession="0001045810-26-000008",
        form="10-K",
        period_end="2026-01-25",
        filed_date="2026-02-25",
        primary_document="doc8.htm",
        url="https://www.sec.gov/Archives/edgar/data/1045810/000104581026000008/doc8.htm",
    )


def test_no_annual_report_is_a_source_error() -> None:
    client = index_client([("10-Q", "2026-08-26"), ("20-F", "2026-03-01")])
    with pytest.raises(SourceError, match=r"No annual report \(10-K\) found for NVIDIA CORP"):
        client.periodic_filings(NVDA, 3)


def test_index_with_ragged_arrays_is_a_source_error() -> None:
    payload = submissions(ROWS)
    payload["filings"]["recent"]["form"].pop()
    client = make_client(lambda request: json_response(payload))
    with pytest.raises(SourceError, match="filing index"):
        client.periodic_filings(NVDA, 3)


# Fetching


def test_fetch_decodes_the_document_and_stamps_utc_retrieval() -> None:
    ref = FilingRef(
        cik=1045810,
        accession="0001045810-26-000075",
        form="10-Q",
        period_end="2026-07-26",
        filed_date="2026-08-26",
        primary_document="nvda-20260726.htm",
        url="https://www.sec.gov/Archives/edgar/data/1045810/000104581026000075/nvda-20260726.htm",
    )
    body = "<html>Data center — revenue</html>".encode() + b"\xff"
    client = make_client(lambda request: httpx.Response(200, content=body))
    fetched = client.fetch(ref)
    assert fetched.ref == ref
    assert fetched.html == "<html>Data center — revenue</html>�"
    assert fetched.retrieved_at.tzinfo == UTC


def test_requests_carry_the_user_agent_and_accepted_encodings() -> None:
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return json_response(TICKERS)

    make_client(handler, user_agent="Example Research admin@example.org").company("NVDA")
    assert seen[0].headers["user-agent"] == "Example Research admin@example.org"
    assert seen[0].headers["accept-encoding"] == "gzip, deflate"


def test_default_user_agent_names_the_tool_not_a_person(monkeypatch) -> None:
    monkeypatch.delenv("SEC_USER_AGENT", raising=False)
    assert EdgarClient.from_env().user_agent == edgar.DEFAULT_USER_AGENT
    assert "@" not in edgar.DEFAULT_USER_AGENT
    monkeypatch.setenv("SEC_USER_AGENT", "Example Research admin@example.org")
    assert EdgarClient.from_env().user_agent == "Example Research admin@example.org"


@pytest.mark.parametrize(
    "url",
    [
        "https://example.com/files/company_tickers.json",
        "http://www.sec.gov/files/company_tickers.json",
        "https://www.sec.gov.evil.example/x",
        "https://user@www.sec.gov/x",
        "https://www.sec.gov:8443/x",
    ],
)
def test_only_sec_hosts_over_https_are_contacted(url: str) -> None:
    calls: list[int] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(1)
        return httpx.Response(200)

    with pytest.raises(SourceError, match="not an SEC address"):
        make_client(handler).get(url)
    assert calls == []


def test_redirects_are_refused() -> None:
    calls: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(str(request.url))
        return httpx.Response(301, headers={"location": "https://www.sec.gov/elsewhere"})

    with pytest.raises(SourceError, match="redirect"):
        make_client(handler).get(edgar.TICKERS_URL)
    assert calls == [edgar.TICKERS_URL]


def test_rate_limited_request_is_retried_with_back_off_then_succeeds() -> None:
    clock = FakeClock()
    statuses = [429, 503, 200]

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(statuses.pop(0), content=b"ok")

    assert make_client(handler, clock).get(edgar.TICKERS_URL) == b"ok"
    assert statuses == []
    backoffs = [seconds for seconds in clock.sleeps if seconds >= 1]
    assert backoffs == [edgar.BACKOFF_SECONDS[0], edgar.BACKOFF_SECONDS[1]]


def test_rate_limiting_that_persists_is_a_source_error() -> None:
    calls: list[int] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(1)
        return httpx.Response(429)

    with pytest.raises(SourceError, match="HTTP 429"):
        make_client(handler).get(edgar.TICKERS_URL)
    assert len(calls) == 1 + edgar.MAX_RETRIES


def test_http_error_status_is_a_source_error_without_retry() -> None:
    calls: list[int] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(1)
        return httpx.Response(404)

    with pytest.raises(SourceError, match="HTTP 404"):
        make_client(handler).get(edgar.TICKERS_URL)
    assert len(calls) == 1


def test_oversized_body_is_cut_off(monkeypatch) -> None:
    monkeypatch.setattr(edgar, "MAX_BYTES", 1000)

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, content=iter([b"x" * 600, b"x" * 600]))

    with pytest.raises(SourceError, match="size limit"):
        make_client(handler).get(edgar.TICKERS_URL)


def test_declared_oversized_body_is_refused_before_reading(monkeypatch) -> None:
    monkeypatch.setattr(edgar, "MAX_BYTES", 1000)

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, headers={"content-length": "5000"}, content=b"x" * 5000)

    with pytest.raises(SourceError, match="size limit"):
        make_client(handler).get(edgar.TICKERS_URL)


def test_timeout_is_a_source_error() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ReadTimeout("slow", request=request)

    with pytest.raises(SourceError, match="timed out"):
        make_client(handler).get(edgar.TICKERS_URL)


def test_network_error_is_a_source_error() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("refused", request=request)

    with pytest.raises(SourceError, match="could not be reached"):
        make_client(handler).get(edgar.TICKERS_URL)


def test_bad_json_is_a_source_error() -> None:
    client = make_client(lambda request: httpx.Response(200, content=b"{not json"))
    with pytest.raises(SourceError, match="malformed"):
        client.company("NVDA")


def test_requests_are_spaced_to_at_most_seven_per_second() -> None:
    clock = FakeClock()
    starts: list[float] = []

    def handler(request: httpx.Request) -> httpx.Response:
        starts.append(clock.now)
        return httpx.Response(200, content=b"ok")

    client = make_client(handler, clock)
    for _ in range(8):
        client.get(edgar.TICKERS_URL)
    gaps = [later - earlier for earlier, later in zip(starts, starts[1:], strict=False)]
    assert all(gap >= 1 / 7 - 1e-9 for gap in gaps)
    assert starts[7] - starts[0] >= 1.0 - 1e-9


def test_spacing_does_not_wait_once_the_interval_has_passed() -> None:
    clock = FakeClock()
    client = make_client(lambda request: httpx.Response(200, content=b"ok"), clock)
    client.get(edgar.TICKERS_URL)
    clock.now += 5
    client.get(edgar.TICKERS_URL)
    assert clock.sleeps == []


def test_selection_against_the_recorded_nvidia_index() -> None:
    fixtures = Path(__file__).parent / "fixtures" / "edgar"
    if not (fixtures / "manifest.json").exists():
        pytest.skip("EDGAR fixtures not recorded; run `make fixtures`")
    files = {
        edgar.TICKERS_URL: fixtures / "company_tickers.json",
        "https://data.sec.gov/submissions/CIK0001045810.json": (
            fixtures / "submissions-CIK0001045810.json"
        ),
    }

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, content=files[str(request.url)].read_bytes())

    client = make_client(handler)
    company = client.company("nvda")
    assert company == Company(cik=1045810, ticker="NVDA", name="NVIDIA CORP")
    refs = client.periodic_filings(company, 3)
    assert [(r.form, r.filed_date, r.period_end, r.accession) for r in refs] == [
        ("10-Q", "2026-08-26", "2026-07-26", "0001045810-26-000075"),
        ("10-Q", "2026-05-20", "2026-04-26", "0001045810-26-000052"),
        ("10-K", "2026-02-25", "2026-01-25", "0001045810-26-000021"),
    ]
    assert refs[0].url == (
        "https://www.sec.gov/Archives/edgar/data/1045810/000104581026000075/nvda-20260726.htm"
    )
