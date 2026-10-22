"""Run persistence: records and stored source text survive a round trip."""

from datetime import UTC, datetime
from pathlib import Path

from app.models import ResearchRequest, Run, RunStatus
from app.store import Store

REQUEST = ResearchRequest(
    question="What risks should an organization examine before using generative AI?",
    decision="Whether to investigate a limited internal pilot",
)


def test_run_round_trip(tmp_path: Path) -> None:
    store = Store(tmp_path / "runs.sqlite")
    run = Run(
        id="run-1",
        inputs=REQUEST,
        status=RunStatus.running,
        started_at=datetime(2026, 10, 21, 12, 0, tzinfo=UTC),
    )
    store.save_run(run)
    loaded = store.get_run("run-1")
    assert loaded == run
    assert store.get_run("run-missing") is None


def test_save_run_overwrites_previous_version(tmp_path: Path) -> None:
    store = Store(tmp_path / "runs.sqlite")
    run = Run(
        id="run-1",
        inputs=REQUEST,
        status=RunStatus.running,
        started_at=datetime(2026, 10, 21, 12, 0, tzinfo=UTC),
    )
    store.save_run(run)
    store.save_run(run.model_copy(update={"status": RunStatus.partial}))
    assert store.get_run("run-1").status == RunStatus.partial
    assert [r.id for r in store.list_runs()] == ["run-1"]


def test_source_text_round_trip(tmp_path: Path) -> None:
    store = Store(tmp_path / "runs.sqlite")
    store.save_source_text("run-1", "src-1", "Exact stored text.")
    store.save_source_text("run-1", "src-2", "Other text.")
    assert store.get_source_texts("run-1") == {
        "src-1": "Exact stored text.",
        "src-2": "Other text.",
    }
    assert store.get_source_texts("run-2") == {}
