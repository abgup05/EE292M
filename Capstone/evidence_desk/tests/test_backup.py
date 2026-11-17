"""Backup with a tested restore: a backup is a valid snapshot, and restore-check catches drift.

The record is the one file nothing can rebuild, so a backup must be readable
when it is taken mid-write, a restore must reproduce every decision exactly,
and a corrupted or stale backup must fail loudly, naming what differs.
"""

from __future__ import annotations

import json
import sqlite3
from contextlib import closing
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from app import backup
from app.core.models import (
    Claim,
    Company,
    Confidence,
    Decision,
    DecisionValue,
    Finding,
    Run,
    RunStatus,
    Stance,
    Thesis,
    ThesisRequest,
)
from app.store import Store

REQUEST = ThesisRequest(
    ticker="NVDA",
    decision="Keep the position into the next earnings report",
    claims=["Data center revenue is still growing year over year."],
)
NOON = datetime(2026, 11, 17, 12, 0, tzinfo=UTC)
STATEMENT = "Data Center revenue grew 56% from a year ago."


def _run(run_id: str) -> Run:
    return Run(
        id=run_id,
        inputs=REQUEST,
        status=RunStatus.complete,
        started_at=NOON,
        company=Company(cik=1045810, ticker="NVDA", name="NVIDIA CORP"),
        claims=[Claim(id="c1", text=REQUEST.claims[0], finding_ids=["f1"])],
        findings=[
            Finding(
                id="f1",
                claim_id="c1",
                statement=STATEMENT,
                stance=Stance.supports,
                evidence_ids=["e1"],
                confidence=Confidence.high,
                rationale="Stated in the 10-Q.",
                verified=True,
            )
        ],
    )


def _decision(value: DecisionValue = DecisionValue.accepted, note: str = "") -> Decision:
    return Decision(run_id="run-1", finding_id="f1", value=value, note=note, decided_at=NOON)


@pytest.fixture
def store(tmp_path: Path) -> Store:
    record = Store(tmp_path / "data" / "record" / "record.sqlite")
    record.save_run(_run("run-1"))
    record.save_run(_run("run-2"))
    record.save_decision(_decision(note="Checked against the filing."))
    record.save_thesis(
        Thesis(id="th-1", name="NVIDIA growth", request=REQUEST, created_at=NOON, run_ids=["run-1"])
    )
    return record


def _integrity(database: Path, tmp_path: Path) -> tuple[str, list[str]]:
    """``PRAGMA integrity_check`` and the run ids of a copy of ``database``."""
    copy = tmp_path / "inspect.sqlite"
    copy.write_bytes(database.read_bytes())
    with closing(sqlite3.connect(copy)) as connection:
        check = connection.execute("PRAGMA integrity_check").fetchone()[0]
        ids = [row[0] for row in connection.execute("SELECT id FROM runs ORDER BY id")]
    return check, ids


def test_a_backup_taken_while_another_connection_is_mid_write_is_a_valid_database(
    store: Store, tmp_path: Path
) -> None:
    writer = sqlite3.connect(store.path, timeout=5, isolation_level=None)
    try:
        writer.execute("BEGIN IMMEDIATE")
        writer.execute(
            "INSERT INTO runs (id, started_at, record) VALUES ('run-uncommitted', '2026', '{}')"
        )
        target = tmp_path / "backups" / "copy.sqlite"
        store.backup(target)
        writer.execute("COMMIT")
    finally:
        writer.close()
    check, ids = _integrity(target, tmp_path)
    assert check == "ok"
    assert ids == ["run-1", "run-2"], "the copy holds what was committed, and only that"


def test_backup_writes_the_database_its_checksum_and_legible_decisions(
    store: Store, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    directory = tmp_path / "backups"
    code = backup.main(["backup", "--dir", str(directory)], store=store, now=NOON)
    assert code == 0
    database = directory / "record-20261117T120000Z.sqlite"
    checksum = directory / "record-20261117T120000Z.sqlite.sha256"
    decisions = directory / "decisions-20261117T120000Z.jsonl"
    assert sorted(directory.iterdir()) == sorted([database, checksum, decisions])
    assert checksum.read_text() == f"{backup.file_sha256(database)}  {database.name}\n"
    [line] = decisions.read_text().splitlines()
    entry = json.loads(line)
    assert entry["run_id"] == "run-1" and entry["finding_id"] == "f1"
    assert entry["value"] == "accepted" and entry["note"] == "Checked against the filing."
    assert entry["statement"] == STATEMENT and entry["claim"] == REQUEST.claims[0]
    assert entry["ticker"] == "NVDA" and entry["company"] == "NVIDIA CORP"
    printed = capsys.readouterr().out
    assert str(database) in printed and str(decisions) in printed
    assert "2 runs, 1 decisions and 1 theses" in printed


def test_restore_check_passes_on_an_unchanged_record(
    store: Store, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    directory = tmp_path / "backups"
    backup.main(["backup", "--dir", str(directory)], store=store, now=NOON)
    code = backup.main(["restore-check", "--dir", str(directory)], store=store, now=NOON)
    assert code == 0
    assert capsys.readouterr().out.splitlines()[-1] == (
        "PASS: record-20261117T120000Z.sqlite restores to the live record: "
        "2 runs, 1 decisions, 1 theses; taken less than a minute before this check"
    )


def test_restore_check_fails_naming_a_decision_changed_after_the_backup(
    store: Store, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    directory = tmp_path / "backups"
    backup.main(["backup", "--dir", str(directory)], store=store, now=NOON)
    store.save_decision(_decision(DecisionValue.rejected, note="Checked against the filing."))
    code = backup.main(["restore-check", "--dir", str(directory)], store=store)
    assert code == 1
    assert capsys.readouterr().out.splitlines()[-1] == (
        "FAIL: record-20261117T120000Z.sqlite: the decision on run-1/f1 differs in value: "
        "accepted in the backup, rejected live"
    )


def test_restore_check_fails_on_a_new_run_or_thesis_and_uses_the_newest_backup(
    store: Store, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    directory = tmp_path / "backups"
    backup.main(["backup", "--dir", str(directory)], store=store, now=NOON)
    store.save_run(_run("run-3"))
    assert backup.main(["restore-check", "--dir", str(directory)], store=store) == 1
    assert "run run-3 is in the live record but not in the backup" in capsys.readouterr().out
    later = NOON + timedelta(minutes=5)
    backup.main(["backup", "--dir", str(directory)], store=store, now=later)
    assert backup.main(["restore-check", "--dir", str(directory)], store=store) == 0
    assert "PASS: record-20261117T120500Z.sqlite" in capsys.readouterr().out


def test_a_corrupted_backup_fails_its_checksum(
    store: Store, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    directory = tmp_path / "backups"
    backup.main(["backup", "--dir", str(directory)], store=store, now=NOON)
    database = directory / "record-20261117T120000Z.sqlite"
    data = bytearray(database.read_bytes())
    data[len(data) // 2] ^= 0xFF
    database.write_bytes(bytes(data))
    code = backup.main(["restore-check", "--dir", str(directory)], store=store)
    assert code == 1
    out = capsys.readouterr().out
    assert "FAIL: record-20261117T120000Z.sqlite does not match its checksum" in out
    assert "the backup is corrupted" in out


def test_restore_check_fails_when_there_is_no_backup(
    store: Store, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    code = backup.main(["restore-check", "--dir", str(tmp_path / "none")], store=store)
    assert code == 1
    assert capsys.readouterr().out.startswith("FAIL: no backup in")


def test_the_backup_file_is_left_exactly_as_its_checksum_says(store: Store, tmp_path: Path) -> None:
    directory = tmp_path / "backups"
    written = backup.take_backup(store, directory, NOON)
    before = backup.file_sha256(written.database)
    assert backup.restore_check(store, directory).startswith("PASS")
    assert backup.file_sha256(written.database) == before
    assert sorted(p.name for p in directory.iterdir()) == sorted(
        [written.database.name, written.checksum.name, written.decisions.name]
    )


# Review 6 (docs/reviews/review-6-speed-system.md), findings 6 and 7 ---------------------------


def _write_row(store: Store, sql: str, parameters: tuple[str, ...]) -> None:
    """Put a row into the record behind the store's back, as an older version left it."""
    with closing(sqlite3.connect(store.path)) as connection:
        connection.execute(sql, parameters)
        connection.commit()


def test_restore_check_fails_when_a_run_changed_though_its_id_did_not(
    store: Store, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """Runs were compared by id only: a run rewritten after the backup passed."""
    directory = tmp_path / "backups"
    backup.main(["backup", "--dir", str(directory)], store=store, now=NOON)
    changed = _run("run-2")
    changed.status = RunStatus.partial
    store.save_run(changed)
    assert backup.main(["restore-check", "--dir", str(directory)], store=store, now=NOON) == 1
    assert capsys.readouterr().out.splitlines()[-1] == (
        "FAIL: record-20261117T120000Z.sqlite: run run-2 differs between the backup and the "
        "live record"
    )


def test_restore_check_fails_on_records_this_version_cannot_read(
    store: Store, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """A thesis and a decision that no longer validate were skipped on both sides, so they agreed.

    The backup and the live record hold the same rows; the check passed while the app could
    show neither. That is what a restore check after a change of schema is run to find.
    """
    _write_row(
        store,
        "INSERT INTO theses (id, created_at, record) VALUES (?, ?, ?)",
        ("th-old", NOON.isoformat(), '{"id": "th-old", "title": "a field this version dropped"}'),
    )
    _write_row(
        store,
        "INSERT INTO decisions (run_id, finding_id, decided_at, record) VALUES (?, ?, ?, ?)",
        ("run-2", "f1", NOON.isoformat(), '{"verdict": "yes"}'),
    )
    directory = tmp_path / "backups"
    backup.main(["backup", "--dir", str(directory)], store=store, now=NOON)
    assert backup.main(["restore-check", "--dir", str(directory)], store=store, now=NOON) == 1
    last = capsys.readouterr().out.splitlines()[-1]
    assert last.startswith("FAIL: record-20261117T120000Z.sqlite: 2 record(s) in it cannot be read")
    assert "the decision on run-2/f1" in last and "thesis th-old" in last


def test_a_record_changed_in_a_way_no_parser_sees_still_fails(
    store: Store, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """Two unreadable rows with the same key and different text are a difference too."""
    _write_row(
        store,
        "INSERT INTO theses (id, created_at, record) VALUES (?, ?, ?)",
        ("th-old", NOON.isoformat(), '{"id": "th-old", "note": "as backed up"}'),
    )
    directory = tmp_path / "backups"
    backup.main(["backup", "--dir", str(directory)], store=store, now=NOON)
    _write_row(store, "UPDATE theses SET record = ? WHERE id = ?", ('{"id": "th-old"}', "th-old"))
    assert backup.main(["restore-check", "--dir", str(directory)], store=store, now=NOON) == 1
    assert (
        "thesis th-old differs between the backup and the live record"
        in (capsys.readouterr().out.splitlines()[-1])
    )


@pytest.mark.parametrize(
    ("later", "words"),
    [
        (timedelta(seconds=20), "less than a minute"),
        (timedelta(minutes=5, seconds=10), "5 minutes"),
        (timedelta(hours=3, minutes=59), "3 hours"),
        (timedelta(days=2, hours=1), "2 days"),
        (timedelta(minutes=1), "1 minute"),
    ],
)
def test_the_pass_line_says_how_old_the_backup_is(
    store: Store,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
    later: timedelta,
    words: str,
) -> None:
    directory = tmp_path / "backups"
    backup.main(["backup", "--dir", str(directory)], store=store, now=NOON)
    code = backup.main(["restore-check", "--dir", str(directory)], store=store, now=NOON + later)
    assert code == 0
    assert capsys.readouterr().out.splitlines()[-1].endswith(f"; taken {words} before this check")


def test_status_says_what_the_newest_backup_does_not_hold(
    store: Store, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """Without comparing anything by hand: how old the newest backup is, and what it lacks."""
    directory = tmp_path / "backups"
    assert backup.main(["status", "--dir", str(directory)], store=store, now=NOON) == 0
    assert capsys.readouterr().out.strip() == (
        f"backup status: no backup in {directory}/. The record holds 2 runs, 1 decisions and "
        "1 theses with no copy (run `make backup`)."
    )
    backup.main(["backup", "--dir", str(directory)], store=store, now=NOON)
    capsys.readouterr()
    assert backup.main(["status", "--dir", str(directory)], store=store, now=NOON) == 0
    assert capsys.readouterr().out.strip() == (
        "backup status: record-20261117T120000Z.sqlite, taken less than a minute ago, holds "
        "everything in the record."
    )
    store.save_run(_run("run-3"))
    store.save_decision(_decision(DecisionValue.rejected, note="Changed my mind."))
    two_days = NOON + timedelta(days=2)
    assert backup.main(["status", "--dir", str(directory)], store=store, now=two_days) == 0
    assert capsys.readouterr().out.strip() == (
        "backup status: record-20261117T120000Z.sqlite, taken 2 days ago, does not hold 1 run "
        "and 1 decision made or changed since (run `make backup`)."
    )
