"""SQLite persistence for runs and the exact extracted text of each source.

Source text is stored separately from the run record so the API can return
the record without exposing more filing text than the cited excerpts, while
verification can still read the full stored text.
"""

from __future__ import annotations

import logging
import sqlite3
import threading
from contextlib import closing
from pathlib import Path

from pydantic import ValidationError

from ed_v2.core.models import Run

logger = logging.getLogger(__name__)

SCHEMA = """
CREATE TABLE IF NOT EXISTS runs (
    id TEXT PRIMARY KEY,
    started_at TEXT NOT NULL,
    record TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS source_texts (
    run_id TEXT NOT NULL,
    source_id TEXT NOT NULL,
    text TEXT NOT NULL,
    PRIMARY KEY (run_id, source_id)
);
"""


class Store:
    """Thread-safe access to one SQLite file; each call opens a short connection.

    Writes are serialised by a lock; reads rely on SQLite's WAL mode.
    """

    def __init__(self, path: Path | str) -> None:
        """Open (creating if needed) the database at ``path`` and its tables."""
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()
        with self._lock, closing(self._connect()) as connection, connection:
            connection.executescript(SCHEMA)

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.path, timeout=30)
        connection.execute("PRAGMA journal_mode=WAL")
        return connection

    @staticmethod
    def _parse(run_id: str, record: str) -> Run | None:
        """The run in ``record``, or None (with a warning) if it no longer validates."""
        try:
            return Run.model_validate_json(record)
        except ValidationError as error:
            logger.warning(
                "Skipping stored run %s: its record does not match the current format "
                "(%d validation error(s)).",
                run_id,
                error.error_count(),
            )
            return None

    def save_run(self, run: Run) -> None:
        """Insert or replace the full run record."""
        with self._lock, closing(self._connect()) as connection, connection:
            connection.execute(
                "INSERT OR REPLACE INTO runs (id, started_at, record) VALUES (?, ?, ?)",
                (run.id, run.started_at.isoformat(), run.model_dump_json()),
            )

    def get_run(self, run_id: str) -> Run | None:
        """The run with ``run_id``; None if absent or stored in an outdated format."""
        with closing(self._connect()) as connection:
            row = connection.execute("SELECT record FROM runs WHERE id = ?", (run_id,)).fetchone()
        return self._parse(run_id, row[0]) if row else None

    def list_runs(self, limit: int = 50) -> list[Run]:
        """Up to ``limit`` runs, most recent first; outdated records are skipped and logged."""
        with closing(self._connect()) as connection:
            rows = connection.execute(
                "SELECT id, record FROM runs ORDER BY started_at DESC LIMIT ?", (limit,)
            ).fetchall()
        runs = (self._parse(run_id, record) for run_id, record in rows)
        return [run for run in runs if run is not None]

    def save_source_text(self, run_id: str, source_id: str, text: str) -> None:
        """Insert or replace the exact stored text of one source of one run."""
        with self._lock, closing(self._connect()) as connection, connection:
            connection.execute(
                "INSERT OR REPLACE INTO source_texts (run_id, source_id, text) VALUES (?, ?, ?)",
                (run_id, source_id, text),
            )

    def get_source_texts(self, run_id: str) -> dict[str, str]:
        """Every stored source text of ``run_id``, by source id."""
        with closing(self._connect()) as connection:
            rows = connection.execute(
                "SELECT source_id, text FROM source_texts WHERE run_id = ?", (run_id,)
            ).fetchall()
        return {source_id: text for source_id, text in rows}
