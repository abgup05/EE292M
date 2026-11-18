"""The answer key of computed claims, written by a route that never calls the evaluator.

``python -m app.evaluation.claim_oracle [--write]`` reads each case of
``eval/claim-results.json`` (a claim, a company, an as-of date and the canonical test
written by hand) and computes the expected outcome straight from the recorded raw
company-facts JSON: it never builds a :class:`~app.core.facts.FactBook` and never
imports :mod:`app.core.claim_eval`. Its own rules are deliberately narrow:

- a value is the fact for exactly that period, of the first concept in a fixed
  preference that has one, from the latest filing on or before the as-of date;
- the latest quarter is the newest three-month fact of revenue (the cases are chosen
  so that it is tagged directly: this route does not difference year-to-date values);
- a quarter a year earlier ends within 10 days of a year before; the quarter before
  ends within five days before this one starts; a fiscal year is a period of 350 to
  380 days reported by a 10-K;
- a period's fiscal label ("Q2 FY2027", "FY2026") is the ``fy`` and ``fp`` of the
  first filing that reported it, which is that period's own report;
- a share of revenue is the row over the total of the newest period of a breakdown
  of the recorded filing, read with :mod:`app.core.breakdowns`.

Without ``--write`` it prints each case's expected result; with it, it writes them into
the file. ``tests/test_claim_results.py`` checks that the file is what this route
gives (so no expected value is edited by hand) and that the evaluator agrees.
"""

from __future__ import annotations

import argparse
import gzip
import json
import re
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date, timedelta
from pathlib import Path
from typing import Any

DEFAULT_KEY = Path("eval/claim-results.json")
FIXTURES = Path("tests/fixtures/edgar")
CIKS = {"NVDA": 1045810, "AAPL": 320193, "MSFT": 789019}
CONCEPTS: dict[str, tuple[str, ...]] = {
    "revenue": (
        "RevenueFromContractWithCustomerExcludingAssessedTax",
        "Revenues",
        "SalesRevenueNet",
    ),
    "gross_profit": ("GrossProfit",),
    "operating_income": ("OperatingIncomeLoss",),
    "net_income": ("NetIncomeLoss",),
    "rnd": ("ResearchAndDevelopmentExpense",),
    "eps_diluted": ("EarningsPerShareDiluted",),
    "operating_cash_flow": ("NetCashProvidedByUsedInOperatingActivities",),
    "capex": ("PaymentsToAcquirePropertyPlantAndEquipment", "PaymentsToAcquireProductiveAssets"),
    "cash": ("CashAndCashEquivalentsAtCarryingValue",),
    "inventory": ("InventoryNet",),
    "receivables": ("AccountsReceivableNetCurrent",),
}
RATIOS = {
    "gross_margin": "gross_profit",
    "operating_margin": "operating_income",
    "net_margin": "net_income",
    "rnd_ratio": "rnd",
    "fcf_margin": "free_cash_flow",
}
INSTANTS = ("cash", "inventory", "receivables")
TERM = re.compile(
    r"^(?:(?P<fn>yoy|qoq|streak)\((?P<m1>\w+)\)|cagr\((?P<m2>\w+), (?P<years>\d+)y\)|"
    r"(?P<m3>\w+))\[(?P<period>[^\]]+)\]$"
)
SHARE_TERM = re.compile(
    r'^(?:share\((?P<axis>segment|geography) "(?P<member>[^"]+)"\)|'
    r"max\(share\(customer\)\))\[filing\]$"
)
TEST = re.compile(r"^(?P<left>.+?) (?P<op>>=|<=|>|<) (?P<right>.+)$")


@dataclass(frozen=True)
class Raw:
    """One raw fact entry, as the oracle reads it."""

    concept: str
    start: date | None
    end: date
    value: float
    accession: str
    form: str
    filed: date
    fy: int | None
    fp: str


class Facts:
    """The raw facts of one company, read straight from the recorded JSON."""

    def __init__(self, payload: dict[str, Any]) -> None:
        self.entries: dict[str, list[Raw]] = {}
        for concept, body in payload["facts"]["us-gaap"].items():
            rows: list[Raw] = []
            for unit, entries in body["units"].items():
                if unit not in ("USD", "USD/shares"):
                    continue
                for e in entries:
                    rows.append(
                        Raw(
                            concept,
                            date.fromisoformat(e["start"]) if "start" in e else None,
                            date.fromisoformat(e["end"]),
                            float(e["val"]),
                            e["accn"],
                            e["form"],
                            date.fromisoformat(e["filed"]),
                            e.get("fy"),
                            e.get("fp") or "",
                        )
                    )
            self.entries[concept] = rows

    def pick(self, measure: str, start: date | None, end: date, as_of: date) -> Raw | None:
        """The fact of exactly this period, first concept that has one, latest filing by then."""
        for concept in CONCEPTS[measure]:
            found = [
                r
                for r in self.entries.get(concept, [])
                if r.start == start and r.end == end and r.filed <= as_of
            ]
            if found:
                return max(found, key=lambda r: (r.filed, r.accession, r.value))
        return None

    def periods(self, measure: str, as_of: date, days: tuple[int, int]) -> list[tuple[date, date]]:
        """Every (start, end) of a duration of the given length reported by then, newest first."""
        low, high = days
        found = {
            (r.start, r.end)
            for concept in CONCEPTS[measure]
            for r in self.entries.get(concept, [])
            if r.start is not None
            and r.filed <= as_of
            and low <= (r.end - r.start).days <= high
            and (high < 300 or r.form == "10-K")
        }
        return sorted(found, key=lambda p: p[1], reverse=True)  # type: ignore[return-value]

    def instants(self, measure: str, as_of: date) -> list[date]:
        found = {
            r.end
            for concept in CONCEPTS[measure]
            for r in self.entries.get(concept, [])
            if r.start is None and r.filed <= as_of
        }
        return sorted(found, reverse=True)

    def label(self, start: date | None, end: date, annual: bool) -> str:
        """The fiscal label of a period, from the ``fy`` and ``fp`` of the first filing that
        reported it, counted back by whole years when that filing reported it as a comparative
        (its own current period ends later)."""
        revenue = [r for concept in CONCEPTS["revenue"] for r in self.entries.get(concept, [])]
        rows = [r for r in revenue if r.start == start and r.end == end]
        first = min(rows, key=lambda r: (r.filed, r.accession))
        own_end = max(r.end for r in revenue if r.accession == first.accession)
        year = (first.fy or 0) - round((own_end - end).days / 365.25)
        if annual:
            return f"FY{year}"
        return f"{first.fp} FY{year}"

    def annual_labelled(self, year: int, as_of: date) -> tuple[date, date] | None:
        """The fiscal year a 10-K reported by ``as_of`` whose label is ``year``."""
        for period in self.periods("revenue", as_of, YEAR_DAYS):
            if self.label(*period, True) == f"FY{year}":
                return period
        return None


QUARTER_DAYS = (80, 100)
YEAR_DAYS = (350, 380)


def _year_before(periods: list[tuple[date, date]], end: date) -> tuple[date, date] | None:
    target = end - timedelta(days=365)
    near = [p for p in periods if p[1] != end and abs((p[1] - target).days) <= 10]
    return min(near, key=lambda p: abs((p[1] - target).days)) if near else None


def _quarter_before(periods: list[tuple[date, date]], start: date) -> tuple[date, date] | None:
    near = [p for p in periods if 0 < (start - p[1]).days <= 5]
    return near[0] if near else None


class Oracle:
    """Computes one case's expected result from the raw facts as of its date."""

    def __init__(self, facts: Facts, as_of: date) -> None:
        self.facts = facts
        self.as_of = as_of
        self.quarters = facts.periods("revenue", as_of, QUARTER_DAYS)
        self.years = facts.periods("revenue", as_of, YEAR_DAYS)
        self.used: list[str] = []

    def _check_latest_quarter_is_tagged(self) -> None:
        latest = self.quarters[0]
        if self.years and self.years[0][1] > latest[1]:
            raise ValueError(
                f"as of {self.as_of} the newest quarter is a fourth quarter this route "
                "cannot read: choose another date"
            )

    def period(self, token: str, measure: str) -> tuple[date | None, date, str] | None:
        """(start, end, label) of a period token."""
        if measure in INSTANTS:
            ends = self.facts.instants(measure, self.as_of)
            if token == "Q":
                return None, ends[0], ends[0].isoformat()
            if token == "Q-4":
                target = ends[0] - timedelta(days=365)
                near = [d for d in ends if abs((d - target).days) <= 10]
                return (None, near[0], near[0].isoformat()) if near else None
            raise ValueError(f"no instant token {token}")
        match = re.fullmatch(r"(Q|FY)(?:-(\d+))?|FY(\d{4})", token)
        if match is None:
            raise ValueError(f"no token {token}")
        if match[3]:
            year = int(match[3])
            found = self.facts.annual_labelled(year, self.as_of)
            return (found[0], found[1], f"FY{year}") if found else None
        back = int(match[2] or 0)
        if match[1] == "FY":
            current: tuple[date, date] | None = self.years[0]
            for _ in range(back):
                current = _year_before(self.years, current[1]) if current else None
            return (current[0], current[1], self.facts.label(*current, True)) if current else None
        self._check_latest_quarter_is_tagged()
        current = self.quarters[0]
        for _ in range(back // 4):
            current = _year_before(self.quarters, current[1]) if current else None
        for _ in range(back % 4):
            current = _quarter_before(self.quarters, current[0]) if current else None
        return (current[0], current[1], self.facts.label(*current, False)) if current else None

    def measure(self, measure: str, start: date | None, end: date) -> float | None:
        if measure in RATIOS:
            top = self.measure(RATIOS[measure], start, end)
            bottom = self.measure("revenue", start, end)
            return None if top is None or bottom is None else top / bottom * 100
        if measure == "free_cash_flow":
            ocf = self.measure("operating_cash_flow", start, end)
            capex = self.measure("capex", start, end)
            return None if ocf is None or capex is None else ocf - capex
        raw = self.facts.pick(measure, start, end, self.as_of)
        if raw is None:
            return None
        where = f"({raw.form} {raw.accession})"
        self.used.append(f"{raw.concept} {start}..{end} = {raw.value:g} {where}")
        return raw.value

    def shifted(self, token: str, years: int) -> str:
        match = re.fullmatch(r"(Q|FY)(?:-(\d+))?", token)
        assert match is not None
        per_year = 1 if match[1] == "FY" else 4
        return f"{match[1]}-{int(match[2] or 0) + per_year * years}"

    def term(self, text: str) -> tuple[float | None, str]:
        """A term's value and its bound text."""
        match = TERM.match(text)
        if match is None:
            raise ValueError(f"cannot read the term {text}")
        token = match["period"]
        if match["fn"] in ("yoy", "qoq"):
            metric = match["m1"]
            here = self.period(token, metric)
            if here is None:
                return None, text
            if match["fn"] == "yoy":
                if token.startswith("FY") and token[2:].isdigit():
                    there = self.period(f"FY{int(token[2:]) - 1}", metric)
                else:
                    there = self.period(self.shifted(token, 1), metric)
            else:
                earlier = f"Q-{int(token[2:] or 0) + 1}" if "-" in token else "Q-1"
                there = self.period(earlier, metric)
            bound = f"{match['fn']}({metric})[{here[2]}]"
            if there is None:
                return None, bound
            now = self.measure(metric, here[0], here[1])
            then = self.measure(metric, there[0], there[1])
            if now is None or then is None or then <= 0:
                return None, bound
            return (now - then) / then * 100, bound
        if match["m2"]:
            metric, years = match["m2"], int(match["years"])
            here = self.period(token, metric)
            there = self.period(self.shifted(token, years), metric)
            if here is None or there is None:
                return None, text
            now = self.measure(metric, here[0], here[1])
            then = self.measure(metric, there[0], there[1])
            bound = f"cagr({metric}, {years}y)[{here[2]}]"
            if now is None or then is None or now <= 0 or then <= 0:
                return None, bound
            return ((now / then) ** (1 / years) - 1) * 100, bound
        if match["fn"] == "streak":
            metric = match["m1"]
            assert token == "FY", "the oracle counts streaks of fiscal years only"
            values: list[float] = []
            fell = False
            for back in range(41):
                here = self.period(f"FY-{back}" if back else "FY", metric)
                value = None if here is None else self.measure(metric, here[0], here[1])
                if value is None:
                    break
                if values and values[-1] <= value:
                    fell = True
                    break
                values.append(value)
            if not fell:
                raise ValueError(f"{text}: the facts end before a fall; choose another case")
            rises = len(values) - 1
            first = self.period("FY", metric)
            assert first is not None
            return float(rises), f"streak({metric})[{first[2]}]"
        metric = match["m3"]
        here = self.period(token, metric)
        if here is None:
            return None, text
        return self.measure(metric, here[0], here[1]), f"{metric}[{here[2]}]"


def _number(text: str) -> float:
    if text.endswith("%"):
        return float(text[:-1])
    scale = {"B": 1e9, "M": 1e6}
    if text.startswith("$"):
        body = text[1:]
        if body[-1] in scale:
            return float(body[:-1]) * scale[body[-1]]
        return float(body)
    return float(text)


def _share(case: dict[str, Any], report: Any) -> dict[str, Any]:
    match = TEST.match(case["canonical"])
    assert match is not None
    share = SHARE_TERM.match(match["left"])
    assert share is not None
    right = _number(match["right"])
    if share["axis"]:
        wanted = "".join(ch for ch in share["member"].casefold() if ch.isalnum())
        for item in report.breakdowns:
            if item.id not in ("revenue_by_segment", "revenue_by_product"):
                continue
            column = item.periods[0]
            for row in item.rows:
                if "".join(ch for ch in row.label.casefold() if ch.isalnum()) != wanted:
                    continue
                part = next(
                    v
                    for v in row.values
                    if v.period_end == column.period_end and v.period_start == column.period_start
                )
                total = next(
                    v
                    for v in item.total
                    if v.period_end == column.period_end and v.period_start == column.period_start
                )
                left = part.value / total.value * 100
                read = [f"{row.label} {part.value:g} of {total.value:g}"]
                return _expected(left, match["op"], right, None, read)
        return _expected(None, match["op"], right, None, [])
    shares = []
    for item in report.breakdowns:
        if item.id != "revenue_concentration_by_customer":
            continue
        column = item.periods[0]
        for row in item.rows:
            if "·" in row.label:
                continue
            for v in row.values:
                if v.period_end == column.period_end and v.period_start == column.period_start:
                    shares.append((v.value * 100, row.label))
    if not shares:
        return _expected(None, match["op"], right, None, [])
    left, who = max(shares)
    return _expected(left, match["op"], right, None, [f"{who} {left:g}%"])


def _expected(
    left: float | None, op: str, right: float | None, bound: str | None, facts: list[str]
) -> dict[str, Any]:
    if left is None or right is None:
        outcome = "cannot_compute"
    else:
        holds = {">": left > right, ">=": left >= right, "<": left < right, "<=": left <= right}[op]
        outcome = "holds" if holds else "fails"
    return {"outcome": outcome, "bound": bound, "left": left, "right": right, "facts": facts}


def expected_for(
    case: dict[str, Any], payload: dict[str, Any], report: Any = None
) -> dict[str, Any]:
    """The expected result of one case, from the raw facts (and the recorded filing's tags)."""
    if case["canonical"].startswith(("share(", "max(share(")):
        return _share(case, report)
    match = TEST.match(case["canonical"])
    if match is None:
        raise ValueError(f"cannot read {case['canonical']}")
    oracle = Oracle(Facts(payload), date.fromisoformat(case["as_of"]))
    left, left_bound = oracle.term(match["left"])
    right_text = match["right"]
    if TERM.match(right_text):
        right, right_bound = oracle.term(right_text)
    else:
        right, right_bound = _number(right_text), right_text
    bound = f"{left_bound} {match['op']} {right_bound}"
    return _expected(left, match["op"], right, bound, oracle.used)


def load_payload(ticker: str) -> dict[str, Any]:
    """A recorded company-facts body."""
    path = FIXTURES / f"companyfacts-CIK{CIKS[ticker]:010d}.json.gz"
    return json.loads(gzip.decompress(path.read_bytes()))


def recorded_report() -> Any:
    """The breakdowns tagged in NVIDIA's recorded 10-Q for the quarter ended 2026-07-26."""
    from app.core.breakdown_models import FilingInfo
    from app.core.breakdowns import build_report
    from app.core.models import Company
    from app.sources.ixbrl import read_tagged_facts

    html = gzip.decompress((FIXTURES / "nvda-10q-20260726.htm.gz").read_bytes()).decode("utf-8")
    return build_report(
        read_tagged_facts(html),
        company=Company(cik=CIKS["NVDA"], ticker="NVDA", name="NVIDIA CORP"),
        filing=FilingInfo(
            form="10-Q",
            period_end="2026-07-26",
            filed_date="2026-08-26",
            accession="0001045810-26-000075",
            url="",
        ),
    )


def compute_all(cases: Sequence[dict[str, Any]]) -> list[dict[str, Any]]:
    """Every case's expected result, in order."""
    payloads = {ticker: load_payload(ticker) for ticker in {c["ticker"] for c in cases}}
    report = None
    results = []
    for case in cases:
        needs_report = case["canonical"].startswith(("share(", "max(share("))
        if needs_report and report is None:
            report = recorded_report()
        results.append(expected_for(case, payloads[case["ticker"]], report))
    return results


def main(argv: Sequence[str] | None = None) -> int:
    """Print every case's expected result; with ``--write``, write them into the key."""
    parser = argparse.ArgumentParser(prog="python -m app.evaluation.claim_oracle")
    parser.add_argument("--key", type=Path, default=DEFAULT_KEY)
    parser.add_argument("--write", action="store_true")
    args = parser.parse_args(argv)
    key = json.loads(args.key.read_text(encoding="utf-8"))
    results = compute_all(key["cases"])
    for case, expected in zip(key["cases"], results, strict=True):
        print(
            f"{case['id']} {case['ticker']} {case['as_of']} {case['canonical']}: "
            f"{expected['outcome']} ({expected['left']} vs {expected['right']})"
        )
        case["expected"] = expected
    if args.write:
        args.key.write_text(json.dumps(key, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
        print(f"Wrote {args.key.as_posix()}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
