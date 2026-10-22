"""SQLite persistence for runs and the exact extracted text of each source.

Source text is stored separately from the run record so the API can return
the record without exposing more page text than the cited excerpts, while
verification can still read the full stored text.
"""

from __future__ import annotations

import sqlite3
import threading
from pathlib import Path

from app.models import Run

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
    """Thread-safe access to one SQLite file; each call opens a short connection."""

    def __init__(self, path: Path | str) -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()
        with self._connect() as connection:
            connection.executescript(SCHEMA)

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.path, timeout=30)
        connection.execute("PRAGMA journal_mode=WAL")
        return connection

    def save_run(self, run: Run) -> None:
        """Insert or replace the full run record."""
        with self._lock, self._connect() as connection:
            connection.execute(
                "INSERT OR REPLACE INTO runs (id, started_at, record) VALUES (?, ?, ?)",
                (run.id, run.started_at.isoformat(), run.model_dump_json()),
            )

    def get_run(self, run_id: str) -> Run | None:
        with self._connect() as connection:
            row = connection.execute("SELECT record FROM runs WHERE id = ?", (run_id,)).fetchone()
        return Run.model_validate_json(row[0]) if row else None

    def list_runs(self, limit: int = 50) -> list[Run]:
        """Most recent runs first."""
        with self._connect() as connection:
            rows = connection.execute(
                "SELECT record FROM runs ORDER BY started_at DESC LIMIT ?", (limit,)
            ).fetchall()
        return [Run.model_validate_json(row[0]) for row in rows]

    def save_source_text(self, run_id: str, source_id: str, text: str) -> None:
        with self._lock, self._connect() as connection:
            connection.execute(
                "INSERT OR REPLACE INTO source_texts (run_id, source_id, text) VALUES (?, ?, ?)",
                (run_id, source_id, text),
            )

    def get_source_texts(self, run_id: str) -> dict[str, str]:
        with self._connect() as connection:
            rows = connection.execute(
                "SELECT source_id, text FROM source_texts WHERE run_id = ?", (run_id,)
            ).fetchall()
        return {source_id: text for source_id, text in rows}
