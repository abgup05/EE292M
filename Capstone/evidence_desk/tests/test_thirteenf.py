"""The 13F price source: reading a table, matching an issuer, the price, and no look-ahead.

Expected prices are divisions written out in the comments, on tables written here by
hand; the name pairs are the ones ``make market-check`` met on the eight probe companies
(EDGAR's name on the left, a manager's on the right).
"""

from __future__ import annotations

import gzip
import json
from datetime import date
from pathlib import Path

import pytest

from app.core.models import Company
from app.core.ports import SourceError
from app.core.thirteenf import (
    Holding,
    ThirteenFError,
    agree,
    implied_price,
    issuer_key,
    match_issuer,
    parse_information_table,
    unit_note,
    value_scale,
)
from app.sources.prices import PriceUnavailable, SuppliedPrice
from app.sources.thirteenf import ManagerFiling, QuarterEndPrices, ThirteenFSource

ACME = Company(cik=77, ticker="ACME", name="ACME WHOLESALE CORP /NEW")
FIRST, SECOND = (1, "First Fund"), (2, "Second Fund")


def entry(
    name: str,
    cusip: str,
    value: int,
    shares: int,
    *,
    kind: str = "SH",
    put_call: str = "",
    title: str = "COM",
    ns: str = "ns1:",
) -> str:
    option = f"<{ns}putCall>{put_call}</{ns}putCall>" if put_call else ""
    return (
        f"<{ns}infoTable><{ns}nameOfIssuer>{name}</{ns}nameOfIssuer>"
        f"<{ns}titleOfClass>{title}</{ns}titleOfClass><{ns}cusip>{cusip}</{ns}cusip>"
        f"<{ns}value>{value}</{ns}value><{ns}shrsOrPrnAmt><{ns}sshPrnamt>{shares}</{ns}sshPrnamt>"
        f"<{ns}sshPrnamtType>{kind}</{ns}sshPrnamtType></{ns}shrsOrPrnAmt>{option}"
        f"</{ns}infoTable>"
    )


def table(*entries: str) -> str:
    return '<?xml version="1.0"?><informationTable>' + "".join(entries) + "</informationTable>"


# Reading a table


def test_share_positions_are_read_and_options_and_principal_amounts_counted() -> None:
    text = table(
        entry("ACME WHSL CORP NEW", "000111222", 5000, 100),
        entry("ACME WHSL CORP NEW", "000111222", 900, 10, put_call="Put"),
        entry("BOND CO", "999888777", 700, 700, kind="PRN"),
        entry("AT&amp;T INC", "00206R102", 300, 10, ns=""),  # no namespace prefix, an escaped name
        entry("ZERO INC", "123456789", 0, 10),
    )
    found = parse_information_table(text)
    assert found.holdings == (
        Holding("ACME WHSL CORP NEW", "COM", "000111222", 5000.0, 100.0),
        Holding("AT&T INC", "COM", "00206R102", 300.0, 10.0),
    )
    assert found.skipped == {
        "an option (put or call)": 1,
        "not held in shares": 1,
        "no CUSIP, or a value or share count that is not positive": 1,
    }


def test_a_text_with_no_entry_is_refused() -> None:
    with pytest.raises(ThirteenFError):
        parse_information_table("<html>Request Rate Threshold Exceeded</html>")


# Matching an issuer


@pytest.mark.parametrize(
    ("edgar", "manager"),
    [
        ("NVIDIA CORP", "NVIDIA CORPORATION"),
        ("Apple Inc.", "APPLE INC"),
        ("MICROSOFT CORP", "MICROSOFT CORP"),
        ("COCA COLA CO", "COCA COLA CO"),
        ("JPMORGAN CHASE & CO", "JPMORGAN CHASE & CO."),
        ("Tesla, Inc.", "TESLA INC"),
        ("COSTCO WHOLESALE CORP /NEW", "COSTCO WHSL CORP NEW"),
        ("COSTCO WHOLESALE CORP /NEW", "COSTCO WHOLESALE CORPORATION"),
        ("AMAZON COM INC", "AMAZON COM INC"),
    ],
)
def test_the_two_spellings_of_a_company_give_one_key(edgar: str, manager: str) -> None:
    assert issuer_key(edgar) == issuer_key(manager) != ()


@pytest.mark.parametrize(
    ("edgar", "other"),
    [
        ("Apple Inc.", "APPLE HOSPITALITY REIT INC"),
        ("COCA COLA CO", "COCA COLA CONS INC"),
        ("Tesla, Inc.", "TESLA EXPLORATION LTD"),
    ],
)
def test_a_longer_name_is_another_company(edgar: str, other: str) -> None:
    assert issuer_key(edgar) != issuer_key(other)


def test_two_share_classes_under_one_name_give_no_price_and_say_so() -> None:
    rows = parse_information_table(
        table(
            entry("ALPHABET INC", "02079K305", 100, 1, title="CAP STK CL A"),
            entry("ALPHABET INC", "02079K107", 101, 1, title="CAP STK CL C"),
        )
    ).holdings
    found = match_issuer(rows, "Alphabet Inc.")
    assert isinstance(found, str)
    assert "2 securities" in found and "CL A" in found and "CL C" in found


def test_a_company_not_held_is_a_reason() -> None:
    rows = parse_information_table(table(entry("OTHER INC", "111111111", 5, 1))).holdings
    assert match_issuer(rows, "Apple Inc.") == "No position is named like 'Apple Inc.'."


# The price


def test_the_price_is_value_over_shares_summed_over_the_rows() -> None:
    rows = [Holding("X", "COM", "1", 3000.0, 20.0), Holding("X", "COM", "1", 1500.0, 10.0)]
    # (3,000 + 1,500) ÷ (20 + 10) = 150 dollars a share when value is in dollars.
    assert implied_price(rows, value_scale(rows)) == pytest.approx(150.0)


def test_a_table_of_thousands_is_told_by_its_median_and_read_as_thousands() -> None:
    # Three positions worth 150, 40 and 9 dollars a share, written in thousands of dollars:
    # value ÷ shares is 0.150, 0.040 and 0.009, median 0.040, under one dollar.
    thousands = [
        Holding("X", "COM", "1", 3000.0, 20_000.0),
        Holding("Y", "COM", "2", 400.0, 10_000.0),
        Holding("Z", "COM", "3", 90.0, 10_000.0),
    ]
    assert value_scale(thousands) == 1000.0
    # 3,000 thousand dollars ÷ 20,000 shares = 150 dollars a share.
    assert implied_price(thousands[:1], value_scale(thousands)) == pytest.approx(150.0)
    # The same three in dollars, with one penny stock (0.50) among them: median 40, dollars.
    dollars = [
        Holding("X", "COM", "1", 3_000_000.0, 20_000.0),
        Holding("Y", "COM", "2", 400_000.0, 10_000.0),
        Holding("P", "COM", "4", 5_000.0, 10_000.0),
    ]
    assert value_scale(dollars) == 1.0
    # A filer that kept thousands after the form changed is read right, and it is said.
    assert "read as thousands" in unit_note(1000.0, date(2025, 2, 10))
    assert unit_note(1000.0, date(2022, 11, 14)) == unit_note(1.0, date(2025, 2, 10)) == ""


def test_two_prices_agree_within_half_a_percent() -> None:
    assert agree(100.0, 100.5) and agree(100.0, 99.5)
    assert not agree(100.0, 100.6)


# The provider: which filing, which quarter, and nothing from after the date


def stocked(tmp_path: Path, filings: dict[int, list[tuple[str, str, str, str]]]) -> ThirteenFSource:
    """A source that reads only ``tmp_path``: per manager, (accession, period, filed, table)."""
    for cik, rows in filings.items():
        index = [[accession, period, filed] for accession, period, filed, _ in rows]
        (tmp_path / f"13f-{cik}-filings.json.gz").write_bytes(
            gzip.compress(json.dumps(index).encode())
        )
        for accession, _, _, text in rows:
            (tmp_path / f"13f-{cik}-{accession}.xml.gz").write_bytes(gzip.compress(text.encode()))
    return ThirteenFSource(None, tmp_path)


Q2 = table(entry("ACME WHSL CORP NEW", "000111222", 4000, 100))  # 40.00
Q3 = table(entry("ACME WHOLESALE CORPORATION", "000111222", 5000, 100))  # 50.00
Q3_SECOND = table(entry("ACME WHSL CORP", "000111222", 10_020, 200))  # 50.10, within 0.5%
Q3_FAR = table(entry("ACME WHSL CORP", "000111222", 2_500, 100))  # 25.00
# 50.00 written in thousands (5 thousand dollars for 100 shares), beside another position.
Q3_THOUSANDS = table(
    entry("ACME WHSL CORP", "000111222", 5, 100), entry("OTHER INC", "111111111", 8, 100)
)


def test_the_newest_filing_filed_by_the_date_gives_the_price_and_a_second_confirms(
    tmp_path: Path,
) -> None:
    source = stocked(
        tmp_path,
        {
            1: [
                ("0000000001-26-000002", "2026-09-30", "2026-11-12", Q3),
                ("0000000001-26-000001", "2026-06-30", "2026-08-11", Q2),
            ],
            2: [("0000000002-26-000009", "2026-09-30", "2026-11-16", Q3_SECOND)],
        },
    )
    price = QuarterEndPrices(source, (FIRST, SECOND)).price(ACME, date(2026, 11, 18))
    assert (price.value, price.day, price.known) == (50.0, date(2026, 9, 30), date(2026, 11, 12))
    assert price.confirmed
    assert "Confirmed within 0.5% by the 13F of Second Fund (0000000002-26-000009)" in price.note
    assert [i.value for i in price.inputs] == [5000.0, 100.0]
    assert "0000000001-26-000002" in price.source and "000111222" in price.source


def test_a_13f_filed_after_the_date_is_not_read(tmp_path: Path) -> None:
    # On 2026-11-11 the third quarter's 13F (filed 2026-11-12) is not public: the price
    # is the second quarter's, 40.00, and the unfiled quarter's 50.00 is nowhere in it.
    source = stocked(
        tmp_path,
        {
            1: [
                ("0000000001-26-000002", "2026-09-30", "2026-11-12", Q3),
                ("0000000001-26-000001", "2026-06-30", "2026-08-11", Q2),
            ]
        },
    )
    prices = QuarterEndPrices(source, (FIRST,))
    before = prices.price(ACME, date(2026, 11, 11))
    assert (before.value, before.day, before.known) == (40.0, date(2026, 6, 30), date(2026, 8, 11))
    assert not before.confirmed and "unconfirmed" in before.note
    assert prices.price(ACME, date(2026, 11, 12)).value == 50.0
    with pytest.raises(PriceUnavailable, match="no 13F-HR filed by 2026-08-10"):
        prices.price(ACME, date(2026, 8, 10))


def test_the_newest_quarter_wins_over_the_order_of_managers(tmp_path: Path) -> None:
    # The first manager has only filed for June; the second already for September.
    source = stocked(
        tmp_path,
        {
            1: [("0000000001-26-000001", "2026-06-30", "2026-08-11", Q2)],
            2: [("0000000002-26-000009", "2026-09-30", "2026-11-16", Q3_SECOND)],
        },
    )
    price = QuarterEndPrices(source, (FIRST, SECOND)).price(ACME, date(2026, 11, 18))
    assert (price.day, price.value) == (date(2026, 9, 30), pytest.approx(50.10))


def test_a_second_manager_that_differs_is_said_not_averaged(tmp_path: Path) -> None:
    source = stocked(
        tmp_path,
        {
            1: [("0000000001-26-000002", "2026-09-30", "2026-11-12", Q3)],
            2: [("0000000002-26-000009", "2026-09-30", "2026-11-16", Q3_FAR)],
        },
    )
    price = QuarterEndPrices(source, (FIRST, SECOND)).price(ACME, date(2026, 11, 18))
    assert price.value == 50.0 and not price.confirmed
    assert "Differs from Second Fund's $25.00" in price.note


def test_a_manager_that_reports_thousands_still_confirms(tmp_path: Path) -> None:
    # Met live: as of 2025-03-01 one manager's 13F gave NVIDIA at $0.13 beside $134.29.
    source = stocked(
        tmp_path,
        {
            1: [("0000000001-26-000002", "2026-09-30", "2026-11-12", Q3)],
            2: [("0000000002-26-000009", "2026-09-30", "2026-11-16", Q3_THOUSANDS)],
        },
    )
    price = QuarterEndPrices(source, (FIRST, SECOND)).price(ACME, date(2026, 11, 18))
    assert price.value == 50.0 and price.confirmed and "Differs" not in price.note
    # And when the manager in thousands is the one the price is taken from, it is 50, not 0.05.
    alone = QuarterEndPrices(source, (SECOND,)).price(ACME, date(2026, 11, 18))
    assert alone.value == pytest.approx(50.0) and "read as thousands" in alone.note


def test_no_manager_holding_the_company_is_unavailable_with_each_reason(tmp_path: Path) -> None:
    other = table(entry("OTHER INC", "111111111", 5, 1))
    source = stocked(tmp_path, {1: [("0000000001-26-000002", "2026-09-30", "2026-11-12", other)]})
    with pytest.raises(PriceUnavailable) as raised:
        QuarterEndPrices(source, (FIRST, SECOND)).price(ACME, date(2026, 11, 18))
    assert "First Fund, quarter ended 2026-09-30: No position is named like" in str(raised.value)
    assert "Second Fund: no 13F-HR filed by 2026-11-18" in str(raised.value)


# The source: three requests a manager, kept, amendments left out


def test_a_live_source_asks_for_the_index_the_folder_and_the_table_once(tmp_path: Path) -> None:
    index = {
        "filings": {
            "recent": {
                "form": ["13F-HR/A", "13F-HR", "4"],
                "accessionNumber": ["0000000001-26-000003", "0000000001-26-000002", "x"],
                "reportDate": ["2026-06-30", "2026-09-30", ""],
                "filingDate": ["2026-11-13", "2026-11-12", "2026-11-01"],
            }
        }
    }
    folder = {"directory": {"item": [{"name": "primary_doc.xml"}, {"name": "InfoTable.xml"}]}}
    asked: list[str] = []

    def get(url: str) -> bytes:
        asked.append(url)
        if "submissions" in url:
            return json.dumps(index).encode()
        return json.dumps(folder).encode() if url.endswith("index.json") else Q3.encode()

    source = ThirteenFSource(get, tmp_path, sleep=lambda _: None)
    for _ in range(2):
        filings = source.filings(1, "First Fund")
        assert filings == [
            ManagerFiling(
                1, "First Fund", "0000000001-26-000002", date(2026, 9, 30), date(2026, 11, 12)
            )
        ]
        assert source.table(filings[0]) == Q3
    assert asked == [
        "https://data.sec.gov/submissions/CIK0000000001.json",
        "https://www.sec.gov/Archives/edgar/data/1/000000000126000002/index.json",
        "https://www.sec.gov/Archives/edgar/data/1/000000000126000002/InfoTable.xml",
    ]


def test_a_folder_with_no_single_table_is_an_error(tmp_path: Path) -> None:
    folder = {"directory": {"item": [{"name": "a.xml"}, {"name": "b.xml"}]}}
    body = json.dumps(folder).encode()
    source = ThirteenFSource(lambda url: body, tmp_path, sleep=lambda _: None)
    filing = ManagerFiling(1, "F", "0000000001-26-000002", date(2026, 9, 30), date(2026, 11, 12))
    with pytest.raises(SourceError, match="2 information tables"):
        source.table(filing)


# The other provider


def test_a_supplied_price_is_refused_when_dated_after_the_date() -> None:
    supplied = SuppliedPrice(12.5, date(2026, 3, 2))
    assert supplied.price(ACME, date(2026, 3, 2)).value == 12.5
    assert "not checked against any source" in supplied.price(ACME, date(2026, 3, 2)).source
    with pytest.raises(PriceUnavailable, match="after 2026-03-01"):
        supplied.price(ACME, date(2026, 3, 1))
