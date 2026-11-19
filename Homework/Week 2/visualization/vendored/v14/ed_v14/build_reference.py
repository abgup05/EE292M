"""Build the reference pack from SEC EDGAR (run through ``make reference-pack``).

Live, on purpose, and polite: every request goes through the app's own EDGAR client and its
rate limit, and every body fetched is kept in the disposable cache, so a run that is
interrupted picks up where it stopped. It reads

1. every frame of every concept the outside view reads (:data:`app.core.frames.FRAME_GROUPS`),
   for each calendar year from 2009 that today's date admits;
2. the industry code and name of each filer kept, from its submissions index (one request a
   filer, the slow part: kept in ``data/cache/reference/profiles.json``);
3. the newest :data:`QUARTERS` 13F-HR tables of each manager of
   :data:`app.sources.thirteenf.MANAGERS`.

and writes ``src/app/reference/frames.json.gz``, ``prices.json.gz`` and ``manifest.json``
(:mod:`app.sources.reference` reads them). A filer is kept when it ever reported annual
revenue of at least :data:`FLOOR`, which is the floor of the outside view's industry class, so
a class read from the pack has the members it has read live. Nothing here computes a result:
the pack is SEC's values, fewer of them, in fewer bytes.
"""

from __future__ import annotations

import argparse
import gzip
import hashlib
import json
import sys
from collections import Counter
from collections.abc import Sequence
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any

from ed_v14 import wiring
from ed_v14.core.facts import GROUPS
from ed_v14.core.frames import FRAME_GROUPS, ParsedFrame, admitted_years, parse_frame
from ed_v14.core.models import Company
from ed_v14.core.ports import SourceError
from ed_v14.core.thirteenf import ThirteenFError, parse_information_table
from ed_v14.services.outside_view import INDUSTRY_FLOOR
from ed_v14.sources.edgar import EdgarClient
from ed_v14.sources.frames import FramesSource
from ed_v14.sources.reference import FRAMES_FILE, MANIFEST_FILE, PACK_DIR, PRICES_FILE
from ed_v14.sources.thirteenf import MANAGERS, ThirteenFSource

FLOOR = INDUSTRY_FLOOR
QUARTERS = 8
PROFILES = "reference/profiles.json"


def concepts() -> list[str]:
    """Every us-gaap concept the outside view reads, without repeats."""
    return list(dict.fromkeys(c for group in FRAME_GROUPS for c in GROUPS[group].concepts))


def read_frames(source: FramesSource, years: Sequence[int]) -> dict[tuple[str, int], ParsedFrame]:
    """Every (concept, year) frame, parsed; a frame SEC does not have is an empty one."""
    found: dict[tuple[str, int], ParsedFrame] = {}
    wanted = [(concept, year) for concept in concepts() for year in years]
    for number, (concept, year) in enumerate(wanted, start=1):
        payload = source.frame(concept, f"CY{year}")
        found[(concept, year)] = (
            parse_frame(payload, concept, f"CY{year}")
            if payload is not None
            else ParsedFrame(concept, f"CY{year}", [])
        )
        if number % 25 == 0 or number == len(wanted):
            print(f"reference-pack: frames {number} of {len(wanted)}", flush=True)
    return found


def kept_filers(frames: dict[tuple[str, int], ParsedFrame], floor: float) -> set[int]:
    """The filers that ever reported annual revenue of at least ``floor``."""
    revenue = set(GROUPS["revenue"].concepts)
    return {
        row.cik
        for (concept, _), frame in frames.items()
        if concept in revenue
        for row in frame.rows
        if row.value >= floor
    }


def read_profiles(
    client: EdgarClient, ciks: Sequence[int], names: dict[int, str], path: Path
) -> dict[int, tuple[str, str, str]]:
    """(name, SIC, SIC title) of each filer, from its submissions index; kept in ``path`` so
    a second run asks only for the filers it does not have. A filer SEC cannot give is kept
    with no code and counted."""
    known: dict[str, list[str]] = json.loads(path.read_text()) if path.is_file() else {}
    missing = [cik for cik in ciks if str(cik) not in known]
    failed = 0
    for number, cik in enumerate(missing, start=1):
        try:
            profile = client.company_profile(Company(cik=cik, ticker="", name=names.get(cik, "")))
            known[str(cik)] = [names.get(cik, ""), profile.sic, profile.sic_description]
        except SourceError:
            known[str(cik)] = [names.get(cik, ""), "", ""]
            failed += 1
        if number % 200 == 0 or number == len(missing):
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(json.dumps(known))
            print(
                f"reference-pack: industry codes {number} of {len(missing)} ({failed} not given)",
                flush=True,
            )
    return {cik: (known[str(cik)][0], known[str(cik)][1], known[str(cik)][2]) for cik in ciks}


def _compact(day: date) -> str:
    return day.strftime("%Y%m%d")


def frames_body(
    frames: dict[tuple[str, int], ParsedFrame],
    profiles: dict[int, tuple[str, str, str]],
    years: Sequence[int],
    built: date,
    floor: float,
) -> dict[str, Any]:
    """The frames half of the pack: each kept filer's values, with its period once a year
    (the period most of its concepts share) and, apart, the periods that differ from it."""
    kept = set(profiles)
    spans: dict[int, dict[int, Counter[tuple[str, int]]]] = {year: {} for year in years}
    for (_, year), frame in frames.items():
        for row in frame.rows:
            if row.cik in kept and row.start is not None:
                span = (_compact(row.end), (row.end - row.start).days)
                spans[year].setdefault(row.cik, Counter())[span] += 1
    periods = {
        year: {cik: counts.most_common(1)[0][0] for cik, counts in sorted(by_cik.items())}
        for year, by_cik in spans.items()
    }
    body: dict[str, dict[str, dict[str, list[Any]]]] = {}
    odd: list[list[Any]] = []
    for (concept, year), frame in sorted(frames.items()):
        rows = sorted(
            (r for r in frame.rows if r.cik in kept and r.start is not None), key=lambda r: r.cik
        )
        # SEC gives one row a filer in a frame; were there two, the first stands.
        seen: dict[int, float] = {}
        for row in rows:
            if row.cik in seen:
                continue
            seen[row.cik] = int(row.value) if float(row.value).is_integer() else row.value
            span = (_compact(row.end), (row.end - row.start).days)  # type: ignore[operator]
            if span != periods[year][row.cik]:
                odd.append([concept, year, row.cik, span[0], span[1]])
        body.setdefault(concept, {})[str(year)] = {
            "ciks": list(seen),
            "values": list(seen.values()),
        }
    return {
        "built": built.isoformat(),
        "floor": floor,
        "years": list(years),
        "filers": {str(cik): [name, sic] for cik, (name, sic, _) in sorted(profiles.items())},
        "sic_names": dict(
            sorted({sic: title for _, sic, title in profiles.values() if sic}.items())
        ),
        "periods": {
            str(year): {str(cik): list(span) for cik, span in by_cik.items()}
            for year, by_cik in periods.items()
        },
        "frames": body,
        "odd": odd,
    }


def prices_body(source: ThirteenFSource, built: date, quarters: int) -> dict[str, Any]:
    """The prices half: each manager's newest ``quarters`` 13F-HR filings and their share
    positions as :func:`app.core.thirteenf.parse_information_table` reads them."""
    managers = []
    for cik, name in MANAGERS:
        packed = []
        for filing in source.filings(cik, name)[:quarters]:
            text = source.table(filing)
            if text is None:
                continue
            try:
                table = parse_information_table(text)
            except ThirteenFError as exc:
                print(f"reference-pack: {name} {filing.accession} not read: {exc}", flush=True)
                continue
            packed.append(
                {
                    "accession": filing.accession,
                    "period": filing.period.isoformat(),
                    "filed": filing.filed.isoformat(),
                    "holdings": [
                        [h.issuer, h.title, h.cusip, h.value, h.shares] for h in table.holdings
                    ],
                }
            )
            print(
                f"reference-pack: {name}, quarter ended {filing.period}: "
                f"{len(table.holdings):,} positions",
                flush=True,
            )
        managers.append({"cik": cik, "name": name, "filings": packed})
    return {"built": built.isoformat(), "managers": managers}


def _write(path: Path, payload: Any) -> tuple[int, str]:
    body = json.dumps(payload, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
    packed = gzip.compress(body, compresslevel=9, mtime=0)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(packed)
    return len(packed), hashlib.sha256(packed).hexdigest()


def build(out: Path = PACK_DIR, floor: float = FLOOR, quarters: int = QUARTERS) -> int:
    """Fetch what the pack needs, write it to ``out`` and print what was written."""
    now = datetime.now(UTC)
    years = admitted_years(None, now.date())
    client = wiring.filings_from_env()
    frames_source = FramesSource(client.get, wiring.frames_dir())
    frames = read_frames(frames_source, years)
    names = {row.cik: row.name for frame in frames.values() for row in frame.rows}
    ciks = sorted(kept_filers(frames, floor))
    print(f"reference-pack: {len(ciks):,} filers ever reported revenue of at least {floor:,.0f}")
    profiles = read_profiles(client, ciks, names, wiring.data_dir() / "cache" / PROFILES)
    frames_payload = frames_body(frames, profiles, years, now.date(), floor)
    prices_payload = prices_body(
        ThirteenFSource(client.get, wiring.thirteenf_dir()), now.date(), quarters
    )
    frames_size, frames_hash = _write(out / FRAMES_FILE, frames_payload)
    prices_size, prices_hash = _write(out / PRICES_FILE, prices_payload)
    values = sum(
        len(row["ciks"]) for by in frames_payload["frames"].values() for row in by.values()
    )
    manifest = {
        "built_at": now.isoformat(timespec="seconds"),
        "command": "make reference-pack",
        "source": "SEC EDGAR: XBRL frames, submissions indexes, Form 13F-HR information tables",
        "frames": {
            "file": FRAMES_FILE,
            "bytes": frames_size,
            "sha256": frames_hash,
            "revenue_floor_usd": floor,
            "years": [years[0], years[-1]],
            "concepts": concepts(),
            "frames_read": len(frames),
            "frames_sec_does_not_have": sum(1 for f in frames.values() if not f.rows),
            "filers": len(ciks),
            "filers_with_an_industry_code": sum(1 for _, sic, _ in profiles.values() if sic),
            "values": values,
            "values_with_a_period_of_their_own": len(frames_payload["odd"]),
        },
        "prices": {
            "file": PRICES_FILE,
            "bytes": prices_size,
            "sha256": prices_hash,
            "managers": [
                {
                    "cik": m["cik"],
                    "name": m["name"],
                    "filings": [
                        {
                            "accession": f["accession"],
                            "period": f["period"],
                            "filed": f["filed"],
                            "positions": len(f["holdings"]),
                        }
                        for f in m["filings"]
                    ],
                }
                for m in prices_payload["managers"]
            ],
        },
    }
    (out / MANIFEST_FILE).write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    print(
        f"reference-pack: wrote {out / FRAMES_FILE} ({frames_size:,} bytes: {values:,} values of "
        f"{len(ciks):,} filers) and {out / PRICES_FILE} ({prices_size:,} bytes)"
    )
    return 0


def main(argv: Sequence[str] | None = None) -> int:
    """Build the pack; ``--floor`` in USD and ``--quarters`` change what it keeps."""
    parser = argparse.ArgumentParser(description=(__doc__ or "").splitlines()[0])
    parser.add_argument("--floor", type=float, default=FLOOR)
    parser.add_argument("--quarters", type=int, default=QUARTERS)
    args = parser.parse_args(argv)
    if args.floor != INDUSTRY_FLOOR:
        print(
            f"reference-pack: the floor must be the industry class's ({INDUSTRY_FLOOR:,.0f}): "
            "a higher one would drop members of a class, a lower one adds none."
        )
        return 2
    return build(floor=args.floor, quarters=args.quarters)


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
