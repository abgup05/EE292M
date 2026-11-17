"""The filing cache: text once per content hash, a filing parsed once, and nothing to lose.

Deleting the cache must change nothing a run records except when its filings
were fetched; a cached filing must not be fetched again; and a change to the
parser must never let text parsed by the old parser be quoted.
"""

from __future__ import annotations

import logging
import shutil
import sqlite3
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest

from app.core.models import ExtractionStatus, Run
from app.engines.extractive import ExtractiveAnalyst
from app.services import ingest as ingest_module
from app.services.examples import EXAMPLE_THESIS
from app.services.thesis_run import execute_run, new_run
from app.sources import filing as filing_parser
from app.store import FilingCache, Store, text_hash
from tests.fakes import FY_2026, Q1_2027, Q2_2027, FakeFilings, FakePages, ManualClock

TEXT = "Item 2. MD&A\nData Center revenue grew 56% from a year ago."
WHEN = datetime(2026, 11, 17, 11, 0, tzinfo=UTC)


# The cache on its own


def test_text_is_kept_once_under_its_content_hash() -> None:
    cache = FilingCache()
    cache.put_text(text_hash(TEXT), TEXT)
    cache.put_text(text_hash(TEXT), TEXT)
    assert cache.get_text(text_hash(TEXT)) == TEXT
    assert cache.get_text(text_hash("other")) is None


def test_text_under_the_wrong_hash_is_refused() -> None:
    with pytest.raises(ValueError, match="SHA-256"):
        FilingCache().put_text(text_hash("something else"), TEXT)


def test_cached_text_that_no_longer_matches_its_hash_is_not_returned(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    path = tmp_path / "filings.sqlite"
    cache = FilingCache(path)
    cache.put_text(text_hash(TEXT), TEXT)
    with sqlite3.connect(path) as connection:
        connection.execute("UPDATE texts SET text = ?", (TEXT.replace("56%", "65%"),))
    connection.close()
    with caplog.at_level(logging.WARNING, logger="app.store"):
        assert cache.get_text(text_hash(TEXT)) is None
    assert "does not match its hash" in caplog.text


def test_a_filing_is_found_by_accession_and_parser_version_only() -> None:
    cache = FilingCache()
    sections = [("Item 2. MD&A", 13, 45)]
    cache.remember_filing(
        Q2_2027.accession,
        "parser-a",
        content_hash=text_hash(TEXT),
        publisher="SEC EDGAR",
        sections=sections,
        retrieved_at=WHEN,
    )
    found = cache.lookup_filing(Q2_2027.accession, "parser-a")
    assert found is not None
    assert (found.content_hash, found.publisher) == (text_hash(TEXT), "SEC EDGAR")
    assert found.sections == (("Item 2. MD&A", 13, 45),) and found.retrieved_at == WHEN
    assert cache.lookup_filing(Q2_2027.accession, "parser-b") is None
    assert cache.lookup_filing(Q1_2027.accession, "parser-a") is None


def test_the_parser_version_changes_when_the_parser_source_does(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    copy = tmp_path / "filing.py"
    copy.write_bytes(Path(filing_parser.__file__).read_bytes())
    monkeypatch.setattr(filing_parser, "__file__", str(copy))
    before = ingest_module.parser_version()
    assert before == ingest_module.PARSER_VERSION
    copy.write_text(copy.read_text() + "\n# a one-line edit\n")
    assert ingest_module.parser_version() != before


# The cache in a run


def _run(store: Store, cache: FilingCache, filings: FakeFilings) -> Run:
    return execute_run(
        new_run(EXAMPLE_THESIS.model_copy(deep=True)),
        store,
        filings=filings,
        analyst=ExtractiveAnalyst(),
        fetch_page=FakePages({}),
        clock=ManualClock(),
        cache=cache,
    )


def _without_times(run: Run) -> dict[str, Any]:
    """The record without its id, its timestamps and when each source was retrieved."""
    record = run.model_dump(mode="json", exclude={"id", "started_at", "finished_at"})
    for source in record["sources"]:
        source.pop("retrieved_at")
    return record


def test_deleting_the_cache_between_two_runs_loses_nothing(tmp_path: Path) -> None:
    store = Store(tmp_path / "record" / "record.sqlite")
    cache_dir = tmp_path / "cache"
    cache = FilingCache(cache_dir / "filings.sqlite")
    first = _run(store, cache, FakeFilings.nvidia(Q2_2027, FY_2026))
    cache.close()
    shutil.rmtree(cache_dir)
    cache = FilingCache(cache_dir / "filings.sqlite")
    filings = FakeFilings.nvidia(Q2_2027, FY_2026)
    second = _run(store, cache, filings)
    assert filings.fetched == [Q2_2027.url, FY_2026.url], "an empty cache fetches every filing"
    assert first.evidence and _without_times(second) == _without_times(first)
    assert cache.source_texts(second) == cache.source_texts(first)
    assert set(cache.source_texts(second)) == {"s1", "s2"}


def test_a_cached_filing_is_not_fetched_again_and_the_run_says_so(tmp_path: Path) -> None:
    store = Store(tmp_path / "record.sqlite")
    cache = FilingCache(tmp_path / "filings.sqlite")
    first = _run(store, cache, FakeFilings.nvidia(Q2_2027, FY_2026))
    assert not any("local cache" in line for line in first.coverage_limits)
    filings = FakeFilings.nvidia(Q2_2027, FY_2026)
    second = _run(store, cache, filings)
    assert filings.fetched == []
    note = ingest_module.CACHE_NOTE.format(cached=2, total=2)
    assert note == (
        "2 of 2 filings were read from the local cache; for those, EDGAR was asked only "
        "for the filing list."
    )
    assert note in second.coverage_limits
    first_record, second_record = _without_times(first), _without_times(second)
    second_record["coverage_limits"].remove(note)
    assert second_record == first_record
    # The source says when EDGAR sent the filing, not when the cache was read.
    fetched_at = [source.retrieved_at for source in first.sources[:2]]
    assert [source.retrieved_at for source in second.sources[:2]] == fetched_at


def test_only_the_filings_not_cached_are_fetched(tmp_path: Path) -> None:
    store = Store(tmp_path / "record.sqlite")
    cache = FilingCache(tmp_path / "filings.sqlite")
    _run(store, cache, FakeFilings.nvidia(Q2_2027))
    filings = FakeFilings.nvidia(Q2_2027, FY_2026)
    run = _run(store, cache, filings)
    assert filings.fetched == [FY_2026.url]
    assert ingest_module.CACHE_NOTE.format(cached=1, total=2) in run.coverage_limits


def test_a_failed_filing_is_not_cached(tmp_path: Path) -> None:
    store = Store(tmp_path / "record.sqlite")
    cache = FilingCache(tmp_path / "filings.sqlite")
    _run(store, cache, FakeFilings.nvidia(Q2_2027, Q1_2027))  # Q1 was not recorded: HTTP 404
    filings = FakeFilings.nvidia(Q2_2027, Q1_2027)
    run = _run(store, cache, filings)
    assert filings.fetched == [Q1_2027.url]
    assert run.sources[1].extraction_status == ExtractionStatus.failed


def test_a_filing_cached_by_another_parser_version_is_parsed_again(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    store = Store(tmp_path / "record.sqlite")
    cache = FilingCache(tmp_path / "filings.sqlite")
    real_version = ingest_module.PARSER_VERSION
    monkeypatch.setattr(ingest_module, "PARSER_VERSION", "an-older-parser")
    _run(store, cache, FakeFilings.nvidia(Q2_2027))
    monkeypatch.setattr(ingest_module, "PARSER_VERSION", real_version)
    filings = FakeFilings.nvidia(Q2_2027)
    run = _run(store, cache, filings)
    assert filings.fetched == [Q2_2027.url]
    assert not any("local cache" in line for line in run.coverage_limits)


def test_a_filing_indexed_without_its_text_is_fetched_again(tmp_path: Path) -> None:
    store = Store(tmp_path / "record.sqlite")
    path = tmp_path / "filings.sqlite"
    cache = FilingCache(path)
    _run(store, cache, FakeFilings.nvidia(Q2_2027))
    with sqlite3.connect(path) as connection:
        connection.execute("DELETE FROM texts")
    connection.close()
    filings = FakeFilings.nvidia(Q2_2027)
    run = _run(store, cache, filings)
    assert filings.fetched == [Q2_2027.url]
    assert set(cache.source_texts(run)) == {"s1"}


def test_a_run_without_a_cache_keeps_its_text_in_memory(tmp_path: Path) -> None:
    run = execute_run(
        new_run(EXAMPLE_THESIS.model_copy(deep=True)),
        Store(tmp_path / "record.sqlite"),
        filings=FakeFilings.nvidia(Q2_2027),
        analyst=ExtractiveAnalyst(),
        fetch_page=FakePages({}),
        clock=ManualClock(),
    )
    assert run.evidence, "the quotes were verified against text that was never written to disk"
    written = {path.name for path in tmp_path.iterdir()}
    assert written <= {"record.sqlite", "record.sqlite-wal", "record.sqlite-shm"}
