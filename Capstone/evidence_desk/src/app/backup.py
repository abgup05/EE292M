"""Back up the record, and prove a backup restores.

``python -m app.backup backup`` (``make backup``) copies the record database
with SQLite's online backup API (safe while the app runs) to
``backups/record-<UTC>.sqlite``, writes its SHA-256 beside it
(``record-<UTC>.sqlite.sha256``, in ``sha256sum`` format) and writes
``backups/decisions-<UTC>.jsonl``: one decision per line, with the finding's
statement, the claim and the company, so each line is legible on its own. It
prints what it wrote and how many runs, decisions and theses the copy holds.

``python -m app.backup restore-check`` (``make restore-check``) checks the
newest backup's SHA-256, restores it into a temporary directory, opens it
with :class:`~app.store.Store` and compares it with the live record: the same
runs, decisions and saved theses, each row compared column by column as it is
stored (the record text, and the columns beside it that the app reads on their
own, such as a run's thesis id), so a record that no longer parses is compared
too, and a failure names the row and the column. It then fails if any record in
the backup cannot be read by this version of the app: a restore would keep
such a record in the file and the app would show nothing of it. It prints
PASS with the backup's age, or FAIL with the first difference, and exits 1 on
FAIL or when there is no backup.

``python -m app.backup status`` (``make backup-status``) prints one line: how
old the newest backup is and how many runs, decisions and theses were made or
changed since. It always exits 0; it is a reminder, not a check.

Only the record is backed up. The filing cache is disposable by design.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import sys
import tempfile
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

from app import wiring
from app.core.models import Decision, Finding, Run, Thesis
from app.store import Store

DEFAULT_DIRECTORY = Path("backups")
RECORD_PREFIX = "record-"
STAMP_FORMAT = "%Y%m%dT%H%M%SZ"
CHUNK_BYTES = 1 << 20


class RestoreCheckFailed(Exception):
    """The backup does not restore to the live record; the message names the first difference."""


@dataclass(frozen=True)
class BackupFiles:
    """What one backup wrote, and what the copied record holds."""

    database: Path
    checksum: Path
    decisions: Path
    counts: dict[str, int]


def file_sha256(path: Path) -> str:
    """Hex SHA-256 of the file at ``path``, read in chunks."""
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while chunk := handle.read(CHUNK_BYTES):
            digest.update(chunk)
    return digest.hexdigest()


def checksum_path(database: Path) -> Path:
    """Where the SHA-256 of ``database`` is kept: the same name plus ``.sha256``."""
    return database.with_name(database.name + ".sha256")


def _finding(run: Run | None, finding_id: str) -> Finding | None:
    if run is None:
        return None
    findings = [*run.findings, *run.unsupported_findings]
    return next((finding for finding in findings if finding.id == finding_id), None)


def decision_line(decision: Decision, run: Run | None) -> str:
    """One decision as a JSON line that can be read without the database."""
    finding = _finding(run, decision.finding_id)
    claim = None
    if run is not None and finding is not None:
        claim = next((c.text for c in run.claims if c.id == finding.claim_id), None)
    entry = {
        **decision.model_dump(mode="json"),
        "ticker": run.inputs.ticker if run is not None else None,
        "company": run.company.name if run is not None and run.company else None,
        "claim": claim,
        "statement": finding.statement if finding is not None else None,
        "stance": finding.stance.value if finding is not None else None,
    }
    if finding is None:
        entry["missing"] = "the run or the finding is not in the record"
    return json.dumps(entry, ensure_ascii=False)


@dataclass
class _Opened:
    """A copy of a database file opened as a record, in a temporary directory."""

    store: Store
    directory: tempfile.TemporaryDirectory[str]

    def close(self) -> None:
        self.store.close()
        self.directory.cleanup()


def _open_copy(database: Path) -> _Opened:
    """Restore ``database`` into a fresh temporary directory and open it as a record.

    Opening a WAL database writes beside it; working on a copy leaves the
    backup file byte for byte as its checksum says.
    """
    directory = tempfile.TemporaryDirectory(prefix="restore-")
    restored = Path(directory.name) / "record.sqlite"
    shutil.copyfile(database, restored)
    return _Opened(Store(restored), directory)


def take_backup(store: Store, directory: Path, now: datetime | None = None) -> BackupFiles:
    """Back up ``store`` into ``directory``: the database, its SHA-256 and the decisions."""
    stamp = (now or datetime.now(UTC)).strftime(STAMP_FORMAT)
    directory.mkdir(parents=True, exist_ok=True)
    database = directory / f"{RECORD_PREFIX}{stamp}.sqlite"
    if database.exists():
        raise FileExistsError(f"{database} already exists; wait a second and back up again")
    store.backup(database)
    checksum = checksum_path(database)
    checksum.write_text(f"{file_sha256(database)}  {database.name}\n")
    decisions = directory / f"decisions-{stamp}.jsonl"
    copy = _open_copy(database)
    try:
        runs: dict[str, Run | None] = {}
        lines = []
        for decision in copy.store.all_decisions():
            if decision.run_id not in runs:
                runs[decision.run_id] = copy.store.get_run(decision.run_id)
            lines.append(decision_line(decision, runs[decision.run_id]))
        decisions.write_text("".join(f"{line}\n" for line in lines), encoding="utf-8")
        counts = copy.store.counts()
    finally:
        copy.close()
    return BackupFiles(database, checksum, decisions, counts)


def newest_backup(directory: Path) -> Path | None:
    """The newest ``record-<UTC>.sqlite`` in ``directory`` (the stamp sorts by time), if any."""
    found = sorted(directory.glob(f"{RECORD_PREFIX}*.sqlite"))
    return found[-1] if found else None


def verify_checksum(database: Path) -> None:
    """Raise :class:`RestoreCheckFailed` unless ``database`` matches its ``.sha256`` file."""
    checksum = checksum_path(database)
    if not checksum.exists():
        raise RestoreCheckFailed(f"{database.name} has no checksum file ({checksum.name})")
    expected = (checksum.read_text().split() or [""])[0]
    actual = file_sha256(database)
    if actual != expected:
        raise RestoreCheckFailed(
            f"{database.name} does not match its checksum (expected {expected[:12]}…, "
            f"found {actual[:12]}…): the backup is corrupted"
        )


def _first_set_difference(kind: str, backup: Sequence[str], live: Sequence[str]) -> str | None:
    only_backup = sorted(set(backup) - set(live))
    only_live = sorted(set(live) - set(backup))
    if only_live:
        return f"{kind} {only_live[0]} is in the live record but not in the backup"
    if only_backup:
        return f"{kind} {only_backup[0]} is in the backup but not in the live record"
    return None


def _decision_difference(backup: list[Decision], live: list[Decision]) -> str | None:
    def key(decision: Decision) -> str:
        return f"{decision.run_id}/{decision.finding_id}"

    by_backup = {key(d): d for d in backup}
    by_live = {key(d): d for d in live}
    missing = _first_set_difference("the decision on", list(by_backup), list(by_live))
    if missing:
        return missing
    for name in sorted(by_live):
        was, now = by_backup[name], by_live[name]
        for field in Decision.model_fields:
            if getattr(was, field) != getattr(now, field):
                return (
                    f"the decision on {name} differs in {field}: "
                    f"{getattr(was, field)!s} in the backup, {getattr(now, field)!s} live"
                )
    return None


def _thesis_difference(backup: list[Thesis], live: list[Thesis]) -> str | None:
    by_backup = {t.id: t for t in backup}
    by_live = {t.id: t for t in live}
    missing = _first_set_difference("thesis", list(by_backup), list(by_live))
    if missing:
        return missing
    for thesis_id in sorted(by_live):
        if by_backup[thesis_id] != by_live[thesis_id]:
            return f"thesis {thesis_id} differs between the backup and the live record"
    return None


RECORD_KINDS: tuple[tuple[str, str], ...] = (
    ("runs", "run"),
    ("decisions", "the decision on"),
    ("theses", "thesis"),
)
MAX_NAMED = 3  # unreadable records named in a failure; the rest are counted


RECORD_COLUMN = "record"  # the stored JSON of a row: too long to quote in a failure
_ABSENT = object()  # a column one side's table does not have (a backup from another schema)


def _shown(value: object) -> str:
    return "no such column" if value is _ABSENT else str(value)


def _row_difference(
    word: str, key: str, was: dict[str, object], now: dict[str, object]
) -> str | None:
    """The first column in which one row differs between the backup and the live record."""
    columns = [*now, *(column for column in was if column not in now)]
    for column in columns:
        before, after = was.get(column, _ABSENT), now.get(column, _ABSENT)
        if before == after:
            continue
        named = (
            f"{word} {key} differs between the backup and the live record in its {column} column"
        )
        if column == RECORD_COLUMN:
            return named
        return f"{named}: {_shown(before)} in the backup, {_shown(after)} live"
    return None


def _stored_difference(table: str, word: str, backup: Store, live: Store) -> str | None:
    """The first row of ``table`` that the two do not hold alike, column by column, if any.

    Every column is compared as stored, without parsing: the record text, and the columns
    the app reads on their own (a run's ``thesis_id``, the times lists are ordered by).
    """
    in_backup, in_live = backup.raw_rows(table), live.raw_rows(table)
    missing = _first_set_difference(word, list(in_backup), list(in_live))
    if missing:
        return missing
    for key in sorted(in_live):
        if found := _row_difference(word, key, in_backup[key], in_live[key]):
            return found
    return None


def _difference(restored: Store, live: Store) -> str | None:
    """The first difference between a restored backup and the live record, most telling first.

    Runs by id, then every decision field by field (so a changed decision is named
    with what changed), then every row of every table column by column as stored,
    which also covers runs whose content changed, records neither side can parse and
    the columns kept beside the record (a run's thesis id, a decision's time).
    """
    return (
        _first_set_difference("run", restored.run_ids(), live.run_ids())
        or _decision_difference(restored.all_decisions(), live.all_decisions())
        or next(
            (
                found
                for table, word in RECORD_KINDS
                if (found := _stored_difference(table, word, restored, live))
            ),
            None,
        )
    )


def backup_time(database: Path) -> datetime | None:
    """When ``database`` was taken, from its name (``record-<UTC>.sqlite``); None if unreadable."""
    stamp = database.name.removeprefix(RECORD_PREFIX).removesuffix(".sqlite")
    try:
        return datetime.strptime(stamp, STAMP_FORMAT).replace(tzinfo=UTC)
    except ValueError:
        return None


def age_words(taken: datetime | None, now: datetime) -> str:
    """How long before ``now`` a backup was taken: whole minutes, hours or days."""
    if taken is None:
        return "an unknown time"
    seconds = max(0, int((now - taken).total_seconds()))
    for size, word in ((86400, "day"), (3600, "hour"), (60, "minute")):
        if seconds >= size:
            count = seconds // size
            return f"{count} {word}" if count == 1 else f"{count} {word}s"
    return "less than a minute"


def restore_check(live: Store, directory: Path, now: datetime | None = None) -> str:
    """Restore the newest backup and compare it with ``live``; the PASS line, or raise.

    Fails on the first row the two do not hold alike in every column, naming the row
    and the column, and then on any record in the backup that this version cannot read.
    """
    database = newest_backup(directory)
    if database is None:
        raise RestoreCheckFailed(f"no backup in {directory}/ (run `make backup` first)")
    verify_checksum(database)
    copy = _open_copy(database)
    try:
        restored = copy.store
        difference = _difference(restored, live)
        unreadable = restored.unreadable()
        counts = restored.counts()
    finally:
        copy.close()
    if difference:
        raise RestoreCheckFailed(f"{database.name}: {difference}")
    if unreadable:
        named = ", ".join(unreadable[:MAX_NAMED])
        more = f" and {len(unreadable) - MAX_NAMED} more" if len(unreadable) > MAX_NAMED else ""
        raise RestoreCheckFailed(
            f"{database.name}: {len(unreadable)} record(s) in it cannot be read by this version "
            f"of the app ({named}{more}); a restore would keep them in the file and show none"
        )
    age = age_words(backup_time(database), now or datetime.now(UTC))
    return (
        f"PASS: {database.name} restores to the live record: {counts['runs']} runs, "
        f"{counts['decisions']} decisions, {counts['theses']} theses; taken {age} before this check"
    )


def status(live: Store, directory: Path, now: datetime | None = None) -> str:
    """One line on the newest backup: its age, and what was made or changed since."""
    database = newest_backup(directory)
    if database is None:
        counts = live.counts()
        return (
            f"backup status: no backup in {directory}/. The record holds {counts['runs']} runs, "
            f"{counts['decisions']} decisions and {counts['theses']} theses with no copy "
            "(run `make backup`)."
        )
    age = age_words(backup_time(database), now or datetime.now(UTC))
    copy = _open_copy(database)
    try:
        behind: list[str] = []
        for table, noun in (("runs", "run"), ("decisions", "decision"), ("theses", "thesis")):
            # Every column, as restore-check compares them, so the two never disagree.
            held, current = copy.store.raw_rows(table), live.raw_rows(table)
            count = sum(1 for key, row in current.items() if held.get(key) != row)
            if count:
                plural = "theses" if noun == "thesis" else f"{noun}s"
                behind.append(f"{count} {noun}" if count == 1 else f"{count} {plural}")
    finally:
        copy.close()
    if not behind:
        return f"backup status: {database.name}, taken {age} ago, holds everything in the record."
    listed = " and ".join([", ".join(behind[:-1]), behind[-1]] if len(behind) > 1 else behind)
    return (
        f"backup status: {database.name}, taken {age} ago, does not hold {listed} made or "
        "changed since (run `make backup`)."
    )


def main(
    argv: list[str] | None = None,
    *,
    store: Store | None = None,
    now: datetime | None = None,
) -> int:
    """``backup``, ``restore-check`` or ``status`` [``--dir DIR``]; returns the exit code.

    ``now`` stamps a backup, and is the time a backup's age is measured at.
    """
    parser = argparse.ArgumentParser(
        prog="python -m app.backup", description=__doc__.split("\n")[0]
    )
    parser.add_argument("command", choices=("backup", "restore-check", "status"))
    parser.add_argument("--dir", type=Path, default=DEFAULT_DIRECTORY, help="backup directory")
    args = parser.parse_args(argv)
    live = store or wiring.store_from_env()
    if args.command == "backup":
        written = take_backup(live, args.dir, now)
        counts = written.counts
        print(f"wrote {written.database}")
        print(f"wrote {written.checksum}")
        print(f"wrote {written.decisions}")
        print(
            f"the backup holds {counts['runs']} runs, {counts['decisions']} decisions "
            f"and {counts['theses']} theses"
        )
        return 0
    if args.command == "status":
        print(status(live, args.dir, now))
        return 0
    try:
        print(restore_check(live, args.dir, now))
    except RestoreCheckFailed as failure:
        print(f"FAIL: {failure}")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
