"""Run the NVIDIA example against the live HTTP API and record what happened.

Run inside the app container (``make demo``) while the server is up. It reads
the example thesis from ``/api/meta``, starts it with ``POST /api/runs`` (real
SEC EDGAR, the configured engine), polls until the run finishes, and writes:

- ``results/demo-<UTC>.json``: the run record exactly as the API returned it;
- ``results/demo-<UTC>.md``: a measured summary followed by the exported brief.

Every number in the summary is read from the record or measured here (wall
time, when each stage was first seen); nothing is asserted.
"""

from __future__ import annotations

import json
import sys
import time
import urllib.error
import urllib.request
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

ROOT = "http://127.0.0.1:8000"
RESULTS_DIR = Path("results")
POLL_SECONDS = 1.0
GIVE_UP_SECONDS = 420.0
NOT_ASSESSED = "Not assessed"
REQUEST_TIMEOUT_SECONDS = 30


class DemoError(RuntimeError):
    """The demonstration could not run; the message says why."""


def _request(path: str, body: dict[str, Any] | None = None) -> tuple[int, bytes]:
    data = json.dumps(body).encode() if body is not None else None
    headers = {"content-type": "application/json"} if body is not None else {}
    req = urllib.request.Request(ROOT + path, data=data, headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=REQUEST_TIMEOUT_SECONDS) as response:
            return response.status, response.read()
    except urllib.error.HTTPError as error:
        return error.code, error.read()


def _json(path: str, body: dict[str, Any] | None = None, expect: int = 200) -> Any:
    status, payload = _request(path, body)
    if status != expect:
        raise DemoError(f"{path} answered HTTP {status}: {payload.decode(errors='replace')}")
    return json.loads(payload)


def _wait_for_startup() -> None:
    for attempt in range(80):
        try:
            urllib.request.urlopen(ROOT + "/api/health", timeout=5)
            return
        except (urllib.error.URLError, ConnectionError) as error:
            if attempt == 79:
                raise DemoError("The server did not start") from error
            time.sleep(0.25)


def _poll(run_id: str, started: float) -> tuple[dict[str, Any], list[tuple[float, str]]]:
    """Poll until the run leaves "running"; return it and when each stage was first seen."""
    timeline: list[tuple[float, str]] = []
    while True:
        run = _json(f"/api/runs/{run_id}")
        stage = run["stage"] + (f" ({run['stage_detail']})" if run["stage_detail"] else "")
        if not timeline or timeline[-1][1] != stage:
            timeline.append((time.monotonic() - started, stage))
            print(f"demo: {timeline[-1][0]:6.1f} s  {stage}", flush=True)
        if run["status"] != "running":
            return run, timeline
        if time.monotonic() - started > GIVE_UP_SECONDS:
            raise DemoError(f"The run did not finish within {GIVE_UP_SECONDS:.0f} s")
        time.sleep(POLL_SECONDS)


def _bullets(items: list[str]) -> list[str]:
    return [f"- {item}" for item in items] or ["- None."]


def summarize(
    run: dict[str, Any],
    meta: dict[str, Any],
    health: dict[str, Any],
    wall_seconds: float,
    timeline: list[tuple[float, str]],
) -> list[str]:
    """The measured summary of one finished run, as Markdown lines."""
    labels = meta["verdict_labels"]
    coverage = run["coverage"]
    lines = [
        "# Evidence Desk demo record",
        "",
        f"- Recorded: {datetime.now(UTC).strftime('%Y-%m-%d %H:%M:%S UTC')}",
        f"- Run: {run['id']}; status **{run['status'].upper()}**",
        f"- Wall time (POST to finished record): {wall_seconds:.1f} s",
        f"- Engine: {run['engine']}; model: {health.get('model') or 'none'}; "
        f"server version {health['version']}",
        f"- Company: {run['company']['name']} (CIK {run['company']['cik']})"
        if run.get("company")
        else "- Company: not resolved",
        "",
        "## Claims",
        "",
        "| Claim | Verdict | Verified findings | Withheld findings | Passages considered |",
        "| --- | --- | ---: | ---: | ---: |",
    ]
    for claim in run["claims"]:
        verdict = labels.get(claim["verdict"] or "", NOT_ASSESSED)
        withheld = sum(1 for f in run["unsupported_findings"] if f["claim_id"] == claim["id"])
        lines.append(
            f"| {claim['id']}. {claim['text']} | {verdict} | {len(claim['finding_ids'])} | "
            f"{withheld} | {claim['passages_considered']} |"
        )
    lines += [
        "",
        "## Coverage",
        "",
        f"- Sources read: {coverage['sources_read']} of {coverage['sources_requested']}",
        f"- Passages indexed: {coverage['passages_indexed']}",
        f"- Claims with verified excerpts or figures: {coverage['claims_with_evidence']} of "
        f"{coverage['claims_total']}",
        f"- Findings verified: {coverage['findings_verified']}; withheld: "
        f"{coverage['findings_withheld']}",
        f"- Quotes offered: {coverage['quotes_offered']}; found word for word: "
        f"{coverage['quotes_found']}; rejected: {coverage['quotes_rejected']}; kept as "
        f"evidence: {coverage['excerpts_verified']}",
        "",
        "## Sources",
        "",
        "| ID | Form | Period end | Filed | Retrieved (UTC) | Sections | Characters | Status |",
        "| --- | --- | --- | --- | --- | ---: | ---: | --- |",
    ]
    for source in run["sources"]:
        status = source["extraction_status"]
        if source.get("error"):
            status += f": {source['error']}"
        lines.append(
            f"| {source['id']} | {source.get('form') or 'web page'} | "
            f"{source.get('period_end') or 'n/a'} | {source.get('published_date') or 'n/a'} | "
            f"{source['retrieved_at']} | {source['sections']} | {source['characters']} | "
            f"{status} |"
        )
    lines += ["", "## Stage timeline (first seen while polling)", ""]
    lines += [f"- {seconds:6.1f} s: {stage}" for seconds, stage in timeline]
    lines += ["", "## Coverage limits", "", *_bullets(run["coverage_limits"])]
    lines += ["", "## Errors", "", *_bullets(run["errors"]), ""]
    return lines


def main() -> int:
    """Run the demonstration; 0 when a record was written, 1 otherwise."""
    try:
        _wait_for_startup()
        health = _json("/api/health")
        meta = _json("/api/meta")
        started = time.monotonic()
        run_id = _json("/api/runs", meta["example"], expect=202)["id"]
        print(f"demo: started {run_id} with the {health['engine']} engine", flush=True)
        run, timeline = _poll(run_id, started)
        wall = time.monotonic() - started
        status, export = _request(f"/api/runs/{run_id}/export.md")
        if status != 200:
            raise DemoError(f"The export answered HTTP {status}")
    except DemoError as error:
        print(f"demo: {error}", file=sys.stderr)
        return 1

    stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    RESULTS_DIR.mkdir(exist_ok=True)
    record = RESULTS_DIR / f"demo-{stamp}.json"
    record.write_text(json.dumps(run, indent=2, ensure_ascii=False) + "\n")
    lines = summarize(run, meta, health, wall, timeline)
    summary = RESULTS_DIR / f"demo-{stamp}.md"
    summary.write_text("\n".join([*lines, "---", "", export.decode("utf-8", errors="replace")]))
    print("\n".join(lines))
    print(f"demo: wrote {record} and {summary}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
