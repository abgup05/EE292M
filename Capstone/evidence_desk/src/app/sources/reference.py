"""The reference pack: SEC frames and 13F tables read ahead of time and shipped with the app.

The outside view and the market view read SEC's XBRL frames (one body per concept and
year, megabytes each) and three managers' 13F information tables. Fetched during a run on a
host that keeps nothing on disk, they do not arrive inside the run's time. The pack is what
those views need, built once by ``make reference-pack`` (:mod:`app.build_reference`) and
committed as package data under ``src/app/reference/``:

- ``frames.json.gz``: for every concept the outside view reads and every calendar year from
  2009, the value of each filer that ever reported revenue of at least the pack's floor, with
  the filer's period; each such filer's name and SEC industry code (SIC) as SEC gave them on
  the day the pack was built;
- ``prices.json.gz``: for each manager of :data:`app.sources.thirteenf.MANAGERS`, its newest
  13F-HR filings with their filing dates and every share position (issuer, class, CUSIP,
  value, shares), from which a quarter-end price is derived exactly as from the filed table;
- ``manifest.json``: when it was built, from what, and the counts.

:class:`PackFrames` and :class:`PackThirteenF` answer from the pack first, at once and with
no request, and ask the live source only for what the pack does not hold: a year or a
manager's filing newer than the pack, or anything at all for a company too small to be in it.
A date is still honoured exactly: frames are admitted by period as before, and a 13F by its
filing date. What a stale pack means for a reader is in ``docs/reference-pack.md``.
"""

from __future__ import annotations

import gzip
import json
from dataclasses import dataclass, field
from datetime import date, timedelta
from functools import cache
from pathlib import Path
from typing import Any

from app.core.thirteenf import Holding, Table, parse_information_table
from app.sources.frames import FramesSource
from app.sources.thirteenf import ManagerFiling, ThirteenFSource

PACK_DIR = Path(__file__).resolve().parent.parent / "reference"
FRAMES_FILE = "frames.json.gz"
PRICES_FILE = "prices.json.gz"
MANIFEST_FILE = "manifest.json"
PACK_NOTE = (
    "Read from the reference pack built {built} (SEC's frames and 13F filings as they stood "
    "that day; a value restated or a filing made since is not in it)."
)


@dataclass(frozen=True)
class FramesPack:
    """The frames of the pack: values by concept, year and filer, and each filer's period.

    ``values[concept][year]`` maps a filer's CIK to its value; ``periods[year][cik]`` is
    the (start, end) most of that filer's concepts share for the year, and ``odd`` holds
    the periods of the values that differ from it. ``filers`` maps a CIK to (name, SIC).
    """

    built: date
    floor: float
    years: tuple[int, ...]
    filers: dict[int, tuple[str, str]]
    sic_names: dict[str, str]
    values: dict[str, dict[int, dict[int, float]]]
    periods: dict[int, dict[int, tuple[str, str]]]
    odd: dict[tuple[str, int, int], tuple[str, str]] = field(default_factory=dict)

    def has(self, concept: str, year: int) -> bool:
        """True when the pack read this frame from SEC (it may have been empty)."""
        return year in self.values.get(concept, {})

    def payload(self, concept: str, year: int) -> dict[str, Any]:
        """The frame as SEC serves it, with the pack's filers only (no accession numbers)."""
        rows = []
        for cik, value in self.values[concept][year].items():
            start, end = self.odd.get((concept, year, cik)) or self.periods[year][cik]
            rows.append(
                {
                    "accn": "",
                    "cik": cik,
                    "entityName": self.filers[cik][0] if cik in self.filers else "",
                    "start": start,
                    "end": end,
                    "val": value,
                }
            )
        return {"taxonomy": "us-gaap", "tag": concept, "ccp": f"CY{year}", "data": rows}

    def members(self, sic: str) -> list[tuple[int, str]]:
        """The pack's filers of industry code ``sic``, as (CIK, name)."""
        return sorted((cik, name) for cik, (name, code) in self.filers.items() if code == sic)


@dataclass(frozen=True)
class PackedFiling:
    """One 13F-HR of the pack: the filing, and its share positions."""

    filing: ManagerFiling
    holdings: tuple[Holding, ...]


@dataclass(frozen=True)
class PricesPack:
    """The 13F tables of the pack, by manager CIK, newest filed first."""

    built: date
    filings: dict[int, tuple[PackedFiling, ...]]


def _day(text: str) -> str:
    """``20251231`` as ``2025-12-31``."""
    return f"{text[:4]}-{text[4:6]}-{text[6:]}"


def _span(end: str, days: int) -> tuple[str, str]:
    last = date.fromisoformat(_day(end))
    return (last - timedelta(days=days)).isoformat(), last.isoformat()


def read_frames(path: Path) -> FramesPack:
    """The frames pack at ``path`` (the format :func:`app.build_reference.frames_body` writes)."""
    raw = json.loads(gzip.decompress(path.read_bytes()))
    periods = {
        int(year): {int(cik): _span(end, days) for cik, (end, days) in rows.items()}
        for year, rows in raw["periods"].items()
    }
    values = {
        concept: {
            int(year): {int(c): v for c, v in zip(row["ciks"], row["values"], strict=True)}
            for year, row in years.items()
        }
        for concept, years in raw["frames"].items()
    }
    odd = {
        (concept, int(year), int(cik)): _span(end, days)
        for concept, year, cik, end, days in raw["odd"]
    }
    return FramesPack(
        built=date.fromisoformat(raw["built"]),
        floor=float(raw["floor"]),
        years=tuple(raw["years"]),
        filers={int(cik): (name, sic) for cik, (name, sic) in raw["filers"].items()},
        sic_names=dict(raw["sic_names"]),
        values=values,
        periods=periods,
        odd=odd,
    )


def read_prices(path: Path) -> PricesPack:
    """The prices pack at ``path`` (the format :func:`app.build_reference.prices_body` writes)."""
    raw = json.loads(gzip.decompress(path.read_bytes()))
    filings: dict[int, tuple[PackedFiling, ...]] = {}
    for manager in raw["managers"]:
        packed = [
            PackedFiling(
                ManagerFiling(
                    manager["cik"],
                    manager["name"],
                    item["accession"],
                    date.fromisoformat(item["period"]),
                    date.fromisoformat(item["filed"]),
                ),
                tuple(Holding(*row) for row in item["holdings"]),
            )
            for item in manager["filings"]
        ]
        packed.sort(key=lambda p: (p.filing.filed, p.filing.period), reverse=True)
        filings[manager["cik"]] = tuple(packed)
    return PricesPack(built=date.fromisoformat(raw["built"]), filings=filings)


@dataclass(frozen=True)
class Pack:
    """Both halves of the reference pack."""

    frames: FramesPack
    prices: PricesPack


@cache
def load(directory: Path = PACK_DIR) -> Pack | None:
    """The pack shipped in ``directory``, read once; None when the app has none."""
    frames, prices = directory / FRAMES_FILE, directory / PRICES_FILE
    if not frames.is_file() or not prices.is_file():
        return None
    return Pack(read_frames(frames), read_prices(prices))


class PackFrames(FramesSource):
    """SEC frames from the pack first, then from ``live`` for what the pack does not hold.

    The pack answers for a company it lists (one that ever reported revenue of at least its
    floor): every frame it read, and the members of an industry code. For any other company
    every question goes to ``live``, because the company's own rows are not in the pack.
    ``used`` is True once the pack answered anything.
    """

    def __init__(self, pack: FramesPack, live: FramesSource, company_cik: int) -> None:
        super().__init__(None, live.cache_dir)
        self.pack, self.live = pack, live
        self.covers = company_cik in pack.filers
        self.used = False

    @property
    def offline(self) -> bool:
        """True when what the pack lacks cannot be fetched."""
        return self.live.offline

    def frame(self, concept: str, period: str, unit: str = "USD") -> dict[str, Any] | None:
        """The frame from the pack when it holds it for this company; else ``live``'s."""
        year = int(period[2:]) if period[2:].isdigit() else None
        if self.covers and unit == "USD" and year is not None and self.pack.has(concept, year):
            self.used = True
            return self.pack.payload(concept, year) if self.pack.values[concept][year] else None
        found = self.live.frame(concept, period, unit)
        self.not_read = list(self.live.not_read)
        return found

    def sic_members(self, sic: str) -> list[tuple[int, str]]:
        """The pack's filers of ``sic`` for a company it lists; else SEC's list, from ``live``."""
        if self.covers:
            self.used = True
            return self.pack.members(sic)
        found = self.live.sic_members(sic)
        self.not_read = list(self.live.not_read)
        return found

    def members_wording(self, sic: str, count: int) -> str:
        """How a class of this source's SIC members is described."""
        return (
            f"the {count:,} filers of SIC {sic} in the reference pack (every filer that ever "
            f"reported annual revenue of at least ${self.pack.floor / 1e6:,.0f}M, with the "
            f"industry code SEC gave it on {self.pack.built.isoformat()})"
        )


class PackThirteenF(ThirteenFSource):
    """13F filings from the pack first, then from ``live`` for a filing newer than the pack.

    For a date on or before the day the pack was built, the pack's list of a manager's
    filings is complete and no request is made. For a later date ``live`` is asked for the
    manager's index, so that a 13F filed since is found; when it cannot be read, the pack's
    list stands and ``stale`` says so. A table the pack holds is never fetched.
    """

    def __init__(self, pack: PricesPack, live: ThirteenFSource, day: date) -> None:
        super().__init__(None, live.cache_dir)
        self.pack, self.live, self.day = pack, live, day
        self.used = False
        self.stale = ""

    @property
    def offline(self) -> bool:
        """True when a filing newer than the pack cannot be fetched."""
        return self.live.offline

    def filings(self, manager_cik: int, manager: str) -> list[ManagerFiling]:
        """The manager's 13F-HR filings, newest filed first: the pack's, and any newer."""
        packed = [p.filing for p in self.pack.filings.get(manager_cik, ())]
        if self.day <= self.pack.built or self.live.offline:
            return packed
        try:
            newer = self.live.filings(manager_cik, manager)
        except Exception as exc:  # noqa: BLE001 - the pack's list stands; said in ``stale``
            self.stale = (
                f"{manager}'s filing index could not be read ({type(exc).__name__}), so a 13F "
                f"filed after {self.pack.built.isoformat()} is not looked for."
            )
            return packed
        known = {f.accession for f in packed}
        merged = [*packed, *(f for f in newer if f.accession not in known)]
        return sorted(merged, key=lambda f: (f.filed, f.period), reverse=True)

    def holdings(self, filing: ManagerFiling) -> Table | None:
        """The filing's share positions: the pack's, else parsed from ``live``'s table."""
        for packed in self.pack.filings.get(filing.manager_cik, ()):
            if packed.filing.accession == filing.accession:
                self.used = True
                return Table(packed.holdings, {})
        text = self.live.table(filing)
        return None if text is None else parse_information_table(text)

    def table(self, filing: ManagerFiling) -> str | None:
        """The filed table's text, for a filing the pack does not hold."""
        return self.live.table(filing)
