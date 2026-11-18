"""Record SEC XBRL company facts as test fixtures (run through ``make fixtures-facts``).

For each company in :data:`COMPANIES` the full company-facts body is fetched
from EDGAR, trimmed to the us-gaap concepts the metrics read (every unit and
every entry of those concepts kept), and saved gzip-compressed as
``tests/fixtures/edgar/companyfacts-CIK##########.json.gz``. One entry per
recording is appended to ``tests/fixtures/edgar/facts-manifest.json`` with the
URL, the UTC retrieval time, and the SHA-256 and byte size of the original,
untrimmed body. Existing fixtures are kept unless ``--refresh`` is given.
"""

from __future__ import annotations

import argparse
import gzip
import hashlib
import json
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from ed_v8.core.facts import ALL_CONCEPTS
from ed_v8.core.ports import SourceError
from ed_v8.sources.edgar import EdgarClient
from ed_v8.sources.xbrl import company_facts_url

FIXTURE_DIR = Path("tests/fixtures/edgar")
MANIFEST = FIXTURE_DIR / "facts-manifest.json"
COMPANIES: dict[str, int] = {"NVDA": 1045810, "AAPL": 320193, "MSFT": 789019}


def fixture_path(cik: int) -> Path:
    """Where the trimmed company facts of ``cik`` are stored."""
    return FIXTURE_DIR / f"companyfacts-CIK{cik:010d}.json.gz"


def trim(payload: dict[str, Any]) -> dict[str, Any]:
    """Keep the identity fields and only the us-gaap concepts in :data:`ALL_CONCEPTS`.

    Raises SourceError when the body has no ``facts`` object, so a changed API
    is noticed when recording rather than in a test.
    """
    facts = payload.get("facts")
    if not isinstance(facts, dict):
        raise SourceError("company facts have no 'facts' object")
    gaap = facts.get("us-gaap", {})
    if not isinstance(gaap, dict):
        raise SourceError("company facts have a 'us-gaap' entry that is not an object")
    kept = {name: gaap[name] for name in sorted(gaap) if name in ALL_CONCEPTS}
    return {
        "cik": payload.get("cik"),
        "entityName": payload.get("entityName"),
        "facts": {"us-gaap": kept},
    }


def record(client: EdgarClient, ticker: str, cik: int) -> dict[str, Any]:
    """Fetch, trim and save one company; return its manifest entry."""
    url = company_facts_url(cik)
    body = client.get(url)
    retrieved_at = datetime.now(UTC)
    try:
        payload = json.loads(body)
    except (json.JSONDecodeError, UnicodeDecodeError) as exc:
        raise SourceError(f"EDGAR returned malformed company facts for {ticker}") from exc
    if not isinstance(payload, dict):
        raise SourceError(f"EDGAR returned company facts for {ticker} that are not an object")
    trimmed = json.dumps(trim(payload), separators=(",", ":")).encode()
    path = fixture_path(cik)
    path.write_bytes(gzip.compress(trimmed, mtime=0))
    return {
        "ticker": ticker,
        "cik": cik,
        "file": path.name,
        "url": url,
        "retrieved_at": retrieved_at.isoformat(),
        "original_sha256": hashlib.sha256(body).hexdigest(),
        "original_bytes": len(body),
        "trimmed_bytes": len(trimmed),
        "stored_bytes": path.stat().st_size,
        "concepts_kept": sorted(payload["facts"].get("us-gaap", {}).keys() & ALL_CONCEPTS),
    }


def load_manifest() -> list[dict[str, Any]]:
    """The manifest entries recorded so far (a JSON list), or an empty list."""
    if not MANIFEST.exists():
        return []
    entries = json.loads(MANIFEST.read_text())
    if not isinstance(entries, list):
        raise ValueError(f"{MANIFEST} must hold a JSON list of recordings")
    return entries


def main(argv: list[str] | None = None) -> int:
    """Record every company whose fixture is missing (or all of them with --refresh)."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--refresh", action="store_true", help="overwrite existing fixtures")
    args = parser.parse_args(argv)
    FIXTURE_DIR.mkdir(parents=True, exist_ok=True)
    manifest = load_manifest()
    failures = 0
    with EdgarClient.from_env() as client:
        for ticker, cik in COMPANIES.items():
            path = fixture_path(cik)
            if path.exists() and not args.refresh:
                print(f"fixtures-facts: keeping {path}")
                continue
            try:
                entry = record(client, ticker, cik)
            except SourceError as exc:
                print(f"fixtures-facts: {ticker} failed: {exc}")
                failures += 1
                continue
            manifest.append(entry)
            print(
                f"fixtures-facts: saved {path} ({entry['stored_bytes']} bytes stored, "
                f"{entry['original_bytes']} bytes original)"
            )
    MANIFEST.write_text(json.dumps(manifest, indent=2) + "\n")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
