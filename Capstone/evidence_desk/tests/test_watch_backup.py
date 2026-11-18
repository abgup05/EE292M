"""The watch's tables are part of the record: backed up, restored and compared like the rest."""

from __future__ import annotations

import sqlite3
from contextlib import closing
from datetime import UTC, datetime, timedelta
from pathlib import Path

from app import backup
from app.core.watch_models import InboxKind
from app.store import Store
from app.watch.store import WatchStore
from tests.test_backup import NOON, _run
from tests.test_watch_store import filing, item, watch


def _watched(store: Store) -> WatchStore:
    watches = WatchStore(store)
    watches.put_watch(watch())
    watches.note_filings("th-1", [filing(1)], NOON)
    watches.put_item(item(1, 1, InboxKind.waiting))
    return watches


def test_restore_check_says_behind_on_an_inbox_item_read_after_the_backup(tmp_path: Path) -> None:
    store = Store(tmp_path / "record.sqlite")
    watches = _watched(store)
    directory = tmp_path / "backups"
    backup.take_backup(store, directory, NOON)
    assert backup.restore_check(store, directory, NOON).startswith("PASS")

    watches.mark_read(["ib-1"], NOON + timedelta(minutes=5), read=True)

    try:
        backup.restore_check(store, directory, NOON)
    except backup.BackupBehind as behind:
        assert "1 inbox item written since (first: inbox item ib-1)" in str(behind)
    else:
        raise AssertionError("restore-check passed on an inbox item changed after the backup")


def test_restore_check_fails_naming_an_inbox_item_changed_with_no_later_time(
    tmp_path: Path,
) -> None:
    """A row both hold that differs with nothing dated after the backup is a broken backup."""
    store = Store(tmp_path / "record.sqlite")
    _watched(store)
    directory = tmp_path / "backups"
    backup.take_backup(store, directory, NOON)
    with closing(sqlite3.connect(store.path)) as connection, connection:
        connection.execute("UPDATE inbox SET kind = 'moved' WHERE id = 'ib-1'")
    try:
        backup.restore_check(store, directory, NOON)
    except backup.BackupBehind:
        raise AssertionError("a change with no later time was taken for a late write") from None
    except backup.RestoreCheckFailed as failure:
        assert "inbox item ib-1 differs" in str(failure) and "kind column" in str(failure)
    else:
        raise AssertionError("restore-check passed on an inbox item changed in place")


def test_restore_check_fails_on_a_job_queued_after_the_backup(tmp_path: Path) -> None:
    store = Store(tmp_path / "record.sqlite")
    watches = _watched(store)
    directory = tmp_path / "backups"
    backup.take_backup(store, directory, NOON)

    watches.note_filings("th-1", [filing(2)], NOON)

    try:
        backup.restore_check(store, directory, NOON)
    except backup.RestoreCheckFailed as failure:
        # The first difference in table order: the filing was seen, then its job queued.
        assert "the seen filing th-1/0008888888-26-000002 is in the live record" in str(failure)
    else:
        raise AssertionError("restore-check passed on a job queued after the backup")


def test_a_backup_from_before_version_14_restores_to_a_record_with_empty_watch_tables(
    tmp_path: Path,
) -> None:
    store = Store(tmp_path / "record.sqlite")
    store.save_run(_run("run-1"))
    directory = tmp_path / "backups"
    backup.take_backup(store, directory, NOON)  # the record has no watch table yet

    WatchStore(store)  # version 13 opens it and adds the empty tables

    assert backup.restore_check(store, directory, NOON).startswith("PASS")


def test_restore_check_fails_on_a_watch_record_this_version_cannot_read(tmp_path: Path) -> None:
    store = Store(tmp_path / "record.sqlite")
    _watched(store)
    with closing(sqlite3.connect(store.path)) as connection, connection:
        connection.execute("UPDATE inbox SET record = ? WHERE id = ?", ('{"id": "ib-1"}', "ib-1"))
    directory = tmp_path / "backups"
    backup.take_backup(store, directory, NOON)

    try:
        backup.restore_check(store, directory, NOON)
    except backup.RestoreCheckFailed as failure:
        assert "inbox item ib-1" in str(failure)
        assert "cannot be read by this version" in str(failure)
    else:
        raise AssertionError("restore-check passed on an inbox item no version can read")


def test_the_pass_line_counts_the_watch_rows_it_compared(tmp_path: Path) -> None:
    store = Store(tmp_path / "record.sqlite")
    _watched(store)
    directory = tmp_path / "backups"
    backup.take_backup(store, directory, NOON)

    line = backup.restore_check(store, directory, NOON)

    assert "0 runs, 0 decisions, 0 theses" in line
    assert "1 watches, 1 seen filings, 1 watch jobs, 1 inbox items" in line


def test_status_names_watch_rows_changed_since_the_backup(tmp_path: Path) -> None:
    store = Store(tmp_path / "record.sqlite")
    watches = _watched(store)
    directory = tmp_path / "backups"
    backup.take_backup(store, directory, NOON)
    watches.mark_read(["ib-1"], NOON, read=True)

    line = backup.status(store, directory, datetime(2026, 11, 17, 13, 0, tzinfo=UTC))

    assert "does not hold 1 inbox item made or changed since" in line
