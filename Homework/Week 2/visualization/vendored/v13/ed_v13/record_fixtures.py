"""Record real SEC EDGAR responses as offline test fixtures (run through ``make fixtures``).

Everything is retrieved through :class:`app.sources.edgar.EdgarClient`, so the
recording obeys the same host allow-list, rate limit and size cap as a run.
Writes under ``tests/fixtures/edgar/``:

- ``company_tickers.json``: SEC's company list trimmed to a few tickers;
- ``submissions-CIK0001045810.json``: NVIDIA's filing index, each
  ``filings.recent`` column trimmed to its first entries (``filings.files`` dropped);
- the primary documents of one NVIDIA 10-Q, one NVIDIA 10-K and one Costco 10-K,
  gzip-compressed;
- the primary document of every 8-K and 8-K/A NVIDIA filed after that 10-K, as the
  recorded index lists them (``nvda-8k-<accession>.htm.gz``), and of the other
  companies' 8-Ks named in :data:`OTHER_CURRENT_REPORTS`, gzip-compressed;
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
from functools import partial
from pathlib import Path
from typing import Any

from ed_v13.core.ports import SourceError
from ed_v13.sources.edgar import SUBMISSIONS_URL, TICKERS_URL, EdgarClient, archive_url

FIXTURE_DIR = Path("tests/fixtures/edgar")
MANIFEST_NAME = "manifest.json"
KEPT_TICKERS = ("NVDA", "AAPL", "MSFT", "BRK-B", "KO")
NVIDIA_CIK = 1045810
INDEX_ROWS_KEPT = 60
# (fixture file, accession number, primary document) for each recorded filing.
DOCUMENTS = (
    ("nvda-10q-20260726.htm.gz", "0001045810-26-000075", "nvda-20260726.htm"),
    ("nvda-10q-20260426.htm.gz", "0001045810-26-000052", "nvda-20260426.htm"),
    ("nvda-10k-20260125.htm.gz", "0001045810-26-000021", "nvda-20260125.htm"),
)
# (fixture file, ticker, accession number) for filings whose primary document is looked
# up in the company's filing index. Costco's 10-K is a second full-size filing from a
# different sector, with "Item 1A—Risk Factors" headings (an em dash, not a full stop).
LOOKED_UP_DOCUMENTS = (("cost-10k-20260830.htm.gz", "COST", "0000909832-26-000093"),)

# (fixture file, CIK, accession number, primary document) of 8-Ks of other companies, each a
# layout the 8-K splitter missed in `make events-probe`: Coca-Cola's "Item 9.01(d)." and
# JPMorgan's "Item 5.02(e) Departure ...", a sub-item letter after the number.
OTHER_CURRENT_REPORTS: tuple[tuple[str, int, str, str], ...] = (
    ("ko-8k-0001628280-26-067403.htm.gz", 21344, "0001628280-26-067403", "ko-20261027.htm"),
    ("jpm-8k-0000019617-26-000052.htm.gz", 19617, "0000019617-26-000052", "jpm-20260120.htm"),
)
NVIDIA_ANNUAL_FORM = "10-K"
CURRENT_FORMS = ("8-K", "8-K/A")

URLSource = str | Callable[[], str]


def current_report_fixtures(index_path: Path) -> list[tuple[str, str]]:
    """(fixture file, URL) of every 8-K in the recorded index filed after its newest 10-K."""
    recent = json.loads(index_path.read_text())["filings"]["recent"]
    rows = list(
        zip(
            recent["form"],
            recent["filingDate"],
            recent["accessionNumber"],
            recent["primaryDocument"],
            strict=True,
        )
    )
    annual = max(filed for form, filed, _, _ in rows if form == NVIDIA_ANNUAL_FORM)
    return [
        (f"nvda-8k-{accession}.htm.gz", archive_url(NVIDIA_CIK, accession, document))
        for form, filed, accession, document in rows
        if form in CURRENT_FORMS and filed > annual
    ]


def lookup_url(client: EdgarClient, ticker: str, accession: str) -> str:
    """The primary-document URL of one of a company's current periodic filings."""
    company = client.company(ticker)
    for ref in client.periodic_filings(company, 5):
        if ref.accession == accession:
            return ref.url
    raise SourceError(f"{accession} is no longer among {ticker}'s current periodic filings")


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
    source: URLSource,
    transform: Callable[[bytes], bytes],
    refresh: bool,
) -> None:
    """Fetch ``source`` (a URL, or a function that looks one up) and save ``transform(body)``.

    The manifest entry records the original response, before ``transform``.
    """
    path = directory / name
    if path.exists() and not refresh:
        print(f"fixtures: keeping {path}")
        return
    url = source if isinstance(source, str) else source()
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
    failures = 0
    with EdgarClient.from_env() as client:
        jobs: list[tuple[str, URLSource, Callable[[bytes], bytes]]] = [
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
            *(
                (name, partial(lookup_url, client, ticker, accession), gzip_bytes)
                for name, ticker, accession in LOOKED_UP_DOCUMENTS
            ),
        ]
        index_path = FIXTURE_DIR / f"submissions-CIK{NVIDIA_CIK:010d}.json"
        if index_path.exists():
            jobs += [(name, url, gzip_bytes) for name, url in current_report_fixtures(index_path)]
        jobs += [
            (name, archive_url(cik, accession, document), gzip_bytes)
            for name, cik, accession, document in OTHER_CURRENT_REPORTS
        ]
        for name, source, transform in jobs:
            try:
                record(client, FIXTURE_DIR, manifest, name, source, transform, args.refresh)
            except (SourceError, ValueError, KeyError, TypeError) as exc:
                # One failed fixture should not stop the others; report it and fail at the end.
                print(f"fixtures: {name} failed: {exc.__class__.__name__}: {exc}")
                failures += 1
    manifest_path.write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
