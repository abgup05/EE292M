"""Check a deployed website: the Week 2 page, /versions and every capstone version.

For the site at URL it fetches ``/``, ``/versions`` and ``/live/status?imports=true`` (which
makes the server build every live version, and reports booleans and counts only), then for
each version N that has a directory under SNAPSHOT_DIR or VENDOR_DIR: ``/vN`` (which must lead
to ``/vN/``) and ``/vN/``, and says whether the page is the version running **live** (its own
page with the live banner) or its **recorded** snapshot. A live version must also answer its
shim and the first address its page reads; a recorded one its ``snapshot.js`` and its first
recorded answer. A version that is vendored but served recorded is reported, with the reason
the server gives, and fails the check unless ``--allow-recorded`` is given.

It prints one line per address and exits 1 if any check fails. It starts no run and sends
nothing but GET requests. Run it as ``make site-check URL=https://...``.
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


def versions(*directories: Path) -> list[int]:
    """The version numbers that have a directory under any of ``directories``, in order."""
    found = {
        int(m.group(1))
        for directory in directories
        if directory.is_dir()
        for p in directory.iterdir()
        if (m := re.fullmatch(r"v(\d+)", p.name))
    }
    return sorted(found)


def main(argv: list[str]) -> int:
    allow_recorded = "--allow-recorded" in argv
    argv = [a for a in argv if a != "--allow-recorded"]
    if len(argv) not in (2, 3):
        print("Usage: check.py [--allow-recorded] URL SNAPSHOT_DIR [VENDOR_DIR]", file=sys.stderr)
        return 2
    site, snapshot_dir = argv[0].rstrip("/"), Path(argv[1])
    vendor_dir = Path(argv[2]) if len(argv) == 3 else snapshot_dir.parent / "vendored"
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

    status, _, body = get(site + "/live/status?imports=true")
    try:
        live = json.loads(body) if status == 200 else {}
    except ValueError:
        live = {}
    states: dict[str, dict] = live.get("versions", {}) if isinstance(live, dict) else {}
    if live:
        what = (
            f"key_present {live.get('key_present')}, sec_user_agent_present "
            f"{live.get('sec_user_agent_present')}, model_engine {live.get('model_engine')}, "
            f"caps_invalid {live.get('caps_invalid')}, model runs today "
            f"{live.get('counts', {}).get('model_runs_today')} (this instance)"
        )
    else:
        what = "no live status: every version is expected to be recorded"
    report("/live/status", status == 200 or not vendor_dir.is_dir(), status, what)

    counts = {"live": 0, "recorded": 0}
    for n in versions(snapshot_dir, vendor_dir):
        vendored = (vendor_dir / f"v{n}" / "VENDORED.json").is_file()
        status, final, _ = get(f"{site}/v{n}")
        report(f"/v{n}", status == 200 and final.endswith(f"/v{n}/"), status, f"leads to {final}")
        status, _, body = get(f"{site}/v{n}/")
        is_live = f'data-live-version="{n}"'.encode() in body
        is_recorded = f'data-snapshot-version="{n}"'.encode() in body
        state = states.get(str(n), {})
        if status == 200 and is_live:
            counts["live"] += 1
            report(f"/v{n}/", True, status, f"LIVE      {state.get('ref', '')} {state.get('commit', '')}")
            status, _, body = get(f"{site}/v{n}/live-shim.js")
            report(f"/v{n}/live-shim.js", status == 200 and b"window.fetch" in body, status, "the shim")
            first = "api/research" if n == 1 else "api/meta"
            status, _, body = get(f"{site}/v{n}/{first}")
            report(f"/v{n}/{first}", status == 200 and body[:1] == b"{", status, "the version's own API answers")
        elif status == 200 and is_recorded:
            counts["recorded"] += 1
            reason = state.get("import_error") or "the server reports no live status for it"
            why = f"vendored here but not running live there: {reason}" if vendored else "no live copy"
            report(f"/v{n}/", allow_recorded or not vendored, status, f"RECORDED  {why}")
            status, _, body = get(f"{site}/v{n}/snapshot.js")
            report(f"/v{n}/snapshot.js", status == 200 and b"window.fetch" in body, status, "the shim")
            manifest_path = snapshot_dir / f"v{n}" / "snapshot.json"
            if manifest_path.is_file():
                manifest = json.loads(manifest_path.read_text())
                for route, file in list(manifest["routes"].items())[:1]:
                    status, _, _ = get(f"{site}/v{n}/{file}")
                    report(f"/v{n}/{file}", status == 200, status, f"the recorded answer to GET {route}")
        else:
            report(f"/v{n}/", False, status, "NEITHER the live banner nor the recorded one")
    print(f"{counts['live']} versions live, {counts['recorded']} recorded.")
    print(f"{failures} of the checks above failed." if failures else "Every check passed.")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
