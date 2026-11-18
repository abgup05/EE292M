"""Probe the outside data the outside and market views read (``make market-probe``).

Live. One request to each candidate, never more than one a second, and a report of
what came back: the HTTP status, the content type, the size, the first line, and
whether the body is the shape the reader expects. It decides nothing by itself; the
findings are written down in ``docs/market-view.md`` and ``docs/outside-view.md``.
``--thirteenf`` looks only at the 13F managers the quarter-end price is read from;
``--concepts TICKER:REGEX`` lists what a company tags on its newest balance sheet.

SEC hosts are asked through the app's own EDGAR client (its User-Agent and rate
limit). Every other host is asked with a generic User-Agent that names the tool and
no person (:data:`app.sources.prices.USER_AGENT`), through the price source's
bounded, allow-listed fetch.

Writes ``results/market-probe-<UTC>.md`` and prints it. Exit code 0 always: a
candidate that fails is a finding, not an error.
"""

from __future__ import annotations

import argparse
import re
import time
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from app import wiring
from app.core.ports import SourceError
from app.core.thirteenf import parse_information_table
from app.sources.prices import PriceFetchError, fetch_public_csv
from app.sources.thirteenf import MANAGERS, ThirteenFSource

RESULTS = Path("results")
PAUSE_SECONDS = 1.0


@dataclass(frozen=True)
class Probe:
    """One candidate: a name, the URL asked, and which client asks it."""

    name: str
    url: str
    sec: bool
    expect: str


PROBES: tuple[Probe, ...] = (
    Probe(
        "SEC frames, revenue, calendar 2024",
        "https://data.sec.gov/api/xbrl/frames/us-gaap/Revenues/USD/CY2024.json",
        True,
        '{"taxonomy"',
    ),
    Probe(
        "SEC frames, cash, instant at the end of 2024 Q4",
        "https://data.sec.gov/api/xbrl/frames/us-gaap/CashAndCashEquivalentsAtCarryingValue/USD/CY2024Q4I.json",
        True,
        '{"taxonomy"',
    ),
    Probe(
        "SEC company list by SIC code (Atom), 3674",
        "https://www.sec.gov/cgi-bin/browse-edgar?action=getcompany&SIC=3674&type=10-K"
        "&dateb=&owner=include&count=40&output=atom",
        True,
        "<?xml",
    ),
    Probe(
        "Stooq daily CSV, AAPL.US",
        "https://stooq.com/q/d/l/?s=aapl.us&i=d",
        False,
        "Date,Open,High,Low,Close",
    ),
    Probe(
        "FRED graph CSV, S&P 500 (SP500)",
        "https://fred.stlouisfed.org/graph/fredgraph.csv?id=SP500",
        False,
        "observation_date,SP500",
    ),
)


def _first_line(body: bytes) -> str:
    text = body[:400].decode("utf-8", errors="replace")
    return text.splitlines()[0][:160] if text else ""


def run_probe(probe: Probe, sec_get: Callable[[str], bytes], save: Path | None = None) -> str:
    """One line of the report for ``probe``; with ``save``, the body is written there too."""
    started = time.monotonic()
    try:
        if probe.sec:
            body = sec_get(probe.url)
            kind = "(EDGAR client)"
        else:
            fetched = fetch_public_csv(probe.url)
            body, kind = fetched.body, fetched.content_type
    except (SourceError, PriceFetchError) as exc:
        return f"- **{probe.name}**: FAILED: {exc}  \n  `{probe.url}`"
    seconds = time.monotonic() - started
    if save is not None:
        save.mkdir(parents=True, exist_ok=True)
        name = "".join(c if c.isalnum() else "-" for c in probe.name.lower())[:60]
        (save / f"{name}.txt").write_bytes(body)
    first = _first_line(body)
    shape = "expected shape" if first.startswith(probe.expect) else "NOT the expected shape"
    lines = body.count(b"\n")
    return (
        f"- **{probe.name}**: {len(body):,} bytes, {lines:,} lines, {kind}, {seconds:.1f} s, "
        f"{shape}; first line `{first}`  \n  `{probe.url}`"
    )


def sic_paging(sic: str, sec_get: Callable[[str], bytes], count: int) -> list[str]:
    """How SEC pages its company list for ``sic`` at ``count`` a page: one line per page."""
    from app.sources.frames import SIC_URL, parse_sic_page

    lines: list[str] = []
    seen: set[int] = set()
    start = 0
    for _ in range(60):  # pages
        body = sec_get(SIC_URL.format(sic=sic, count=count, start=start))
        found = parse_sic_page(body.decode("latin-1"), sic)
        entries = body.count(b"<entry>")
        new = [cik for cik, _ in found if cik not in seen]
        seen.update(new)
        first = found[0][1] if found else "-"
        last = found[-1][1] if found else "-"
        lines.append(
            f"- count={count} start={start}: {entries} entries, {len(found)} of SIC {sic}, "
            f"{len(new)} new; {first} ... {last}"
        )
        if not entries:
            break
        start += entries
        time.sleep(PAUSE_SECONDS)
    lines.append(f"- {len(seen)} filers in all after {len(lines)} page(s)")
    return lines


def main(argv: Sequence[str] | None = None) -> int:
    """Run every probe (or those whose name contains ``--only``) and write the report."""
    parser = argparse.ArgumentParser(prog="market-probe")
    parser.add_argument("--only", default="", help="probe only names containing this text")
    parser.add_argument("--save", action="store_true", help="keep each body under results/")
    parser.add_argument("--sic", default="", help="only page SEC's company list for this code")
    parser.add_argument("--count", type=int, default=100, help="page size for --sic")
    parser.add_argument("--thirteenf", action="store_true", help="only the 13F managers")
    parser.add_argument(
        "--concepts", default="", help="TICKER:REGEX[:DATE], its concepts on a balance sheet"
    )
    args = parser.parse_args(argv)
    now = datetime.now(UTC)
    lines = [f"# Market and outside-data probe, {now.strftime('%Y-%m-%d %H:%M UTC')}", ""]
    with wiring.filings_from_env() as edgar:
        if args.sic:
            lines += sic_paging(args.sic, edgar.get, args.count)
        if args.thirteenf:
            lines += thirteenf_probe(edgar.get)
        if args.concepts:
            ticker, pattern, day = (*args.concepts.split(":"), "")[:3]
            lines += concepts_probe(edgar.company_facts(edgar.company(ticker)), pattern, day)
        for probe in PROBES if not (args.sic or args.thirteenf or args.concepts) else ():
            if args.only and args.only.lower() not in probe.name.lower():
                continue
            save = RESULTS / "market-probe-bodies" if args.save else None
            lines.append(run_probe(probe, edgar.get, save))
            time.sleep(PAUSE_SECONDS)
    text = "\n".join(lines) + "\n"
    RESULTS.mkdir(exist_ok=True)
    out = RESULTS / f"market-probe-{now.strftime('%Y%m%dT%H%M%SZ')}.md"
    out.write_text(text, encoding="utf-8")
    print(text)
    print(f"market-probe: written to {out}")
    return 0


def thirteenf_probe(sec_get: Callable[[str], bytes]) -> list[str]:
    """Each 13F manager the price source reads: its newest filing and what its table holds."""
    source = ThirteenFSource(sec_get, wiring.thirteenf_dir())
    lines: list[str] = []
    for cik, manager in MANAGERS:
        filings = source.filings(cik, manager)
        if not filings:
            lines.append(f"- **{manager}** (CIK {cik}): no 13F-HR in its recent index")
            continue
        newest = filings[0]
        text = source.table(newest) or ""
        table = parse_information_table(text)
        counts = sorted(table.skipped.items())
        skipped = "; ".join(f"{count:,} {reason}" for reason, count in counts)
        lines.append(
            f"- **{manager}** (CIK {cik}): {len(filings)} 13F-HR in its recent index; newest "
            f"{newest.accession} for {newest.period}, filed {newest.filed} "
            f"({(newest.filed - newest.period).days} days after the quarter's end); table "
            f"{len(text):,} characters, {len(table.holdings):,} share positions of "
            f"{len({h.cusip for h in table.holdings}):,} securities; not read: {skipped or 'none'}"
        )
    lines.append(f"- {source.requests} request(s) to SEC")
    return lines


def concepts_probe(payload: dict[str, Any], pattern: str, day: str = "") -> list[str]:
    """The us-gaap USD concepts matching ``pattern`` at ``day`` (default: the newest ``Assets``)."""
    gaap: dict[str, Any] = payload["facts"]["us-gaap"]
    newest = day or max(row["end"] for row in gaap["Assets"]["units"]["USD"])
    lines = [f"- balance sheet read: {newest}"]
    for concept in sorted(gaap):
        if not re.search(pattern, concept):
            continue
        rows = gaap[concept].get("units", {}).get("USD", [])
        at = [row for row in rows if row.get("end") == newest and "start" not in row]
        last = max((row["end"] for row in rows), default="-")
        lines.append(
            f"- {concept}: "
            + (
                f"{at[-1]['val']:,} at {newest} ({at[-1].get('form')} filed {at[-1].get('filed')})"
                if at
                else f"none (last {last})"
            )
        )
    return lines


if __name__ == "__main__":
    raise SystemExit(main())
