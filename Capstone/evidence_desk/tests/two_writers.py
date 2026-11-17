"""Two processes write one record at once: the served app and a one-off container.

``python -m tests.two_writers`` (run by ``make two-writers``, against a SCRATCH record
under ``results/``, never the real one) is the check that review 6 asked for: the
README draws both the app and the one-off ``make run`` container writing
``record.sqlite`` across the bind mount, in WAL mode, and no test had run two.

What it does, with the app already serving the scratch record:

1. writes one run with one verified finding straight into the record (this process);
2. at the same time, for ``--rounds`` rounds, (a) asks the app over HTTP to record a
   decision on that finding, alternating accepted and rejected with the round in the
   note (the app's process writes), and (b) saves a new run straight into the record
   (this process writes);
3. then checks: no write failed on either side; SQLite's ``integrity_check`` says
   ok; every directly written run is there and parses; the app can serve the last of
   them; exactly one decision is stored and it is the last one the app was sent.

It prints what it measured and exits 1 on the first thing that is not so. It shows
that this arrangement held for this many writes on this machine once. It does not show
what a power cut does, and it is not part of ``make verify``.
"""

from __future__ import annotations

import argparse
import json
import sqlite3
import sys
import threading
import time
import urllib.error
import urllib.request
from contextlib import closing
from datetime import UTC, datetime
from typing import Any

from app import wiring
from app.core.models import (
    Claim,
    Company,
    Confidence,
    Finding,
    Run,
    RunStatus,
    Stance,
    ThesisRequest,
)

BASE = "http://app:8000"
SHARED_RUN = "run-two-writers"
REQUEST = ThesisRequest(
    ticker="NVDA",
    decision="A scratch record for the two-writers check",
    claims=["Data center revenue is still growing year over year."],
)


def _run(run_id: str) -> Run:
    """A small finished run with one verified finding, as the store keeps one."""
    return Run(
        id=run_id,
        inputs=REQUEST,
        status=RunStatus.complete,
        started_at=datetime.now(UTC),
        company=Company(cik=1045810, ticker="NVDA", name="NVIDIA CORP"),
        claims=[Claim(id="c1", text=REQUEST.claims[0], finding_ids=["f1"])],
        findings=[
            Finding(
                id="f1",
                claim_id="c1",
                statement="A statement written by the two-writers check.",
                stance=Stance.supports,
                evidence_ids=[],
                confidence=Confidence.high,
                rationale="Written by a test, not by an engine.",
                verified=True,
            )
        ],
    )


def call(method: str, path: str, body: dict[str, Any] | None = None) -> tuple[int, Any]:
    """One request to the served app: the status and the decoded JSON body (or its text)."""
    data = None if body is None else json.dumps(body).encode()
    request = urllib.request.Request(  # noqa: S310 - a fixed http URL on the compose network
        f"{BASE}{path}", data=data, method=method, headers={"Content-Type": "application/json"}
    )
    try:
        with urllib.request.urlopen(request, timeout=60) as response:  # noqa: S310
            return response.status, json.loads(response.read() or b"null")
    except urllib.error.HTTPError as error:
        return error.code, error.read().decode(errors="replace")[:300]


def wait_for_app() -> None:
    for _ in range(60):
        try:
            if call("GET", "/api/health")[0] == 200:
                return
        except OSError:
            pass
        time.sleep(0.5)
    raise SystemExit("FAIL: the app does not answer /api/health")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--rounds", type=int, default=200)
    args = parser.parse_args(argv)
    rounds: int = args.rounds
    wait_for_app()
    store = wiring.store_from_env()
    if store.counts()["runs"]:
        print("FAIL: the record is not empty; this check runs on a scratch record only")
        return 1
    store.save_run(_run(SHARED_RUN))

    failures: list[str] = []
    sent: list[tuple[str, str]] = []

    def through_the_app() -> None:
        for number in range(rounds):
            value = "accepted" if number % 2 == 0 else "rejected"
            note = f"round {number}"
            status, body = call(
                "PUT",
                f"/api/runs/{SHARED_RUN}/findings/f1/decision",
                {"value": value, "note": note},
            )
            if status != 200:
                failures.append(f"the app answered {status} in round {number}: {body}")
                return
            sent.append((value, note))

    def straight_into_the_record() -> None:
        for number in range(rounds):
            try:
                store.save_run(_run(f"run-direct-{number:04d}"))
            except sqlite3.Error as error:
                failures.append(f"a direct write failed in round {number}: {error}")
                return

    started = time.perf_counter()
    threads = [
        threading.Thread(target=through_the_app),
        threading.Thread(target=straight_into_the_record),
    ]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()
    elapsed = time.perf_counter() - started

    def expect(condition: bool, message: str) -> None:
        print(f"{'ok' if condition else 'FAIL'}: {message}")
        if not condition:
            failures.append(message)

    expect(not failures, f"no write failed on either side in {rounds} rounds each")
    with closing(sqlite3.connect(store.path, timeout=30)) as connection:
        integrity = connection.execute("PRAGMA integrity_check").fetchone()[0]
        mode = connection.execute("PRAGMA journal_mode").fetchone()[0]
    expect(integrity == "ok", f"SQLite's integrity_check says {integrity!r}")
    expect(mode == "wal", f"the record is in {mode} mode")
    ids = store.run_ids()
    direct = [run_id for run_id in ids if run_id.startswith("run-direct-")]
    expect(len(direct) == rounds, f"{len(direct)} of {rounds} directly written runs are stored")
    expect(not store.unreadable(), "every stored record parses")
    status, served = call("GET", f"/api/runs/run-direct-{rounds - 1:04d}")
    expect(status == 200 and served["id"] == direct[-1], "the app serves a run the other wrote")
    decisions = store.list_decisions(SHARED_RUN)
    last = sent[-1] if sent else ("", "")
    expect(
        len(decisions) == 1
        and (decisions[0].value.value, decisions[0].note) == last
        and len(sent) == rounds,
        f"one decision is stored and it is the last of the {len(sent)} the app was sent: {last}",
    )
    print(
        f"two writers: {rounds} decisions through the app and {rounds} runs written directly, "
        f"at the same time, in {elapsed:.2f} s"
    )
    if failures:
        print(f"two writers: FAIL ({failures[0]})")
        return 1
    print("two writers: PASS")
    return 0


if __name__ == "__main__":
    sys.exit(main())
