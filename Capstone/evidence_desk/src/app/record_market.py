"""Record the SEC data the offline outside and market examples read (``make fixtures-market``).

Live, on purpose, once: what ``docs/examples/market`` and the tests are built from.

- **Frames** under ``tests/fixtures/frames``: every revenue concept of
  :data:`app.core.facts.GROUPS` for CY2009 to the newest admitted year, and the other
  groups the peer standing reads for the newest three years, each **trimmed** to the
  rows of the filers that matter to the example: any filer with a revenue row of at least
  :data:`KEEP_REVENUE` in any recorded year (the size class and the ten-year spread start
  at $100B for NVIDIA), every filer SEC lists under the example's SIC code, and the
  company. A kept filer keeps all its rows in every frame, so concepts resolve as live.
- **The SIC list** of the example's code, as SEC pages it.
- **Company facts** of the example company under ``tests/fixtures/edgar``, trimmed to the
  us-gaap concepts the app's facts read (``app.core.facts.BOOK_GROUPS``) and the cover
  page's shares outstanding.

``tests/fixtures/frames/manifest.json`` says what was recorded, when, from which URL,
each body's size and SHA-256 before trimming, and the trim rule. Nothing is recorded
over an existing file unless ``--refresh`` is given. No price is recorded: no price
source found may be committed (``docs/market-view.md``).
"""

from __future__ import annotations

import argparse
import gzip
import hashlib
import json
from collections.abc import Sequence
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from app import wiring
from app.core.facts import BOOK_GROUPS, GROUPS
from app.core.frames import admitted_years, groups_for
from app.core.peers import PEER_MEASURES
from app.sources.frames import FRAME_URL, SIC_URL, FramesSource
from app.sources.xbrl import company_facts_url

FIXTURES = Path("tests/fixtures/frames")
EDGAR_FIXTURES = Path("tests/fixtures/edgar")
TICKER = "NVDA"
SIC = "3674"
KEEP_REVENUE = 50e9
FIRST_YEAR = 2009
DEI_SHARES = "EntityCommonStockSharesOutstanding"


def _write_gz(path: Path, payload: Any) -> int:
    body = json.dumps(payload, separators=(",", ":"), sort_keys=True).encode("utf-8")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(gzip.compress(body, mtime=0))
    return path.stat().st_size


def _digest(payload: Any) -> tuple[str, int]:
    body = json.dumps(payload, separators=(",", ":"), sort_keys=True).encode("utf-8")
    return hashlib.sha256(body).hexdigest(), len(body)


def trim_facts(payload: dict[str, Any]) -> dict[str, Any]:
    """The company facts with only the concepts the app reads and the cover page's shares."""
    wanted = {concept for group in BOOK_GROUPS.values() for concept in group.concepts}
    gaap = payload.get("facts", {}).get("us-gaap", {})
    dei = payload.get("facts", {}).get("dei", {})
    return {
        "cik": payload["cik"],
        "entityName": payload["entityName"],
        "facts": {
            "us-gaap": {k: v for k, v in gaap.items() if k in wanted},
            "dei": {k: v for k, v in dei.items() if k == DEI_SHARES},
        },
    }


def record(refresh: bool) -> int:
    """Record everything; print one line per file; the number of files written."""
    now = datetime.now(UTC)
    years = admitted_years(None, now.date())
    peer_years = years[-3:]
    peer_keys = ["revenue" if k == "revenue_growth" else k for k in PEER_MEASURES]
    wanted: list[tuple[str, int]] = [(c, y) for c in GROUPS["revenue"].concepts for y in years]
    wanted += [
        (c, y)
        for g in groups_for(peer_keys)
        if g != "revenue"
        for c in GROUPS[g].concepts
        for y in peer_years
    ]
    written = 0
    manifest: dict[str, Any] = {
        "recorded_at": now.isoformat(timespec="seconds"),
        "command": "make fixtures-market",
        "trim": (
            f"Each frame keeps every row of a filer with a revenue row of at least "
            f"${KEEP_REVENUE / 1e9:g}B in any recorded year (any revenue concept), of a filer "
            f"SEC lists under SIC {SIC}, and of {TICKER}; every other row is dropped."
        ),
        "cache": (
            "A body already in the disposable cache (data/cache/frames, kept from an earlier "
            "live read) is used as it is; 'requests' counts the bodies this command fetched. "
            "The cache's files carry the time each was fetched."
        ),
        "frames": [],
    }
    with wiring.filings_from_env() as edgar:
        live = FramesSource(edgar.get, wiring.frames_dir())
        company = edgar.company(TICKER)
        members = {cik for cik, _ in live.sic_members(SIC)} | {company.cik}
        bodies: dict[tuple[str, int], dict[str, Any] | None] = {
            (c, y): live.frame(c, f"CY{y}") for c, y in wanted
        }
        keep = set(members)
        for (concept, _), body in bodies.items():
            if body is None or concept not in GROUPS["revenue"].concepts:
                continue
            keep |= {
                row["cik"]
                for row in body.get("data", [])
                if isinstance(row, dict)
                and isinstance(row.get("val"), int | float)
                and row["val"] >= KEEP_REVENUE
            }
        for (concept, year), body in sorted(bodies.items(), key=lambda kv: (kv[0][1], kv[0][0])):
            path = FIXTURES / f"{concept}-USD-CY{year}.json.gz"
            entry: dict[str, Any] = {
                "file": path.name,
                "url": FRAME_URL.format(concept=concept, unit="USD", period=f"CY{year}"),
            }
            if body is None:
                entry["absent"] = True
                manifest["frames"].append(entry)
                if refresh or not path.exists():
                    path.parent.mkdir(parents=True, exist_ok=True)
                    path.write_bytes(gzip.compress(b'{"absent": true}', mtime=0))
                continue
            digest, size = _digest(body)
            trimmed = {**body, "data": [r for r in body["data"] if r.get("cik") in keep]}
            entry |= {
                "original_sha256": digest,
                "original_bytes": size,
                "rows": len(body["data"]),
                "rows_kept": len(trimmed["data"]),
            }
            manifest["frames"].append(entry)
            if refresh or not path.exists():
                written += 1
                _write_gz(path, trimmed)
        sic_rows = live.sic_members(SIC)
        sic_path = FIXTURES / f"sic-{SIC}.json.gz"
        manifest["sic"] = {
            "file": sic_path.name,
            "url": SIC_URL.format(sic=SIC, count=100, start=0) + " (and the pages after it)",
            "filers": len(sic_rows),
        }
        if refresh or not sic_path.exists():
            written += 1
            _write_gz(sic_path, sic_rows)
        facts = edgar.company_facts(company)
        digest, size = _digest(facts)
        facts_path = EDGAR_FIXTURES / f"companyfacts-market-CIK{company.cik:010d}.json.gz"
        manifest["company_facts"] = {
            "file": f"../edgar/{facts_path.name}",
            "url": company_facts_url(company.cik),
            "original_sha256": digest,
            "original_bytes": size,
            "kept": f"us-gaap concepts of app.core.facts.BOOK_GROUPS and dei:{DEI_SHARES}",
        }
        if refresh or not facts_path.exists():
            written += 1
            _write_gz(facts_path, trim_facts(facts))
        manifest["requests"] = live.requests
    (FIXTURES / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    kept = sum(f.get("rows_kept", 0) for f in manifest["frames"])
    rows = sum(f.get("rows", 0) for f in manifest["frames"])
    print(
        f"fixtures-market: {len(manifest['frames'])} frames ({rows:,} rows, {kept:,} kept), "
        f"SIC {SIC} ({len(sic_rows)} filers), company facts of {TICKER}; {written} file(s) written"
    )
    return written


def main(argv: Sequence[str] | None = None) -> int:
    """Record the fixtures; ``--refresh`` writes over the existing ones."""
    parser = argparse.ArgumentParser(prog="fixtures-market")
    parser.add_argument("--refresh", action="store_true")
    args = parser.parse_args(argv)
    record(args.refresh)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
