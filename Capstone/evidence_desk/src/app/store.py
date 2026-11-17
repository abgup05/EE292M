"""SQLite persistence, split by what can be rebuilt.

:class:`Store` is **the record**: runs, reviewers' decisions and saved theses,
in one file (``<data dir>/record/record.sqlite``). Nothing can rebuild it: a
later run meets a different EDGAR, perhaps a different parser and model. It is
the only file that is backed up (:mod:`app.backup`).

:class:`FilingCache` is **disposable** (``<data dir>/cache/filings.sqlite``):
the extracted text of each document, stored once and keyed by the SHA-256 of
that text, and an index from a filing (accession, parser version) to its
parsed result, so a filing fetched and parsed once is not fetched again.
Deleting it loses nothing: the next run fetches and parses again. Source text
is never copied into the record; :meth:`FilingCache.source_texts` is the one
way to read the stored text of a run's sources.
"""

from __future__ import annotations

import hashlib
import json
import logging
import sqlite3
import threading
from collections.abc import Iterator, Sequence
from contextlib import closing, contextmanager
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Final

from pydantic import BaseModel, ValidationError

from app.core.models import Decision, ExtractionStatus, Run, RunStatus, Thesis

logger = logging.getLogger(__name__)

MEMORY: Final = ":memory:"

RECORD_SCHEMA = """
CREATE TABLE IF NOT EXISTS runs (
    id TEXT PRIMARY KEY,
    started_at TEXT NOT NULL,
    thesis_id TEXT,
    record TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS runs_by_start ON runs (started_at);
CREATE INDEX IF NOT EXISTS runs_by_thesis ON runs (thesis_id, started_at);
CREATE TABLE IF NOT EXISTS decisions (
    run_id TEXT NOT NULL,
    finding_id TEXT NOT NULL,
    decided_at TEXT NOT NULL,
    record TEXT NOT NULL,
    PRIMARY KEY (run_id, finding_id)
);
CREATE TABLE IF NOT EXISTS theses (
    id TEXT PRIMARY KEY,
    created_at TEXT NOT NULL,
    record TEXT NOT NULL
);
"""

CACHE_SCHEMA = """
CREATE TABLE IF NOT EXISTS texts (
    content_hash TEXT PRIMARY KEY,
    text TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS filings (
    accession TEXT NOT NULL,
    parser_version TEXT NOT NULL,
    content_hash TEXT NOT NULL,
    publisher TEXT NOT NULL,
    sections TEXT NOT NULL,
    retrieved_at TEXT NOT NULL,
    PRIMARY KEY (accession, parser_version)
);
"""


def text_hash(text: str) -> str:
    """Hex SHA-256 of ``text`` as UTF-8: the key a document's text is cached under."""
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


class _Database:
    """One SQLite file behind one connection, shared by threads under a lock.

    WAL lets a second process (a ``make run`` container) read and write the
    same file. A transaction is durable (``synchronous=FULL``: the WAL is
    synced to disk at commit) unless the caller says it need not be; then
    ``synchronous=NORMAL`` leaves the sync to the next durable commit or
    checkpoint. A power cut can lose such a commit, never corrupt the file
    (``docs/speed.md``: the commit's sync, not the connection, was the cost
    of a save).
    """

    def __init__(self, path: Path | str, schema: str) -> None:
        self.path: Path | str = path if str(path) == MEMORY else Path(path)
        if isinstance(self.path, Path):
            self.path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.RLock()
        self._connection = sqlite3.connect(self.path, timeout=30, check_same_thread=False)
        with self._lock, self._connection as connection:
            if self.path != MEMORY:
                connection.execute("PRAGMA journal_mode=WAL")
            connection.executescript(schema)

    @contextmanager
    def transaction(self, durable: bool = True) -> Iterator[sqlite3.Connection]:
        """The shared connection inside one transaction, committed on success.

        ``durable=False`` lets the commit return before the WAL reaches the disk.
        """
        with self._lock:
            if self.path != MEMORY:
                level = "FULL" if durable else "NORMAL"
                self._connection.execute(f"PRAGMA synchronous={level}")
            with self._connection as connection:
                yield connection

    def query(self, sql: str, parameters: Sequence[object] = ()) -> list[tuple]:
        """Every row ``sql`` selects."""
        with self._lock:
            return self._connection.execute(sql, parameters).fetchall()

    def close(self) -> None:
        """Close the connection; the object must not be used afterwards."""
        with self._lock:
            self._connection.close()


def _parse[M: BaseModel](model: type[M], key: str, record: str) -> M | None:
    """``record`` as ``model``, or None (with a warning) if it no longer validates."""
    try:
        return model.model_validate_json(record)
    except ValidationError as error:
        logger.warning(
            "Skipping stored %s %s: its record does not match the current format "
            "(%d validation error(s)).",
            model.__name__.lower(),
            key,
            error.error_count(),
        )
        return None


class Store:
    """The record: runs, decisions and saved theses, in one SQLite file.

    Thread-safe: every call goes through one connection under a lock. Records
    that no longer validate against the current models are skipped with a
    warning, never raised.
    """

    def __init__(self, path: Path | str) -> None:
        """Open (creating if needed) the record database at ``path``."""
        self._db = _Database(path, RECORD_SCHEMA)
        self.path = self._db.path

    def close(self) -> None:
        """Close the database connection."""
        self._db.close()

    # Runs

    def save_run(self, run: Run) -> None:
        """Insert or replace the full run record; its thesis id is indexed beside it.

        A progress save (the run still running) is not synced to disk on its
        own: a power cut would lose at most the latest progress of a run that
        would then never finish anyway. The final save is durable, and so
        carries every save before it.
        """
        record = run.model_dump_json()
        with self._db.transaction(durable=run.status != RunStatus.running) as connection:
            connection.execute(
                "INSERT OR REPLACE INTO runs (id, started_at, thesis_id, record) "
                "VALUES (?, ?, ?, ?)",
                (run.id, run.started_at.isoformat(), run.thesis_id, record),
            )

    def get_run(self, run_id: str) -> Run | None:
        """The run with ``run_id``; None if absent or stored in an outdated format."""
        rows = self._db.query("SELECT record FROM runs WHERE id = ?", (run_id,))
        return _parse(Run, run_id, rows[0][0]) if rows else None

    def list_runs(self, limit: int = 50) -> list[Run]:
        """Up to ``limit`` runs, most recent first; outdated records are skipped and logged."""
        rows = self._db.query(
            "SELECT id, record FROM runs ORDER BY started_at DESC, id DESC LIMIT ?", (limit,)
        )
        return [run for run_id, record in rows if (run := _parse(Run, run_id, record))]

    def run_ids(self) -> list[str]:
        """The id of every stored run, sorted, including records that no longer validate."""
        return [row[0] for row in self._db.query("SELECT id FROM runs ORDER BY id")]

    def runs_of_thesis(self, thesis_id: str) -> list[Run]:
        """Every run of the saved thesis ``thesis_id``, newest first."""
        rows = self._db.query(
            "SELECT id, record FROM runs WHERE thesis_id = ? ORDER BY started_at DESC, id DESC",
            (thesis_id,),
        )
        return [run for run_id, record in rows if (run := _parse(Run, run_id, record))]

    # Decisions

    def save_decision(self, decision: Decision) -> None:
        """Keep ``decision``; one per run and finding, so saving again replaces the earlier one."""
        with self._db.transaction() as connection:
            connection.execute(
                "INSERT OR REPLACE INTO decisions (run_id, finding_id, decided_at, record) "
                "VALUES (?, ?, ?, ?)",
                (
                    decision.run_id,
                    decision.finding_id,
                    decision.decided_at.isoformat(),
                    decision.model_dump_json(),
                ),
            )

    def clear_decision(self, run_id: str, finding_id: str) -> None:
        """Remove the decision on ``finding_id`` of ``run_id``, if there is one."""
        with self._db.transaction() as connection:
            connection.execute(
                "DELETE FROM decisions WHERE run_id = ? AND finding_id = ?", (run_id, finding_id)
            )

    def list_decisions(self, run_id: str) -> list[Decision]:
        """Every decision on ``run_id``, in the order decided (a replaced one counts as new)."""
        rows = self._db.query(
            "SELECT finding_id, record FROM decisions WHERE run_id = ? ORDER BY decided_at, rowid",
            (run_id,),
        )
        return [
            decision
            for finding_id, record in rows
            if (decision := _parse(Decision, f"{run_id}/{finding_id}", record))
        ]

    def all_decisions(self) -> list[Decision]:
        """Every decision in the record, by run and then in the order decided."""
        rows = self._db.query(
            "SELECT run_id, finding_id, record FROM decisions ORDER BY run_id, decided_at, rowid"
        )
        return [
            decision
            for run_id, finding_id, record in rows
            if (decision := _parse(Decision, f"{run_id}/{finding_id}", record))
        ]

    # Saved theses

    def save_thesis(self, thesis: Thesis) -> None:
        """Insert or replace the saved thesis."""
        with self._db.transaction() as connection:
            connection.execute(
                "INSERT OR REPLACE INTO theses (id, created_at, record) VALUES (?, ?, ?)",
                (thesis.id, thesis.created_at.isoformat(), thesis.model_dump_json()),
            )

    def get_thesis(self, thesis_id: str) -> Thesis | None:
        """The saved thesis ``thesis_id``; None if absent or stored in an outdated format."""
        rows = self._db.query("SELECT record FROM theses WHERE id = ?", (thesis_id,))
        return _parse(Thesis, thesis_id, rows[0][0]) if rows else None

    def list_theses(self) -> list[Thesis]:
        """Every saved thesis, newest first."""
        rows = self._db.query("SELECT id, record FROM theses ORDER BY created_at DESC, id DESC")
        return [thesis for key, record in rows if (thesis := _parse(Thesis, key, record))]

    # Backup

    def counts(self) -> dict[str, int]:
        """Rows in the record: runs, decisions and theses (outdated records included)."""
        queries = {
            "runs": "SELECT COUNT(*) FROM runs",
            "decisions": "SELECT COUNT(*) FROM decisions",
            "theses": "SELECT COUNT(*) FROM theses",
        }
        return {table: self._db.query(sql)[0][0] for table, sql in queries.items()}

    def backup(self, target: Path) -> None:
        """Copy the record to ``target`` with SQLite's online backup API.

        Safe while the app is running: the copy is one consistent snapshot of
        what was committed, and a transaction still open on another connection
        is not in it. ``target`` is replaced if it exists.
        """
        if self.path == MEMORY:
            raise ValueError("an in-memory record cannot be backed up")
        target.parent.mkdir(parents=True, exist_ok=True)
        target.unlink(missing_ok=True)
        with (
            closing(sqlite3.connect(self.path, timeout=30)) as source,
            closing(sqlite3.connect(target)) as copy,
        ):
            source.backup(copy)


@dataclass(frozen=True)
class CachedFiling:
    """What the cache knows about one parsed filing: enough to rebuild its document.

    ``sections`` are (heading, start, length) in the text cached under
    ``content_hash``; ``retrieved_at`` is when the filing was fetched from EDGAR.
    """

    accession: str
    parser_version: str
    content_hash: str
    publisher: str
    sections: tuple[tuple[str, int, int], ...]
    retrieved_at: datetime


class FilingCache:
    """Disposable: document text once per content hash, and parsed filings by accession.

    Thread-safe. ``path`` may be ``":memory:"`` for a cache that lives as long
    as the object (what a run gets when it is given no cache).
    """

    def __init__(self, path: Path | str = MEMORY) -> None:
        """Open (creating if needed) the cache database at ``path``."""
        self._db = _Database(path, CACHE_SCHEMA)
        self.path = self._db.path

    def close(self) -> None:
        """Close the database connection."""
        self._db.close()

    def put_text(self, content_hash: str, text: str) -> None:
        """Keep ``text`` under ``content_hash``, which must be its SHA-256 (else ValueError)."""
        if text_hash(text) != content_hash:
            raise ValueError("content_hash is not the SHA-256 of the text")
        with self._db.transaction() as connection:
            connection.execute(
                "INSERT OR IGNORE INTO texts (content_hash, text) VALUES (?, ?)",
                (content_hash, text),
            )

    def get_text(self, content_hash: str) -> str | None:
        """The text cached under ``content_hash``; None if absent or no longer matching it."""
        rows = self._db.query("SELECT text FROM texts WHERE content_hash = ?", (content_hash,))
        if not rows:
            return None
        text: str = rows[0][0]
        if text_hash(text) != content_hash:
            logger.warning("Cached text %s does not match its hash; it is ignored", content_hash)
            return None
        return text

    def remember_filing(
        self,
        accession: str,
        parser_version: str,
        *,
        content_hash: str,
        publisher: str,
        sections: Sequence[tuple[str, int, int]],
        retrieved_at: datetime,
    ) -> None:
        """Note that ``accession`` parsed by ``parser_version`` gave the text ``content_hash``."""
        with self._db.transaction() as connection:
            connection.execute(
                "INSERT OR REPLACE INTO filings (accession, parser_version, content_hash, "
                "publisher, sections, retrieved_at) VALUES (?, ?, ?, ?, ?, ?)",
                (
                    accession,
                    parser_version,
                    content_hash,
                    publisher,
                    json.dumps([list(section) for section in sections]),
                    retrieved_at.isoformat(),
                ),
            )

    def lookup_filing(self, accession: str, parser_version: str) -> CachedFiling | None:
        """The filing ``accession`` as ``parser_version`` parsed it, if it is cached."""
        rows = self._db.query(
            "SELECT content_hash, publisher, sections, retrieved_at FROM filings "
            "WHERE accession = ? AND parser_version = ?",
            (accession, parser_version),
        )
        if not rows:
            return None
        content_hash, publisher, sections, retrieved_at = rows[0]
        return CachedFiling(
            accession=accession,
            parser_version=parser_version,
            content_hash=content_hash,
            publisher=publisher,
            sections=tuple((str(h), int(s), int(n)) for h, s, n in json.loads(sections)),
            retrieved_at=datetime.fromisoformat(retrieved_at),
        )

    def source_texts(self, run: Run) -> dict[str, str]:
        """The stored text of every extracted source of ``run`` that is cached, by source id.

        This is the one way stored source text is read (by the pipeline's gate
        and by tests). A source whose text is not cached is absent from the result.
        """
        texts: dict[str, str] = {}
        for source in run.sources:
            if source.extraction_status != ExtractionStatus.extracted or not source.content_hash:
                continue
            text = self.get_text(source.content_hash)
            if text is not None:
                texts[source.id] = text
        return texts
