"""Record the two real seed pages as test fixtures (run through ``make fixtures``).

Saves the raw HTML and a manifest with the UTC retrieval time and content
hash under ``tests/fixtures/`` so retrieval and metadata tests run offline.
Existing fixtures are kept unless ``--refresh`` is given.
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import UTC, datetime
from pathlib import Path

from app.extract import extract_document
from app.fetch import FetchError, fetch_page

FIXTURE_DIR = Path("tests/fixtures")
SEEDS = {
    "nist_ai_rmf": (
        "https://www.nist.gov/publications/artificial-intelligence-risk-management-framework-ai-rmf-10"
    ),
    "gao_24_106946": "https://www.gao.gov/products/gao-24-106946",
}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--refresh", action="store_true", help="overwrite existing fixtures")
    args = parser.parse_args(argv)
    FIXTURE_DIR.mkdir(parents=True, exist_ok=True)
    manifest_path = FIXTURE_DIR / "manifest.json"
    manifest = json.loads(manifest_path.read_text()) if manifest_path.exists() else {}
    failures = 0
    for name, url in SEEDS.items():
        html_path = FIXTURE_DIR / f"{name}.html"
        if html_path.exists() and not args.refresh:
            # Keep the recorded page but refresh the extraction fields in the manifest,
            # so an extractor change is reflected without a new fetch.
            entry = manifest.get(name, {"requested_url": url, "final_url": url})
            document = extract_document(entry["final_url"], html_path.read_text())
            entry.update(
                content_hash=document.content_hash,
                title=document.title,
                publisher=document.publisher,
                published_date=document.published_date,
            )
            manifest[name] = entry
            print(f"fixtures: keeping {html_path}")
            continue
        try:
            page = fetch_page(url)
        except FetchError as exc:
            print(f"fixtures: {url} failed: {exc}")
            failures += 1
            continue
        html_path.write_text(page.html)
        document = extract_document(page.final_url, page.html)
        manifest[name] = {
            "requested_url": url,
            "final_url": page.final_url,
            "retrieved_at": page.retrieved_at.astimezone(UTC).isoformat(),
            "content_hash": document.content_hash,
            "title": document.title,
            "publisher": document.publisher,
            "published_date": document.published_date,
            "bytes": len(page.html.encode()),
        }
        print(f"fixtures: saved {html_path} ({manifest[name]['bytes']} bytes)")
    manifest["recorded_at"] = datetime.now(UTC).isoformat()
    manifest_path.write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
