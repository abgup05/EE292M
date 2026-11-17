"""Record real SEC EDGAR responses as offline test fixtures (run through ``make fixtures``).

Everything is retrieved through :class:`app.sources.edgar.EdgarClient`, so the
recording obeys the same host allow-list, rate limit and size cap as a run.
Writes under ``tests/fixtures/edgar/``:

- ``company_tickers.json``: SEC's company list trimmed to a few tickers;
- ``submissions-CIK0001045810.json``: NVIDIA's filing index, each
  ``filings.recent`` column trimmed to its first entries (``filings.files`` dropped);
- the primary documents of one NVIDIA 10-Q and one 10-K, gzip-compressed;
- ``manifest.json``: URL, UTC retrieval time, SHA-256 and byte size of each
  original response, before trimming or compression.

Existing files are kept unless ``--refresh`` is given. The older public-page
fixture (``tests/fixtures/nist_ai_rmf.html`` and its manifest) is not touched.
"""

from __future__ import annotations

import argparse
import gzip
import hashlib
import json
import sys
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from app.core.ports import SourceError
from app.sources.edgar import SUBMISSIONS_URL, TICKERS_URL, EdgarClient, archive_url

FIXTURE_DIR = Path("tests/fixtures/edgar")
MANIFEST_NAME = "manifest.json"
KEPT_TICKERS = ("NVDA", "AAPL", "MSFT", "BRK-B", "KO")
NVIDIA_CIK = 1045810
INDEX_ROWS_KEPT = 60
# (fixture file, accession number, primary document) for each recorded filing.
DOCUMENTS = (
    ("nvda-10q-20260726.htm.gz", "0001045810-26-000075", "nvda-20260726.htm"),
    ("nvda-10k-20260125.htm.gz", "0001045810-26-000021", "nvda-20260125.htm"),
)


def trim_tickers(body: bytes) -> bytes:
    """Keep only :data:`KEPT_TICKERS` from SEC's company list."""
    payload: dict[str, Any] = json.loads(body)
    kept = {key: entry for key, entry in payload.items() if entry["ticker"] in KEPT_TICKERS}
    missing = set(KEPT_TICKERS) - {entry["ticker"] for entry in kept.values()}
    if missing:
        raise SourceError(f"Company list is missing {', '.join(sorted(missing))}")
    return (json.dumps(kept, indent=1) + "\n").encode()


def trim_submissions(body: bytes) -> bytes:
    """Trim each ``filings.recent`` column to its first :data:`INDEX_ROWS_KEPT` entries.

    If the newest 10-K lies further down the index (a company with many insider
    filings), the columns are kept down to and including it, so the selection
    rule can run against the recorded index.
    """
    payload: dict[str, Any] = json.loads(body)
    recent = payload["filings"]["recent"]
    forms: list[str] = recent["form"]
    annual = forms.index("10-K") if "10-K" in forms else 0
    kept = max(INDEX_ROWS_KEPT, annual + 1)
    payload["filings"] = {"recent": {name: column[:kept] for name, column in recent.items()}}
    return (json.dumps(payload, indent=1) + "\n").encode()


def gzip_bytes(body: bytes) -> bytes:
    """Compress deterministically (no file name or time in the header)."""
    return gzip.compress(body, compresslevel=9, mtime=0)


def record(
    client: EdgarClient,
    directory: Path,
    manifest: dict[str, Any],
    name: str,
    url: str,
    transform: Callable[[bytes], bytes],
    refresh: bool,
) -> None:
    """Fetch ``url`` and save ``transform(body)`` as ``name`` with its manifest entry."""
    path = directory / name
    if path.exists() and not refresh:
        print(f"fixtures: keeping {path}")
        return
    body = client.get(url)
    retrieved_at = datetime.now(UTC)
    path.write_bytes(transform(body))
    manifest[name] = {
        "url": url,
        "retrieved_at": retrieved_at.isoformat(),
        "sha256": hashlib.sha256(body).hexdigest(),
        "bytes": len(body),
    }
    print(f"fixtures: saved {path} ({len(body)} bytes retrieved, {path.stat().st_size} stored)")


def main(argv: list[str] | None = None) -> int:
    """Record every EDGAR fixture; return 1 if any could not be recorded."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--refresh", action="store_true", help="overwrite existing fixtures")
    args = parser.parse_args(argv)
    FIXTURE_DIR.mkdir(parents=True, exist_ok=True)
    manifest_path = FIXTURE_DIR / MANIFEST_NAME
    manifest: dict[str, Any] = (
        json.loads(manifest_path.read_text()) if manifest_path.exists() else {}
    )
    jobs: list[tuple[str, str, Callable[[bytes], bytes]]] = [
        ("company_tickers.json", TICKERS_URL, trim_tickers),
        (
            f"submissions-CIK{NVIDIA_CIK:010d}.json",
            SUBMISSIONS_URL.format(cik=NVIDIA_CIK),
            trim_submissions,
        ),
        *(
            (name, archive_url(NVIDIA_CIK, accession, document), gzip_bytes)
            for name, accession, document in DOCUMENTS
        ),
    ]
    failures = 0
    with EdgarClient.from_env() as client:
        for name, url, transform in jobs:
            try:
                record(client, FIXTURE_DIR, manifest, name, url, transform, args.refresh)
            except (SourceError, ValueError, KeyError, TypeError) as exc:
                # One failed fixture should not stop the others; report it and fail at the end.
                print(f"fixtures: {name} failed: {exc.__class__.__name__}: {exc}")
                failures += 1
    manifest_path.write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
