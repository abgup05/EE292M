"""The reference pack: what the builder writes reads back as SEC's frames and 13F tables, the
pack answers first and with no request, and a date is still honoured.

The first tests build a small pack from made-up frames and a made-up 13F table, so every
expected value is written here. The last ones read the pack shipped in ``src/app/reference``
and check what any pack must give (not its numbers, which change when it is rebuilt).
"""

from __future__ import annotations

import gzip
import json
from datetime import date
from pathlib import Path
from typing import Any

import pytest

from app.build_reference import frames_body, kept_filers
from app.core.frames import parse_frame
from app.core.models import Company, ThesisRequest
from app.core.ports import SourceError
from app.core.thirteenf import Holding
from app.engines.extractive import ExtractiveAnalyst
from app.services.thesis_run import execute_run, new_run
from app.services.view_providers import run_providers
from app.sources import reference
from app.sources.frames import FramesSource
from app.sources.reference import (
    FramesPack,
    Pack,
    PackedFiling,
    PackFrames,
    PackThirteenF,
    PricesPack,
    read_frames,
)
from app.sources.thirteenf import MANAGERS, ManagerFiling, QuarterEndPrices, ThirteenFSource
from app.store import FilingCache, Store
from tests.examples_analysis import CLAIMS, MARKET_FACTS
from tests.fakes import FakePages
from tests.replay_run import recorded_filings

M = 1_000_000
BUILT = date(2026, 11, 18)


def _row(cik: int, name: str, value: float, start: str, end: str) -> dict[str, Any]:
    return {"accn": "a", "cik": cik, "entityName": name, "start": start, "end": end, "val": value}


def _frames() -> dict[tuple[str, int], Any]:
    """Three filers: Big (calendar year), June (a June year end, and one concept on other
    dates) and Small, which never reaches the floor."""
    raw = {
        ("Revenues", 2024): [
            _row(1, "Big", 900 * M, "2024-01-01", "2024-12-31"),
            _row(2, "June", 150 * M, "2023-07-01", "2024-06-30"),
            _row(3, "Small", 20 * M, "2024-01-01", "2024-12-31"),
        ],
        ("Revenues", 2025): [
            _row(1, "Big", 1000 * M, "2025-01-01", "2025-12-31"),
            _row(2, "June", 90 * M, "2024-07-01", "2025-06-30"),
            _row(3, "Small", 25 * M, "2025-01-01", "2025-12-31"),
        ],
        ("NetIncomeLoss", 2025): [
            _row(1, "Big", 100.5 * M + 0.5, "2025-01-01", "2025-12-31"),
            _row(2, "June", -5 * M, "2024-06-29", "2025-06-28"),
        ],
        ("NetIncomeLoss", 2024): [],
    }
    return {key: parse_frame({"data": rows}, key[0], f"CY{key[1]}") for key, rows in raw.items()}


def _pack(tmp_path: Path) -> FramesPack:
    frames = _frames()
    assert kept_filers(frames, 100 * M) == {1, 2}
    profiles = {1: ("Big", "3674", "Semiconductors"), 2: ("June", "5331", "Variety Stores")}
    body = frames_body(frames, profiles, [2024, 2025], BUILT, 100 * M)
    path = tmp_path / "frames.json.gz"
    path.write_bytes(gzip.compress(json.dumps(body).encode()))
    return read_frames(path)


class NoLive(FramesSource):
    """A live source that fails the test when asked for anything."""

    def __init__(self, tmp_path: Path) -> None:
        super().__init__(None, tmp_path)
        self.asked: list[str] = []

    def frame(self, concept: str, period: str, unit: str = "USD") -> dict[str, Any] | None:
        self.asked.append(f"{concept}/{period}")
        return None

    def sic_members(self, sic: str) -> list[tuple[int, str]]:
        self.asked.append(f"sic {sic}")
        return []


def test_a_frame_from_the_pack_parses_to_the_rows_sec_gave_for_the_filers_kept(
    tmp_path: Path,
) -> None:
    pack = _pack(tmp_path)
    live = NoLive(tmp_path)
    source = PackFrames(pack, live, company_cik=1)
    for (concept, year), original in _frames().items():
        payload = source.frame(concept, f"CY{year}")
        if not [r for r in original.rows if r.cik in (1, 2)]:
            assert payload is None  # SEC had no such frame, and the pack knows it
            continue
        got = parse_frame(payload, concept, f"CY{year}")
        want = [r for r in original.rows if r.cik in (1, 2)]
        assert [(r.cik, r.name, r.start, r.end, r.value) for r in got.rows] == [
            (r.cik, r.name, r.start, r.end, r.value) for r in want
        ]
    # A value on dates of its own keeps them (June's net income), and a fraction its cents.
    assert ("NetIncomeLoss", 2025, 2) in pack.odd
    assert pack.values["NetIncomeLoss"][2025][1] == 100.5 * M + 0.5
    assert source.sic_members("3674") == [(1, "Big")]
    assert live.asked == [] and source.used
    assert "in the reference pack" in source.members_wording("3674", 1)
    assert "2026-11-18" in source.members_wording("3674", 1)


def test_what_the_pack_lacks_is_asked_of_the_live_source(tmp_path: Path) -> None:
    pack = _pack(tmp_path)
    live = NoLive(tmp_path)
    source = PackFrames(pack, live, company_cik=1)
    source.frame("Revenues", "CY2026")  # a year after the pack was built
    source.frame("GrossProfit", "CY2025")  # a concept it never read
    assert live.asked == ["Revenues/CY2026", "GrossProfit/CY2025"]
    # A company the pack does not list (it never reached the floor) is read live throughout:
    # its own rows are not in the pack.
    small = PackFrames(pack, live, company_cik=3)
    small.frame("Revenues", "CY2025")
    small.sic_members("3674")
    assert live.asked[2:] == ["Revenues/CY2025", "sic 3674"] and not small.used


class Index(ThirteenFSource):
    """A live 13F source: a fixed index (or a failure), counting what it is asked."""

    def __init__(self, tmp_path: Path, newer: list[ManagerFiling] | Exception) -> None:
        super().__init__(lambda url: b"", tmp_path)
        self.newer, self.asked = newer, 0

    def filings(self, manager_cik: int, manager: str) -> list[ManagerFiling]:
        self.asked += 1
        if isinstance(self.newer, Exception):
            raise self.newer
        return [f for f in self.newer if f.manager_cik == manager_cik]

    def table(self, filing: ManagerFiling) -> str | None:
        self.asked += 1
        return None


CIK, NAME = MANAGERS[0]
Q2 = ManagerFiling(CIK, NAME, "0000000000-26-000002", date(2026, 6, 30), date(2026, 8, 10))
Q3 = ManagerFiling(CIK, NAME, "0000000000-26-000003", date(2026, 9, 30), date(2026, 11, 12))
Q4 = ManagerFiling(CIK, NAME, "0000000000-27-000001", date(2026, 12, 31), date(2027, 2, 9))
OWN = Company(cik=9, ticker="OWN", name="Own Co Inc")


def _holding(value: float) -> tuple[Holding, ...]:
    # Dollars from 2023: 1,000 shares worth ``value`` dollars.
    return (
        Holding("OWN CO INC", "COM", "123456789", value, 1000.0),
        Holding("OTHER CORP", "COM", "987654321", 5_000_000.0, 100_000.0),
    )


def _prices() -> PricesPack:
    return PricesPack(
        built=BUILT,
        filings={CIK: (PackedFiling(Q3, _holding(50_000.0)), PackedFiling(Q2, _holding(40_000.0)))},
    )


def test_a_price_is_the_newest_quarters_filed_by_the_date_and_needs_no_request(
    tmp_path: Path,
) -> None:
    live = Index(tmp_path, [])
    managers = (MANAGERS[0],)
    source = PackThirteenF(_prices(), live, BUILT)
    price = QuarterEndPrices(source, managers).price(OWN, BUILT)
    assert (price.day, price.value) == (Q3.period, pytest.approx(50.0))
    # As of a date before the third quarter's 13F was filed, the price is the second's: the
    # filing date decides, not the quarter's end.
    earlier = date(2026, 11, 1)
    price = QuarterEndPrices(PackThirteenF(_prices(), live, earlier), managers).price(OWN, earlier)
    assert (price.day, price.value) == (Q2.period, pytest.approx(40.0))
    assert price.known is not None and price.known <= earlier
    assert live.asked == 0 and source.used


def test_after_the_pack_was_built_a_newer_filing_is_looked_for_and_a_failure_is_said(
    tmp_path: Path,
) -> None:
    later = date(2027, 3, 1)
    live = Index(tmp_path, [Q4, Q3])
    source = PackThirteenF(_prices(), live, later)
    assert [f.accession for f in source.filings(CIK, NAME)] == [
        Q4.accession,
        Q3.accession,
        Q2.accession,
    ]
    assert live.asked == 1 and source.stale == ""
    down = PackThirteenF(_prices(), Index(tmp_path, SourceError("EDGAR is down")), later)
    assert [f.accession for f in down.filings(CIK, NAME)] == [Q3.accession, Q2.accession]
    assert "could not be read" in down.stale and "2026-11-18" in down.stale
    # The pack's own table is never fetched.
    assert down.holdings(Q3) is not None and down.live.asked == 1  # type: ignore[attr-defined]


# The pack shipped with the app.


def _shipped() -> Pack:
    pack = reference.load()
    assert pack is not None, "src/app/reference holds no pack: run make reference-pack"
    return pack


def test_the_shipped_pack_is_what_its_manifest_says() -> None:
    pack = _shipped()
    manifest = json.loads((reference.PACK_DIR / reference.MANIFEST_FILE).read_text())
    frames = manifest["frames"]
    assert frames["bytes"] == (reference.PACK_DIR / reference.FRAMES_FILE).stat().st_size
    assert frames["bytes"] < 6_000_000, "the frames pack is meant to stay near 5 MB"
    assert frames["filers"] == len(pack.frames.filers)
    assert frames["values"] == sum(
        len(by_cik) for years in pack.frames.values.values() for by_cik in years.values()
    )
    assert manifest["built_at"].startswith(pack.frames.built.isoformat())
    assert pack.frames.floor == frames["revenue_floor_usd"] == 100 * M
    assert {m["cik"] for m in manifest["prices"]["managers"]} == {cik for cik, _ in MANAGERS}
    assert all(len(found) >= 4 for found in pack.prices.filings.values())


def _run_from_the_pack(tmp_path: Path, as_of: date | None = None, pack: Any = "shipped") -> Any:
    """A run whose frames and 13F caches are empty and cannot fetch: a cold start offline."""
    filings = recorded_filings()
    filings.facts = json.loads(gzip.decompress(MARKET_FACTS.read_bytes()))
    providers = run_providers(
        filings,
        FramesSource(None, tmp_path / "no-frames"),
        ThirteenFSource(None, tmp_path / "no-13f"),
        pack,
    )
    request = ThesisRequest(
        ticker="NVDA", decision="Whether to buy NVIDIA now", claims=CLAIMS, as_of=as_of
    )
    return execute_run(
        new_run(request),
        Store(tmp_path / f"{as_of}-{pack is None}.sqlite"),
        filings=filings,
        analyst=ExtractiveAnalyst(),
        fetch_page=FakePages({}),
        cache=FilingCache(),
        analytics_providers=providers,
    )


def test_a_cold_run_gets_both_views_from_the_pack_and_none_without_it(tmp_path: Path) -> None:
    run = _run_from_the_pack(tmp_path)
    analysis = run.analysis
    assert analysis.providers_failed == [], analysis.provider_reasons
    by_kind: dict[str, list[Any]] = {}
    for item in analysis.analytics:
        if item.provider != "facts" and item.available:
            by_kind.setdefault(item.kind, []).append(item)
    assert {"base_rate", "peer_standing", "pe", "fcf_yield", "reverse_dcf"} <= set(by_kind)
    built = _shipped().frames.built.isoformat()
    for items in by_kind.values():
        for item in items:
            assert f"reference pack built {built}" in item.note, item.id
    assert any("in the reference pack" in item.note for item in by_kind["base_rate"])
    slowest = max(t.seconds for t in run.timings if t.stage.startswith("analytics: "))
    assert slowest < 15, "the pack is read in seconds, inside either budget"
    # The same cold run with the pack ignored has neither view.
    without = _run_from_the_pack(tmp_path, pack=None)
    got = [a for a in without.analysis.analytics if a.provider != "facts" and a.available]
    assert got == []


def test_as_of_a_date_the_pack_gives_nothing_later(tmp_path: Path) -> None:
    as_of = date(2026, 6, 15)
    run = _run_from_the_pack(tmp_path, as_of)
    market = {a.kind: a for a in run.analysis.analytics if a.provider == "market_view"}
    assert market["pe"].available, market["pe"].note
    assert market["pe"].period == "2026-03-31"  # the quarter whose 13F was filed by the date
    today = {
        a.kind: a for a in _run_from_the_pack(tmp_path).analysis.analytics if a.provider != "facts"
    }
    assert today["pe"].period > market["pe"].period
    for item in run.analysis.analytics:
        if item.provider == "facts":
            continue
        text = " ".join([item.id, item.period, item.reading, item.formula])
        text += " ".join(f"{i.id} {i.label} {i.filed}" for i in item.inputs)
        assert "CY2026" not in text and "2026-09-30" not in text and "FY2027" not in text, item.id
