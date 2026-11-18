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

:class:`FactStore` is **disposable** too (``<data dir>/facts/facts.sqlite``):
every us-gaap fact of each company whose XBRL company facts were loaded, with the
filing (accession, form, filed date) that reported it, and a row per company
with its ticker, name and industry code. It is persistence and queries only:
:meth:`FactStore.payload` gives the facts back in EDGAR's own shape, and
:class:`app.core.facts.FactBook` remains the one place that places them in
periods. Deleting it loses nothing that EDGAR cannot give again.
"""

from __future__ import annotations

import hashlib
import json
import logging
import math
import sqlite3
import threading
from collections.abc import Iterator, Sequence
from contextlib import closing, contextmanager
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Final

from pydantic import BaseModel, ValidationError

from ed_v14.core.fact_models import CompanyProfile, StoredCompany, StoredFiling
from ed_v14.core.models import Decision, ExtractionStatus, Run, RunStatus, Thesis

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

# The tables of the record, and the SQL expression that keys a row of each.
RECORD_KEYS: Final = {
    "runs": "id",
    "decisions": "run_id || '/' || finding_id",
    "theses": "id",
    # Version 13, the standing watch: created by app.watch.store.WatchStore (Store.extend).
    "watches": "thesis_id",
    "watch_seen": "thesis_id || '/' || accession",
    "watch_jobs": "id",
    "inbox": "id",
}

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
CREATE TABLE IF NOT EXISTS tagged (
    accession TEXT NOT NULL,
    reader_version TEXT NOT NULL,
    report TEXT NOT NULL,
    PRIMARY KEY (accession, reader_version)
);
"""


FACTS_SCHEMA = """
CREATE TABLE IF NOT EXISTS companies (
    cik INTEGER PRIMARY KEY,
    ticker TEXT NOT NULL,
    name TEXT NOT NULL,
    sic TEXT NOT NULL,
    sic_description TEXT NOT NULL,
    facts INTEGER NOT NULL,
    skipped INTEGER NOT NULL,
    payload_sha256 TEXT NOT NULL,
    loaded_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS facts (
    cik INTEGER NOT NULL,
    concept TEXT NOT NULL,
    unit TEXT NOT NULL,
    start TEXT,
    end TEXT NOT NULL,
    value REAL NOT NULL,
    accession TEXT NOT NULL,
    form TEXT NOT NULL,
    filed TEXT NOT NULL,
    fy INTEGER,
    fp TEXT,
    frame TEXT
);
CREATE INDEX IF NOT EXISTS facts_by_concept ON facts (cik, concept, unit);
CREATE INDEX IF NOT EXISTS facts_by_filed ON facts (cik, filed);
"""
# The taxonomy a company-facts body keeps its US GAAP concepts under: the one stored.
GAAP = "us-gaap"


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

    def extend(self, schema: str) -> _Database:
        """Create a feature's own tables of the record if they are missing; the shared database.

        ``schema`` may only create what is missing (``CREATE ... IF NOT EXISTS``): the
        record is never dropped or rebuilt. The feature's repository (``app.watch.store``)
        then reads and writes through the same connection and lock as this store.
        """
        with self._db.transaction() as connection:
            connection.executescript(schema)
        return self._db

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

    def raw_records(self, table: str) -> dict[str, str]:
        """Every stored record of ``table`` as its text, by key, without parsing any of them.

        ``table`` is "runs", "decisions" or "theses". A decision's key is
        "<run id>/<finding id>". A record that no longer validates is still a record, and
        is returned too. The other columns of a row are in :meth:`raw_rows`.
        """
        if table not in RECORD_KEYS:
            raise ValueError(f"no table {table!r} in the record")
        if not self._has_table(table):
            return {}
        rows = self._db.query(f"SELECT {RECORD_KEYS[table]}, record FROM {table}")
        return {key: record for key, record in rows}

    def _has_table(self, table: str) -> bool:
        """True when the file has ``table``; a record written before a version lacks its tables."""
        rows = self._db.query(
            "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = ?", (table,)
        )
        return bool(rows)

    def raw_rows(self, table: str) -> dict[str, dict[str, object]]:
        """Every row of ``table`` with every one of its columns, by key, without parsing any.

        ``table`` is "runs", "decisions" or "theses"; keys are as :meth:`raw_records` gives
        them. Each row maps column name to stored value, in the table's column order. This is
        what a restored backup is compared by: besides the record text, a row holds columns
        the app reads on their own (a run's ``thesis_id``, which :meth:`runs_of_thesis`
        selects by, and the times lists are ordered by).
        """
        if table not in RECORD_KEYS:
            raise ValueError(f"no table {table!r} in the record")
        columns = [row[1] for row in self._db.query(f"PRAGMA table_info({table})")]
        if not columns:  # a record written before the version that added the table
            return {}
        # ``table`` is one of the fixed names of RECORD_KEYS; the column names come from the
        # file's own schema (a backup may be any file), so they are quoted as SQL identifiers.
        selected = ", ".join('"' + column.replace('"', '""') + '"' for column in columns)
        rows = self._db.query(f"SELECT {RECORD_KEYS[table]}, {selected} FROM {table}")
        return {row[0]: dict(zip(columns, row[1:], strict=True)) for row in rows}

    def unreadable(self) -> list[str]:
        """Stored records that no longer validate against the current models, named.

        "run <id>", "the decision on <run id>/<finding id>" or "thesis <id>", sorted
        within each kind. The app skips these with a warning; this is how to see them.
        """
        kinds: tuple[tuple[str, str, type[BaseModel]], ...] = (
            ("runs", "run", Run),
            ("decisions", "the decision on", Decision),
            ("theses", "thesis", Thesis),
        )
        return [
            f"{word} {key}"
            for table, word, model in kinds
            for key, record in sorted(self.raw_records(table).items())
            if _parse(model, key, record) is None
        ]

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
    """Disposable: document text once per content hash, parsed filings and their tags by accession.

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

    def extend(self, schema: str) -> _Database:
        """Create a feature's own disposable tables if they are missing; the shared database.

        For state that can be lost without loss (the watcher's heartbeat and the time of
        each company's last check, ``app.watch.store.WatchStatus``).
        """
        with self._db.transaction() as connection:
            connection.executescript(schema)
        return self._db

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

    def put_tagged(self, accession: str, reader_version: str, report: str) -> None:
        """Keep what ``reader_version`` read from the tags of filing ``accession``, as JSON text."""
        with self._db.transaction(durable=False) as connection:
            connection.execute(
                "INSERT OR REPLACE INTO tagged (accession, reader_version, report) "
                "VALUES (?, ?, ?)",
                (accession, reader_version, report),
            )

    def get_tagged(self, accession: str, reader_version: str) -> str | None:
        """What ``reader_version`` read from the tags of filing ``accession``, if it is kept."""
        rows = self._db.query(
            "SELECT report FROM tagged WHERE accession = ? AND reader_version = ?",
            (accession, reader_version),
        )
        return rows[0][0] if rows else None

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


def _fact_row(cik: int, concept: str, unit: str, raw: object) -> tuple[object, ...] | None:
    """One raw company-facts entry as a ``facts`` row; None when a required field is unusable.

    Required: ``end``, ``val`` (a finite number), ``accn``, ``form`` and ``filed``, as
    :func:`app.core.facts.parse_fact` requires them; ``start``, ``fy``, ``fp`` and
    ``frame`` are kept when present.
    """
    if not isinstance(raw, dict):
        return None
    val = raw.get("val")
    if isinstance(val, bool) or not isinstance(val, int | float) or not math.isfinite(val):
        return None
    texts = [raw.get(name) for name in ("end", "accn", "form", "filed")]
    if not all(isinstance(text, str) and text for text in texts):
        return None
    start = raw.get("start")
    fy = raw.get("fy")
    fp = raw.get("fp")
    frame = raw.get("frame")
    return (
        cik,
        concept,
        unit,
        start if isinstance(start, str) else None,
        texts[0],
        float(val),
        texts[1],
        texts[2],
        texts[3],
        fy if isinstance(fy, int) and not isinstance(fy, bool) else None,
        fp if isinstance(fp, str) else None,
        frame if isinstance(frame, str) else None,
    )


def _fact_rows(cik: int, payload: dict[str, object]) -> tuple[list[tuple[object, ...]], int]:
    """Every us-gaap fact of a company-facts body as rows, and how many entries were unusable."""
    facts = payload.get("facts")
    gaap = facts.get(GAAP) if isinstance(facts, dict) else None
    rows: list[tuple[object, ...]] = []
    skipped = 0
    if not isinstance(gaap, dict):
        return rows, skipped
    for concept, entry in gaap.items():
        units = entry.get("units") if isinstance(entry, dict) else None
        if not isinstance(units, dict):
            continue
        for unit, entries in units.items():
            if not isinstance(entries, list):
                continue
            for raw in entries:
                row = _fact_row(cik, str(concept), str(unit), raw)
                if row is None:
                    skipped += 1
                else:
                    rows.append(row)
    return rows, skipped


class FactStore:
    """Disposable: every us-gaap fact of each loaded company, and the companies themselves.

    Thread-safe. ``path`` may be ``":memory:"``. A company is replaced whole when
    it is loaded again with different facts; loading the same body again (same
    SHA-256) changes nothing but its profile.
    """

    def __init__(self, path: Path | str = MEMORY) -> None:
        """Open (creating if needed) the fact store at ``path``."""
        self._db = _Database(path, FACTS_SCHEMA)
        self.path = self._db.path

    def close(self) -> None:
        """Close the database connection."""
        self._db.close()

    def save_company(
        self,
        profile: CompanyProfile,
        payload: dict[str, object],
        payload_sha256: str,
        loaded_at: datetime,
    ) -> StoredCompany:
        """Keep every us-gaap fact of ``payload`` under ``profile.cik``; return what is stored.

        ``payload_sha256`` identifies the body (:func:`app.services.numbers.content_hash`):
        when the company is already stored with it, the facts are left as they are.
        Entries without a usable end, value, accession, form or filing date are not
        stored and are counted in ``skipped``.
        """
        known = self.company(profile.cik)
        with self._db.transaction() as connection:
            if known is None or known.payload_sha256 != payload_sha256:
                rows, skipped = _fact_rows(profile.cik, payload)
                connection.execute("DELETE FROM facts WHERE cik = ?", (profile.cik,))
                connection.executemany(
                    "INSERT INTO facts (cik, concept, unit, start, end, value, accession, form, "
                    "filed, fy, fp, frame) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                    rows,
                )
                count, stamp = len(rows), loaded_at.isoformat()
            else:
                count, skipped, stamp = known.facts, known.skipped, known.loaded_at
            connection.execute(
                "INSERT OR REPLACE INTO companies (cik, ticker, name, sic, sic_description, "
                "facts, skipped, payload_sha256, loaded_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    profile.cik,
                    profile.ticker,
                    profile.name,
                    profile.sic,
                    profile.sic_description,
                    count,
                    skipped,
                    payload_sha256,
                    stamp,
                ),
            )
        stored = self.company(profile.cik)
        assert stored is not None
        return stored

    def company(self, cik: int) -> StoredCompany | None:
        """The stored company with ``cik``, or None."""
        rows = self._db.query(
            "SELECT cik, ticker, name, sic, sic_description, facts, skipped, payload_sha256, "
            "loaded_at FROM companies WHERE cik = ?",
            (cik,),
        )
        return _stored_company(rows[0]) if rows else None

    def company_by_ticker(self, ticker: str) -> StoredCompany | None:
        """The stored company whose ticker is ``ticker`` (any case), or None."""
        rows = self._db.query(
            "SELECT cik, ticker, name, sic, sic_description, facts, skipped, payload_sha256, "
            "loaded_at FROM companies WHERE upper(ticker) = upper(?) ORDER BY cik LIMIT 1",
            (ticker,),
        )
        return _stored_company(rows[0]) if rows else None

    def companies(self) -> list[StoredCompany]:
        """Every stored company, by ticker."""
        rows = self._db.query(
            "SELECT cik, ticker, name, sic, sic_description, facts, skipped, payload_sha256, "
            "loaded_at FROM companies ORDER BY ticker, cik"
        )
        return [_stored_company(row) for row in rows]

    def payload(self, cik: int) -> dict[str, object] | None:
        """The stored facts of ``cik`` in EDGAR's company-facts shape (us-gaap only), or None.

        Entries keep EDGAR's field names (``start``, ``end``, ``val``, ``accn``, ``form``,
        ``filed``, and ``fy``, ``fp``, ``frame`` when known), in the order stored.
        """
        company = self.company(cik)
        if company is None:
            return None
        rows = self._db.query(
            "SELECT concept, unit, start, end, value, accession, form, filed, fy, fp, frame "
            "FROM facts WHERE cik = ? ORDER BY rowid",
            (cik,),
        )
        gaap: dict[str, dict[str, dict[str, list[dict[str, object]]]]] = {}
        for concept, unit, start, end, value, accession, form, filed, fy, fp, frame in rows:
            entry: dict[str, object] = {}
            if start is not None:
                entry["start"] = start
            entry.update(end=end, val=value, accn=accession, form=form, filed=filed)
            for name, extra in (("fy", fy), ("fp", fp), ("frame", frame)):
                if extra is not None:
                    entry[name] = extra
            units = gaap.setdefault(concept, {"units": {}})["units"]
            units.setdefault(unit, []).append(entry)
        return {"cik": cik, "entityName": company.name, "facts": {GAAP: gaap}}

    def filings(self, cik: int, forms: Sequence[str] = ()) -> list[StoredFiling]:
        """Every filing a stored fact of ``cik`` came from, oldest first; ``forms`` filters."""
        rows = self._db.query(
            "SELECT DISTINCT accession, form, filed FROM facts WHERE cik = ? "
            "ORDER BY filed, accession, form",
            (cik,),
        )
        return [
            StoredFiling(accession=accession, form=form, filed=filed)
            for accession, form, filed in rows
            if not forms or form in forms
        ]

    def fact_count(self, cik: int) -> int:
        """How many facts of ``cik`` are stored."""
        return int(self._db.query("SELECT COUNT(*) FROM facts WHERE cik = ?", (cik,))[0][0])


def _stored_company(row: tuple) -> StoredCompany:
    cik, ticker, name, sic, description, facts, skipped, digest, loaded_at = row
    return StoredCompany(
        cik=cik,
        ticker=ticker,
        name=name,
        sic=sic,
        sic_description=description,
        facts=facts,
        skipped=skipped,
        payload_sha256=digest,
        loaded_at=loaded_at,
    )
