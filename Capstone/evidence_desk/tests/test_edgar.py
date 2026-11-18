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


def test_the_newest_of_two_close_annual_reports_is_chosen_with_only_later_quarterlies() -> None:
    # Two 10-Ks three weeks apart (say a transition-period report), a 10-K/A newer than both,
    # and 10-Qs before, between and after them; given out of order, as nothing promises order.
    rows = [
        ("10-Q", "2026-03-10"),  # between the two 10-Ks: before the newest, so not taken
        ("10-K/A", "2026-04-02"),  # newer than both annual reports, but an amendment
        ("10-Q", "2026-08-26"),
        ("10-K", "2026-02-17"),  # the older annual report
        ("10-Q", "2026-01-12"),  # before both
        ("10-K", "2026-03-17"),  # the newest plain annual report
        ("10-Q", "2026-05-20"),
        ("10-Q", "2026-11-18"),
    ]
    refs = index_client(rows).periodic_filings(NVDA, 5)
    assert forms_and_dates(refs) == [
        ("10-Q", "2026-11-18"),
        ("10-Q", "2026-08-26"),
        ("10-Q", "2026-05-20"),
        ("10-K", "2026-03-17"),
    ]


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


def test_filings_of_form_are_the_newest_of_exactly_that_form_newest_first() -> None:
    client = index_client(ROWS)
    assert forms_and_dates(client.filings_of_form(NVDA, "10-K", 2)) == [
        ("10-K", "2026-02-25"),
        ("10-K", "2025-02-26"),
    ]
    assert forms_and_dates(index_client(ROWS).filings_of_form(NVDA, "10-Q", 2)) == [
        ("10-Q", "2026-11-01"),
        ("10-Q", "2026-08-26"),  # the 10-Q/A filed between them is skipped
    ]
    assert len(index_client(ROWS).filings_of_form(NVDA, "10-Q", 10)) == 5


def test_filings_of_form_are_read_from_an_index_given_out_of_order() -> None:
    rows = [("10-K", "2024-02-21"), ("10-K", "2026-02-25"), ("10-K/A", "2026-04-01")]
    rows += [("10-K", "2025-02-26")]
    refs = index_client(rows).filings_of_form(NVDA, "10-K", 2)
    assert forms_and_dates(refs) == [("10-K", "2026-02-25"), ("10-K", "2025-02-26")]
    assert refs[0].url.endswith("/000104581026000001/doc1.htm")


@pytest.mark.parametrize(
    "rows",
    [
        [("10-K", "2026-02-25"), ("10-K/A", "2026-04-01"), ("10-Q", "2026-08-26")],
        [("10-Q", "2026-08-26"), ("8-K", "2026-03-01")],
    ],
)
def test_fewer_than_two_filings_of_the_form_is_a_source_error(rows: list) -> None:
    with pytest.raises(SourceError, match=r"NVIDIA CORP has \d 10-K filing"):
        index_client(rows).filings_of_form(NVDA, "10-K", 2)


# Older pages of the index. A company that files a great deal (a bank issuing notes
# every day) has about a year of filings in ``filings.recent``; the rest is in further
# files named under ``filings.files``, each with the same columns at its top level.

MAIN_INDEX = "CIK0001045810.json"
BUSY = [("424B2", "2026-11-10"), ("10-Q", "2026-11-01"), ("10-K", "2026-02-25")]


def page_name(number: int) -> str:
    return f"CIK0001045810-submissions-{number:03d}.json"


def page_entry(number: int, filing_from: str, filing_to: str) -> dict:
    return {
        "name": page_name(number),
        "filingCount": 2000,
        "filingFrom": filing_from,
        "filingTo": filing_to,
    }


def older_page(number: int, rows: list[tuple[str, str]]) -> dict:
    """One older index file holding ``rows``, with accession numbers of its own."""
    page = submissions(rows)["filings"]["recent"]
    page["accessionNumber"] = [f"0001045810-25-{number:03d}{n:03d}" for n in range(len(rows))]
    page["primaryDocument"] = [f"page{number}-{n}.htm" for n in range(len(rows))]
    return page


def paged_client(
    recent: list[tuple[str, str]], files: list[dict], pages: dict[int, dict], seen: list[str]
) -> EdgarClient:
    """A client whose index names ``files``; ``seen`` collects the file names requested."""
    payload = submissions(recent)
    payload["filings"]["files"] = files
    bodies = {MAIN_INDEX: payload} | {page_name(number): page for number, page in pages.items()}

    def handler(request: httpx.Request) -> httpx.Response:
        prefix = "https://data.sec.gov/submissions/"
        assert str(request.url).startswith(prefix), request.url
        name = str(request.url).removeprefix(prefix)
        seen.append(name)
        return json_response(bodies[name])

    return make_client(handler)


def test_an_earlier_filing_of_the_form_is_found_in_an_older_page_of_the_index() -> None:
    seen: list[str] = []
    files = [
        page_entry(1, "2025-06-01", "2025-11-30"),
        page_entry(2, "2024-12-01", "2025-05-31"),
    ]
    pages = {
        1: older_page(1, [("424B2", "2025-11-30"), ("10-Q", "2025-08-05")]),
        2: older_page(2, [("424B2", "2025-05-31"), ("10-K", "2025-02-26")]),
    }
    refs = paged_client(BUSY, files, pages, seen).filings_of_form(NVDA, "10-K", 2)
    assert forms_and_dates(refs) == [("10-K", "2026-02-25"), ("10-K", "2025-02-26")]
    assert refs[1].url.endswith("/000104581025002001/page2-1.htm")
    assert seen == [MAIN_INDEX, page_name(1), page_name(2)]


def test_older_pages_are_not_read_when_the_recent_index_already_has_two() -> None:
    seen: list[str] = []
    files = [page_entry(1, "2024-01-01", "2025-01-31")]
    client = paged_client(ROWS, files, {}, seen)
    assert len(client.filings_of_form(NVDA, "10-K", 2)) == 2
    assert seen == [MAIN_INDEX]


def test_older_pages_are_read_newest_first_and_only_until_the_pair_is_complete() -> None:
    seen: list[str] = []
    files = [  # listed oldest first on purpose: the dates decide the order, not the list
        page_entry(3, "2023-01-01", "2023-12-31"),
        page_entry(2, "2024-01-01", "2024-12-31"),
        page_entry(1, "2025-01-01", "2025-11-30"),
    ]
    pages = {
        1: older_page(1, [("10-K", "2025-02-26")]),
        2: older_page(2, [("10-K", "2024-02-21")]),
        3: older_page(3, [("10-K", "2023-02-24")]),
    }
    refs = paged_client(BUSY, files, pages, seen).filings_of_form(NVDA, "10-K", 2)
    assert forms_and_dates(refs) == [("10-K", "2026-02-25"), ("10-K", "2025-02-26")]
    assert seen == [MAIN_INDEX, page_name(1)]


def test_at_most_a_fixed_number_of_older_pages_are_read_and_the_error_says_how_many() -> None:
    seen: list[str] = []
    count = edgar.MAX_OLDER_INDEX_PAGES + 2
    numbers = range(1, count + 1)  # page n holds the filings of the year 2025 - n
    files = [page_entry(n, f"{2025 - n}-01-01", f"{2025 - n}-12-31") for n in numbers]
    pages = {n: older_page(n, [("424B2", f"{2025 - n}-06-30")]) for n in numbers}
    client = paged_client(BUSY, files, pages, seen)
    message = (
        rf"NVIDIA CORP has 1 10-K filing\(s\) in EDGAR's recent index and the "
        rf"{edgar.MAX_OLDER_INDEX_PAGES} newest of its {count} older index pages"
    )
    with pytest.raises(SourceError, match=message):
        client.filings_of_form(NVDA, "10-K", 2)
    assert seen == [MAIN_INDEX, *(page_name(n) for n in range(1, edgar.MAX_OLDER_INDEX_PAGES + 1))]


@pytest.mark.parametrize(
    "name",
    [
        "CIK0000320193-submissions-001.json",  # another company's index
        "../../Archives/edgar/data/1045810/x.json",
        "https://example.com/CIK0001045810-submissions-001.json",
        "CIK0001045810-submissions-001.json?x=1",
        "",
        7,
    ],
)
def test_an_older_page_with_an_unexpected_name_is_refused_and_never_requested(
    name: object,
) -> None:
    seen: list[str] = []
    files = [{"name": name, "filingCount": 1, "filingFrom": "2025-01-01", "filingTo": "2025-12-31"}]
    with pytest.raises(SourceError, match="malformed"):
        paged_client(BUSY, files, {}, seen).filings_of_form(NVDA, "10-K", 2)
    assert seen == [MAIN_INDEX]


def test_a_malformed_older_page_is_a_source_error() -> None:
    page = older_page(1, [("10-K", "2025-02-26"), ("424B2", "2025-03-01")])
    page["form"].pop()
    files = [page_entry(1, "2025-01-01", "2025-11-30")]
    with pytest.raises(SourceError, match="malformed"):
        paged_client(BUSY, files, {1: page}, []).filings_of_form(NVDA, "10-K", 2)


def test_an_index_without_a_list_of_older_pages_is_read_as_having_none() -> None:
    payload = submissions(BUSY)
    del payload["filings"]["files"]
    client = make_client(lambda request: json_response(payload))
    with pytest.raises(SourceError, match=r"has 1 10-K filing\(s\) in EDGAR's recent index;"):
        client.filings_of_form(NVDA, "10-K", 2)


# The latest filing of a form: one is enough (a company's first annual report has no earlier one).


def test_the_latest_filing_of_a_form_is_the_newest_and_amendments_are_skipped() -> None:
    ref = index_client(ROWS).latest_of_form(NVDA, "10-K")
    assert (ref.form, ref.filed_date) == ("10-K", "2026-02-25")
    assert index_client(ROWS).latest_of_form(NVDA, "10-Q").filed_date == "2026-11-01"


def test_one_filing_of_the_form_is_enough_for_the_latest_and_no_older_page_is_read() -> None:
    seen: list[str] = []
    files = [page_entry(1, "2024-01-01", "2025-01-31")]
    ref = paged_client(BUSY, files, {}, seen).latest_of_form(NVDA, "10-K")
    assert ref.filed_date == "2026-02-25" and seen == [MAIN_INDEX]


def test_the_latest_filing_is_looked_for_in_older_pages_when_the_recent_index_has_none() -> None:
    seen: list[str] = []
    recent = [("424B2", "2026-11-10"), ("8-K", "2026-08-20")]
    files = [page_entry(1, "2025-06-01", "2025-11-30"), page_entry(2, "2024-12-01", "2025-05-31")]
    pages = {
        1: older_page(1, [("424B2", "2025-11-30")]),
        2: older_page(2, [("10-K", "2025-02-26"), ("10-K", "2024-02-21")]),
    }
    ref = paged_client(recent, files, pages, seen).latest_of_form(NVDA, "10-K")
    assert ref.filed_date == "2025-02-26"
    assert seen == [MAIN_INDEX, page_name(1), page_name(2)]


def test_no_filing_of_the_form_anywhere_is_a_source_error_that_says_so() -> None:
    client = index_client([("10-Q", "2026-08-26"), ("8-K", "2026-03-01")])
    message = r"NVIDIA CORP has no 10-K filing in EDGAR's recent index"
    with pytest.raises(SourceError, match=message):
        client.latest_of_form(NVDA, "10-K")


def test_filings_of_form_needs_a_limit_of_at_least_two() -> None:
    with pytest.raises(ValueError, match="at least 2"):
        index_client(ROWS).filings_of_form(NVDA, "10-K", 1)


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


# Current reports (8-K)


def submissions_with_items(rows: list[tuple[str, str, str]]) -> dict:
    """An index from (form, filingDate, items) rows, with EDGAR's ``items`` column."""
    payload = submissions([(form, filed) for form, filed, _ in rows])
    payload["filings"]["recent"]["items"] = [items for _, _, items in rows]
    return payload


def counting_index_client(payload: dict, seen: list[str], clock: FakeClock) -> EdgarClient:
    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(str(request.url))
        return json_response(payload)

    return make_client(handler, clock)


CURRENT_ROWS = [
    ("8-K", "2026-11-12", "5.02,9.01"),
    ("4", "2026-11-06", ""),
    ("8-K/A", "2026-09-03", "8.01"),
    ("10-Q", "2026-08-26", ""),
    ("8-K", "2026-08-26", "2.02,9.01"),
    ("6-K", "2026-04-01", ""),
    ("8-K", "2026-03-06", "5.02"),
    ("10-K", "2026-02-25", ""),
    ("8-K", "2026-02-25", "2.02"),
    ("8-K", "2026-01-10", "1.01"),
]


def test_current_reports_are_the_8ks_and_amendments_filed_after_a_date_newest_first() -> None:
    seen: list[str] = []
    client = counting_index_client(submissions_with_items(CURRENT_ROWS), seen, FakeClock())
    refs = client.current_reports(NVDA, "2026-02-25")
    assert [(r.form, r.filed_date, r.items) for r in refs] == [
        ("8-K", "2026-11-12", ("5.02", "9.01")),
        ("8-K/A", "2026-09-03", ("8.01",)),
        ("8-K", "2026-08-26", ("2.02", "9.01")),
        ("8-K", "2026-03-06", ("5.02",)),
    ]
    assert refs[0].url.endswith("/000104581026000000/doc0.htm")


def test_a_periodic_report_carries_no_items_even_when_the_index_cell_is_filled() -> None:
    payload = submissions_with_items([("10-K", "2026-02-25", "9.01")])
    client = counting_index_client(payload, [], FakeClock())
    assert client.periodic_filings(NVDA, 1)[0].items == ()


def test_an_index_without_the_items_column_lists_8ks_with_no_items() -> None:
    client = counting_index_client(submissions([("8-K", "2026-03-06")]), [], FakeClock())
    assert [r.items for r in client.current_reports(NVDA, "2026-01-01")] == [()]


def test_an_items_column_of_another_length_is_malformed() -> None:
    payload = submissions_with_items([("8-K", "2026-03-06", "5.02")])
    payload["filings"]["recent"]["items"] = []
    with pytest.raises(SourceError, match="malformed"):
        counting_index_client(payload, [], FakeClock()).current_reports(NVDA, "2026-01-01")


def test_listing_8ks_right_after_the_periodic_selection_reuses_its_index() -> None:
    seen: list[str] = []
    clock = FakeClock()
    client = counting_index_client(submissions_with_items(CURRENT_ROWS), seen, clock)
    client.periodic_filings(NVDA, 3)
    clock.now += edgar.INDEX_REUSE_SECONDS
    client.current_reports(NVDA, "2026-02-25")
    assert len(seen) == 1


def test_an_index_older_than_the_reuse_window_is_fetched_again() -> None:
    seen: list[str] = []
    clock = FakeClock()
    client = counting_index_client(submissions_with_items(CURRENT_ROWS), seen, clock)
    client.periodic_filings(NVDA, 3)
    clock.now += edgar.INDEX_REUSE_SECONDS + 1
    client.current_reports(NVDA, "2026-02-25")
    assert len(seen) == 2


def test_listing_8ks_with_no_periodic_selection_before_fetches_the_index() -> None:
    seen: list[str] = []
    client = counting_index_client(submissions_with_items(CURRENT_ROWS), seen, FakeClock())
    client.current_reports(NVDA, "2026-02-25")
    assert seen == ["https://data.sec.gov/submissions/CIK0001045810.json"]


# Company facts (XBRL)


def test_company_facts_are_read_from_data_sec_gov_for_the_padded_cik() -> None:
    seen: list[str] = []
    facts = {"cik": 1045810, "entityName": "NVIDIA CORP", "facts": {"us-gaap": {}}}

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(str(request.url))
        return json_response(facts)

    assert make_client(handler).company_facts(NVDA) == facts
    assert seen == ["https://data.sec.gov/api/xbrl/companyfacts/CIK0001045810.json"]


@pytest.mark.parametrize(
    "response",
    [
        httpx.Response(200, content=b"{not json"),
        httpx.Response(200, content=b"[1, 2]"),
        httpx.Response(404, content=b""),
    ],
)
def test_company_facts_failures_are_source_errors(response: httpx.Response) -> None:
    with pytest.raises(SourceError):
        make_client(lambda request: response).company_facts(NVDA)
