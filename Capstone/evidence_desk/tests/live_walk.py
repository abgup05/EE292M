"""Walk the live application end to end, over real HTTP, with recorded model answers.

``make live-walk`` starts the app with the NVIDIA cassette, then runs this inside
the container. It needs SEC EDGAR (the filings are fetched for real) but no model
key. It exercises what the offline tests reach only through fakes: a run on live
filings, decisions on its findings, the reviewed brief, a saved thesis, a second
run of it from the filing cache, and the comparison of the two.

It prints one line per step and exits non-zero at the first step that fails.
"""

from __future__ import annotations

import json
import sys
import time
import urllib.error
import urllib.request
from typing import Any

ROOT = "http://127.0.0.1:8000"


def call(method: str, path: str, body: dict[str, Any] | None = None) -> tuple[int, Any]:
    """One request; JSON bodies are decoded, anything else is returned as text."""
    data = json.dumps(body).encode() if body is not None else None
    headers = {"content-type": "application/json"} if body is not None else {}
    request = urllib.request.Request(ROOT + path, data=data, headers=headers, method=method)
    try:
        with urllib.request.urlopen(request, timeout=60) as response:
            raw, status = response.read(), response.status
            kind = response.headers.get("content-type", "")
    except urllib.error.HTTPError as error:
        raw, status, kind = error.read(), error.code, error.headers.get("content-type", "")
    return status, (json.loads(raw) if "json" in kind else raw.decode())


def expect(condition: bool, message: str) -> None:
    """Print the step, or stop the walk."""
    if not condition:
        print(f"FAIL: {message}")
        sys.exit(1)
    print(f"ok: {message}")


def wait_for_app() -> None:
    for _ in range(80):
        try:
            if call("GET", "/api/health")[0] == 200:
                return
        except OSError:
            pass
        time.sleep(0.25)
    expect(False, "the app answers /api/health")


def finished(run_id: str) -> dict[str, Any]:
    for _ in range(400):
        status, run = call("GET", f"/api/runs/{run_id}")
        if status == 200 and run["status"] != "running":
            return run
        time.sleep(0.5)
    expect(False, f"run {run_id} finishes within 200 s")
    raise AssertionError


def main() -> int:
    wait_for_app()
    _, meta = call("GET", "/api/meta")
    example = meta["example"]
    print(f"engine: {meta['engine']}; version {meta['version']}")

    status, started = call("POST", "/api/runs", example)
    expect(status == 202, "a run on the example thesis starts (202)")
    run = finished(started["id"])
    coverage = run["coverage"]
    print(
        f"   run {run['id']}: {run['status']}; {coverage['sources_read']} of "
        f"{coverage['sources_requested']} filings from live EDGAR; "
        f"{coverage['findings_verified']} of {coverage['findings_proposed']} findings verified; "
        f"{coverage['engine_fallbacks']} engine fallback(s)"
    )
    for claim in run["claims"]:
        print(f"   {claim['id']} {claim['verdict']}: {claim['text']}")
    expect(run["status"] in ("complete", "partial"), "the run finishes with a brief")
    expect(coverage["sources_read"] == coverage["sources_requested"], "every filing was read")
    judged = coverage["engine_fallbacks"] == 0
    print(
        "   the recorded answers matched the live filings"
        if judged
        else "   NOTE: the live prompts no longer match the cassette, so the deterministic "
        "engine answered; the review steps below still run"
    )

    findings = run["findings"]
    expect(bool(findings), "the run has verified findings to review")
    first, last = findings[0], findings[-1]
    status, review = call(
        "PUT",
        f"/api/runs/{run['id']}/findings/{first['id']}/decision",
        {"value": "accepted", "note": "Read in the filing."},
    )
    expect(status == 200 and review["decided"] == 1, "accepting a finding is recorded")
    status, review = call(
        "PUT",
        f"/api/runs/{run['id']}/findings/{last['id']}/decision",
        {"value": "rejected", "note": "Does not bear on the claim."},
    )
    expect(status == 200 and review["decided"] == 2, "rejecting another is recorded")
    status, review = call("GET", f"/api/runs/{run['id']}/review")
    reviewed = [c for c in review["claims"] if c["reviewed_verdict"] is not None]
    expect(status == 200 and bool(reviewed), "the review returns reviewed verdicts")
    for claim in reviewed:
        print(
            f"   {claim['claim_id']} engine {claim['engine_verdict']} -> after review "
            f"{claim['reviewed_verdict']} ({claim['accepted']} accepted, "
            f"{claim['rejected']} rejected, {claim['undecided']} undecided)"
        )
    status, brief = call("GET", f"/api/runs/{run['id']}/export.md?reviewed=true")
    expect(status == 200 and "Rejected" in brief and "Accepted" in brief, "the reviewed brief")

    status, thesis = call(
        "POST", "/api/theses", {"name": "NVIDIA into earnings", "request": example}
    )
    expect(status == 201, "the thesis is saved (201)")
    status, changes = call("GET", f"/api/theses/{thesis['id']}/changes")
    expect(status == 409, "one run is not enough to compare (409)")
    runs = []
    for _ in range(2):
        status, started = call("POST", f"/api/theses/{thesis['id']}/runs")
        expect(status == 202, "a run of the saved thesis starts (202)")
        runs.append(finished(started["id"]))
    cached = [line for line in runs[1]["coverage_limits"] if "cache" in line]
    expect(bool(cached), f"the later run read its filings from the cache: {cached[:1]}")
    status, changes = call("GET", f"/api/theses/{thesis['id']}/changes")
    expect(status == 200, "the two runs are compared")
    print(f"   {changes['note']}")
    expect(
        changes["verdicts_moved"] == 0,
        "no verdict moved between two runs on the same filings and the same answers",
    )
    print("live walk: PASS")
    return 0


if __name__ == "__main__":
    sys.exit(main())
