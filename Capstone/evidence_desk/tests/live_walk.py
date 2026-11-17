"""Walk the live application end to end, over real HTTP, with recorded model answers.

``make live-walk`` starts the app with the NVIDIA cassette, then runs this inside
the container. It needs SEC EDGAR (the filings are fetched for real) but no model
key. It exercises what the offline tests reach only through fakes: a run on live
filings, decisions on its findings, the reviewed brief, a saved thesis, a second
run of it from the filing cache, and the comparison of the two.

It prints one line per step and exits non-zero at the first step that fails. One of
the steps is that the engine did not fall back: a pass means a judged run. The recorded
answers match only while the company's reported facts are as they were when the cassette
was recorded, so this walk expires at the company's next filing.
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
    expect(
        coverage["engine_fallbacks"] == 0,
        "the recorded answers match the live filings, so the run is judged (if this fails, the "
        "company has filed again and the recording has expired: record the cassette again, "
        "docs/cassettes.md)",
    )

    status, linked = call("GET", f"/api/runs/{run['id']}/changes")
    expect(status == 200, "what changed in the filings the run read is listed under its claims")
    for pair in linked["compared"]:
        print(
            f"   compared {pair['form']}: {pair['later']['period_end']} against "
            f"{pair['earlier']['period_end']}"
        )
    for note in linked["notes"]:
        print(f"   note: {note}")
    listed_for = [claim["claim_id"] for claim in linked["claims"]]
    expect(
        listed_for == [claim["id"] for claim in run["claims"]],
        "every claim of the run has its list of changes, in the run's order",
    )
    expect(
        bool(linked["compared"]) or bool(linked["notes"]),
        "each filing was compared with the one before it, or a note says why not",
    )
    for claim in linked["claims"]:
        print(
            f"   {claim['claim_id']}: {len(claim['changes'])} changed paragraph(s) listed, "
            f"{claim['matched']} of {claim['considered']} share two words with the claim or "
            "its queries"
        )
    expect(
        not linked["compared"] or any(claim["changes"] for claim in linked["claims"]),
        "where filings were compared, at least one claim has a changed paragraph listed",
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

    status, _ = call("GET", "/api/companies/NVDA/changes?form=8-K")
    expect(status == 422, "a filing comparison of a form other than 10-K or 10-Q is refused (422)")
    status, diff = call("GET", "/api/companies/NVDA/changes?form=10-K")
    expect(status == 200, "the two latest annual reports are compared (live EDGAR or the cache)")
    totals = diff["totals"]
    print(
        f"   {diff['later']['form']} for {diff['later']['period_end']} against "
        f"{diff['earlier']['period_end']}: {totals['unchanged']} unchanged, "
        f"{totals['numbers_only']} numbers only, {totals['reworded']} reworded, "
        f"{totals['added']} added, {totals['removed']} removed"
    )
    expect(
        diff["earlier"]["period_end"] < diff["later"]["period_end"]
        and all(totals[name] == sum(item[name] for item in diff["items"]) for name in totals),
        "the earlier filing is the earlier one, and each total is the sum over the Items",
    )
    risk = next((item for item in diff["items"] if item["item"].startswith("Item 1A")), None)
    expect(
        risk is not None and risk["present_in"] == "both" and risk["unchanged"] > 0,
        "the risk factors were found in both reports",
    )

    status, tagged = call("GET", "/api/companies/NVDA/breakdowns?form=10-K")
    expect(status == 200, "the latest annual report's tagged breakdowns are read (live EDGAR)")
    found = {item["id"]: item for item in tagged["breakdowns"]}
    print(
        f"   {tagged['facts_read']} tagged facts read, {tagged['facts_unparsed']} unread; "
        f"breakdowns: {', '.join(found) or 'none'}"
    )
    expect(
        tagged["facts_read"] > 100 and tagged["facts_unparsed"] < tagged["facts_read"] / 100,
        "the filing's tagged numbers were read, with under one in a hundred left out",
    )
    segments = found.get("revenue_by_segment")
    expect(
        segments is not None and segments["adds_up"] is True,
        "revenue by segment is found and its members add up to the tagged total",
    )
    for row in (found.get("revenue_by_product") or {"rows": []})["rows"][:3]:
        newest = row["values"][0]
        print(f"   {row['label']}: {newest['shown']} for the period ended {newest['period_end']}")
    print("live walk: PASS")
    return 0


if __name__ == "__main__":
    sys.exit(main())
