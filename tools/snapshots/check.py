"""Check a deployed website: the Week 2 page, /versions and every committed snapshot.

For the site at URL, it fetches ``/``, ``/versions``, and for each version N with a directory
``SNAPSHOT_DIR/vN``: ``/vN`` (which must lead to ``/vN/``), ``/vN/`` (whose page must carry the
banner of version N), ``/vN/snapshot.js`` and the first recorded API answer the snapshot
names. It prints one line per address with its HTTP status and what was checked, and exits 1
if any check fails. Run it as ``make site-check URL=https://...``.
"""

from __future__ import annotations

import http.client
import json
import re
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

USER_AGENT = "ee292m-site-check"


def get(url: str) -> tuple[int, str, bytes]:
    """GET a URL, following redirects; return the status, the final URL and the body."""
    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            return response.status, response.url, response.read()
    except urllib.error.HTTPError as error:
        return error.code, url, b""
    except urllib.error.URLError as error:
        return 0, f"{url} ({error.reason})", b""
    except (http.client.HTTPException, OSError) as error:
        return 0, f"{url} ({type(error).__name__})", b""


def versions(snapshot_dir: Path) -> list[int]:
    """The version numbers that have a snapshot directory, in order."""
    found = [int(m.group(1)) for p in snapshot_dir.iterdir() if (m := re.fullmatch(r"v(\d+)", p.name))]
    return sorted(found)


def main(argv: list[str]) -> int:
    if len(argv) != 2:
        print("Usage: check.py URL SNAPSHOT_DIR", file=sys.stderr)
        return 2
    site, snapshot_dir = argv[0].rstrip("/"), Path(argv[1])
    failures = 0

    def report(path: str, ok: bool, status: int, what: str) -> None:
        nonlocal failures
        failures += not ok
        print(f"{'ok  ' if ok else 'FAIL'}  HTTP {status:<3}  {path:<28} {what}")

    # The app validates its workbook before it answers; give a cold start up to 30 seconds.
    for _ in range(30):
        status, _, body = get(site + "/")
        if status:
            break
        time.sleep(1)
    report("/", status == 200 and b"Who buys what?" in body, status, "the Week 2 page")
    status, _, body = get(site + "/versions")
    report("/versions", status == 200 and b"capstone-v1" in body, status, "the table of versions")
    for n in versions(snapshot_dir):
        status, final, _ = get(f"{site}/v{n}")
        report(f"/v{n}", status == 200 and final.endswith(f"/v{n}/"), status, f"leads to {final}")
        status, _, body = get(f"{site}/v{n}/")
        banner = f'data-snapshot-version="{n}"'.encode() in body
        report(f"/v{n}/", status == 200 and banner, status, "banner present" if banner else "NO BANNER")
        status, _, body = get(f"{site}/v{n}/snapshot.js")
        report(f"/v{n}/snapshot.js", status == 200 and b"window.fetch" in body, status, "the shim")
        manifest = json.loads((snapshot_dir / f"v{n}" / "snapshot.json").read_text())
        for route, file in list(manifest["routes"].items())[:1]:
            status, _, _ = get(f"{site}/v{n}/{file}")
            report(f"/v{n}/{file}", status == 200, status, f"the recorded answer to GET {route}")
    print(f"{failures} of the checks above failed." if failures else "Every check passed.")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
