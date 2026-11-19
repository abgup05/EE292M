"""Run the real seed case against the live app and record what happened.

Writes ``results/demo-<UTC timestamp>.md`` containing a measured summary
(sources retrieved or failed, findings verified or withheld, status) followed
by the exported brief. Nothing in the summary is asserted; it is a record.
"""

from __future__ import annotations

import json
import sys
import time
import urllib.error
import urllib.request
from datetime import UTC, datetime
from pathlib import Path

ROOT = "http://127.0.0.1:8000"
RESULTS_DIR = Path("results")
SEED_CASE = {
    "question": (
        "What opportunities and risks should an organization examine before using "
        "generative AI in internal workflows?"
    ),
    "decision": "Whether to investigate a limited internal pilot",
    "scope_notes": "Public evidence; distinguish documented findings from open questions.",
    "seed_urls": [
        "https://www.nist.gov/publications/artificial-intelligence-risk-management-framework-ai-rmf-10",
        "https://www.gao.gov/products/gao-24-106946",
    ],
    "source_budget": 10,
}


def _request(path: str, body: dict | None = None) -> tuple[int, bytes]:
    data = json.dumps(body).encode() if body is not None else None
    headers = {"content-type": "application/json"} if body is not None else {}
    req = urllib.request.Request(ROOT + path, data=data, headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=30) as response:
            return response.status, response.read()
    except urllib.error.HTTPError as error:
        return error.code, error.read()


def _wait_for_startup() -> None:
    for attempt in range(40):
        try:
            urllib.request.urlopen(ROOT + "/", timeout=5)
            return
        except urllib.error.URLError:
            if attempt == 39:
                raise
            time.sleep(0.25)


def main() -> int:
    _wait_for_startup()
    started = time.monotonic()
    status, body = _request("/api/research", SEED_CASE)
    if status != 202:
        print(f"demo: could not start run (HTTP {status}): {body.decode(errors='replace')}")
        return 1
    run_id = json.loads(body)["id"]
    print(f"demo: started {run_id}")
    while True:
        status, body = _request(f"/api/research/{run_id}")
        run = json.loads(body)
        if run["status"] != "running":
            break
        if time.monotonic() - started > 400:
            print("demo: run did not finish within 400 s")
            return 1
        time.sleep(2)
    elapsed = time.monotonic() - started
    status, export = _request(f"/api/research/{run_id}/export.md")

    extracted = [s for s in run["sources"] if s["extraction_status"] == "extracted"]
    failed = [s for s in run["sources"] if s["extraction_status"] != "extracted"]
    lines = [
        "# Evidence Desk demo record",
        "",
        f"- Recorded: {datetime.now(UTC).strftime('%Y-%m-%d %H:%M:%S UTC')}",
        f"- Run: {run['id']}; status: **{run['status'].upper()}**; "
        f"synthesizer: {run['synthesizer']}",
        f"- Wall time: {elapsed:.1f} s",
        f"- Sources extracted: {len(extracted)}; failed or duplicate: {len(failed)}",
        f"- Subquestions: {len(run['subquestions'])}",
        f"- Verified findings: {len(run['findings'])}; "
        f"withheld (unverified): {len(run['unsupported_findings'])}",
        f"- Evidence excerpts verified: {len(run['evidence'])}",
        "",
        "## Sources",
        "",
    ]
    for source in run["sources"]:
        if source["extraction_status"] == "extracted":
            lines.append(
                f"- {source['id']}: {source['title']} ({source['publisher']}); "
                f"published {source['published_date'] or 'not available'}; "
                f"retrieved {source['retrieved_at']}; {source['canonical_url']}"
            )
        else:
            lines.append(f"- {source['id']}: FAILED {source['requested_url']}: {source['error']}")
    lines += ["", "## Coverage limits", ""]
    lines += [f"- {limit}" for limit in run["coverage_limits"]] or ["- none"]
    lines += ["", "## Errors", ""]
    lines += [f"- {error}" for error in run["errors"]] or ["- none"]
    lines += ["", "---", "", "# Exported brief", "", export.decode(errors="replace")]

    RESULTS_DIR.mkdir(exist_ok=True)
    out = RESULTS_DIR / f"demo-{datetime.now(UTC).strftime('%Y%m%dT%H%M%SZ')}.md"
    out.write_text("\n".join(lines))
    print("\n".join(lines[:12]))
    print(f"demo: wrote {out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
