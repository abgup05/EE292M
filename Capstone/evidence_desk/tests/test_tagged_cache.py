"""What was read from a filing's tags is kept, so a second run does not fetch the filing again.

A run that asks for tagged figures fetched the newest annual and quarterly report a
second time on every run, because the filing cache keeps a filing's parsed text and
the tags are only in the HTML: about 0.3 s of a 0.8 s run on a warm cache
(``docs/speed/live-timing-v10.txt``). The breakdowns read from a filing are now kept
in the disposable cache, by accession and by the version of the code that read them.
"""

from __future__ import annotations

from pathlib import Path

from app.core.ports import SourceError
from app.engines.extractive import ExtractiveAnalyst
from app.services import tagged_figures as service
from app.services.examples import EXAMPLE_THESIS
from app.services.tagged_figures import READER_VERSION, load_tagged_figures, reader_version
from app.services.thesis_run import execute_run, new_run
from app.store import FilingCache, Store
from tests.fakes import FY_2026, NVIDIA, Q2_2027, FakeFilings

REFS = [Q2_2027, FY_2026]


def test_the_cache_keeps_a_report_by_accession_and_reader_version(tmp_path: Path) -> None:
    cache = FilingCache(tmp_path / "cache.sqlite")
    assert cache.get_tagged("0001045810-26-000021", "v1") is None
    cache.put_tagged("0001045810-26-000021", "v1", '{"a": 1}')
    assert cache.get_tagged("0001045810-26-000021", "v1") == '{"a": 1}'
    assert cache.get_tagged("0001045810-26-000021", "v2") is None
    assert cache.get_tagged("0001045810-26-000075", "v1") is None
    cache.put_tagged("0001045810-26-000021", "v1", '{"a": 2}')
    assert cache.get_tagged("0001045810-26-000021", "v1") == '{"a": 2}'
    cache.close()
    assert FilingCache(tmp_path / "cache.sqlite").get_tagged("0001045810-26-000021", "v1") == (
        '{"a": 2}'
    )


def test_a_second_call_fetches_nothing_and_gives_the_same_figures() -> None:
    filings = FakeFilings.nvidia(*REFS)
    cache = FilingCache()
    first = load_tagged_figures(NVIDIA, filings, REFS, cache=cache)
    assert len(filings.fetched) == 2 and len(first.figures) == 40
    second = load_tagged_figures(NVIDIA, filings, REFS, cache=cache)
    assert len(filings.fetched) == 2, "the two filings were fetched again"
    assert second.figures == first.figures
    assert second.notes == first.notes and second.errors == first.errors == []


def test_without_a_cache_every_call_fetches() -> None:
    filings = FakeFilings.nvidia(*REFS)
    load_tagged_figures(NVIDIA, filings, REFS)
    load_tagged_figures(NVIDIA, filings, REFS)
    assert len(filings.fetched) == 4


def test_a_failure_is_not_kept_so_the_next_run_tries_again() -> None:
    filings = FakeFilings.nvidia(*REFS)
    document = filings.documents[FY_2026.url]
    filings.documents[FY_2026.url] = SourceError("EDGAR answered HTTP 503 for the document")
    cache = FilingCache()
    failed = load_tagged_figures(NVIDIA, filings, REFS, cache=cache)
    assert len(failed.errors) == 1 and "HTTP 503" in failed.errors[0]
    filings.documents[FY_2026.url] = document
    recovered = load_tagged_figures(NVIDIA, filings, REFS, cache=cache)
    assert recovered.errors == [] and len(recovered.figures) == 40
    # The quarterly report was kept the first time: only the annual report is fetched again.
    assert filings.fetched.count(Q2_2027.url) == 1 and filings.fetched.count(FY_2026.url) == 2


def test_a_kept_report_this_version_cannot_read_is_read_again() -> None:
    filings = FakeFilings.nvidia(*REFS)
    cache = FilingCache()
    cache.put_tagged(FY_2026.accession, READER_VERSION, '{"not": "a report"}')
    result = load_tagged_figures(NVIDIA, filings, REFS, cache=cache)
    assert result.errors == [] and len(result.figures) == 40
    assert FY_2026.url in filings.fetched


def test_a_change_to_the_reader_is_a_new_version(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    """What an older reader kept is not used by a newer one."""
    assert reader_version() == READER_VERSION and len(READER_VERSION) >= 16
    filings = FakeFilings.nvidia(*REFS)
    cache = FilingCache()
    load_tagged_figures(NVIDIA, filings, REFS, cache=cache)
    monkeypatch.setattr(service, "READER_VERSION", "another-reader")
    load_tagged_figures(NVIDIA, filings, REFS, cache=cache)
    assert len(filings.fetched) == 4


def test_a_second_run_with_the_same_cache_fetches_no_filing_at_all(tmp_path: Path) -> None:
    """The whole point, at the level of a run: text and tags both come from the cache."""
    filings = FakeFilings.nvidia(*REFS)  # the two filings this fake holds as recorded
    cache = FilingCache(tmp_path / "cache.sqlite")
    thesis = EXAMPLE_THESIS.model_copy(deep=True, update={"tagged_figures": True, "filings": 2})

    def run_once(name: str):  # type: ignore[no-untyped-def]
        store = Store(tmp_path / f"{name}.sqlite")
        return execute_run(
            new_run(thesis), store, filings=filings, analyst=ExtractiveAnalyst(), cache=cache
        )

    first = run_once("first")
    fetched_by_first = len(filings.fetched)
    assert first.coverage.tagged_figures_offered == 40
    assert fetched_by_first == 4, "two filings for their text, and again for their tags"
    second = run_once("second")
    again = [url.rsplit("/", 1)[-1] for url in filings.fetched[fetched_by_first:]]
    assert again == [], f"the second run fetched {again}"
    tagged_first = [m for m in first.metrics if m.id.startswith("tagged:")]
    tagged_second = [m for m in second.metrics if m.id.startswith("tagged:")]
    assert tagged_second == tagged_first and len(tagged_second) == 40
