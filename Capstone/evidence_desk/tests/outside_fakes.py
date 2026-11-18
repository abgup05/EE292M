"""A small, made-up set of SEC frames for the outside view's tests, worked out by hand.

Revenue in USD millions, calendar years 2020 to 2022 (period ends 31 December unless
said otherwise). The expected base rates and rankings in the tests are counted from
this table by hand; the comments in each test show the counting.

    cik  name        2020   2021   2022   notes
    1    Alpha        100    160    200
    2    Beta         200    250    400
    3    Gamma         50    120    300
    4    Delta        300    290      -    no 2022 row
    5    Epsilon       90    200    210    2021 and 2022 end on 30 June
    9    Own Co      1000   1700   2000    the company the view is of
"""

from __future__ import annotations

from datetime import date
from typing import Any

from app.core.frames import Panel, parse_frame, resolve_group

M = 1e6
REVENUE: dict[int, tuple[str, dict[int, float]]] = {
    1: ("Alpha", {2020: 100, 2021: 160, 2022: 200}),
    2: ("Beta", {2020: 200, 2021: 250, 2022: 400}),
    3: ("Gamma", {2020: 50, 2021: 120, 2022: 300}),
    4: ("Delta", {2020: 300, 2021: 290}),
    5: ("Epsilon", {2020: 90, 2021: 200, 2022: 210}),
    9: ("Own Co", {2020: 1000, 2021: 1700, 2022: 2000}),
}
JUNE_ENDS = {(5, 2021), (5, 2022)}
# Operating income in 2022, USD millions: margins 10%, 25%, 10%, 20% for 1, 2, 3, 9.
OPERATING_2022 = {1: 20, 2: 100, 3: 30, 9: 400}


def row(cik: int, name: str, year: int, value: float, *, june: bool = False) -> dict[str, Any]:
    """One frame row for a calendar year (or a fiscal year ending 30 June)."""
    if june:
        start, end = date(year - 1, 7, 1), date(year, 6, 30)
    else:
        start, end = date(year, 1, 1), date(year, 12, 31)
    return {
        "accn": f"0000000000-{year % 100:02d}-{cik:06d}",
        "cik": cik,
        "entityName": name,
        "loc": "US-CA",
        "start": start.isoformat(),
        "end": end.isoformat(),
        "val": value,
    }


def frame(concept: str, period: str, rows: list[dict[str, Any]]) -> dict[str, Any]:
    """A frame body in SEC's shape."""
    return {
        "taxonomy": "us-gaap",
        "tag": concept,
        "ccp": period,
        "uom": "USD",
        "label": concept,
        "description": "",
        "pts": len(rows),
        "data": rows,
    }


def revenue_frames() -> dict[int, dict[str, Any]]:
    """The ``Revenues`` frame of each year of the table."""
    out: dict[int, dict[str, Any]] = {}
    for year in (2020, 2021, 2022):
        rows = [
            row(cik, name, year, values[year] * M, june=(cik, year) in JUNE_ENDS)
            for cik, (name, values) in REVENUE.items()
            if year in values
        ]
        out[year] = frame("Revenues", f"CY{year}", rows)
    return out


def panel() -> Panel:
    """The table as a panel: revenue for 2020 to 2022, operating income for 2022."""
    built = Panel()
    for year, body in revenue_frames().items():
        parsed = {"Revenues": parse_frame(body, "Revenues", f"CY{year}")}
        values, counts = resolve_group("revenue", year, parsed)
        built.add("revenue", year, values, counts)
    rows = [
        row(cik, REVENUE[cik][0], 2022, value * M) for cik, value in OPERATING_2022.items()
    ]
    body = frame("OperatingIncomeLoss", "CY2022", rows)
    parsed = {"OperatingIncomeLoss": parse_frame(body, "OperatingIncomeLoss", "CY2022")}
    values, counts = resolve_group("operating_income", 2022, parsed)
    built.add("operating_income", 2022, values, counts)
    return built
