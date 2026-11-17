"""The command line: the same use case as the API, run synchronously, writing its record."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from app import cli
from app.core.models import Run, RunStatus
from app.core.policy import STATUS_NOTES, VERDICT_LABELS
from app.services.examples import EXAMPLE_THESIS
from app.store import Store
from tests.fakes import Q1_2027, Q2_2027, FakeFilings, filing_html

SENTENCE = "Data Center revenue grew 56% from a year ago, driven by demand for Blackwell."
CLAIM = "Data center revenue is still growing year over year."
DECISION = "Whether to keep an overweight position in NVIDIA into the next earnings report"


def run_cli(argv: list[str], tmp_path: Path, filings: FakeFilings) -> tuple[int, Store]:
    store = Store(tmp_path / "runs.sqlite")
    code = cli.main(argv, filings=filings, store=store)
    return code, store


def written(out: Path) -> Run:
    [record] = out.glob("run-*.json")
    assert record.with_suffix(".md").exists()
    return Run.model_validate_json(record.read_text())


def test_example_runs_the_nvidia_thesis_and_writes_its_record(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    out = tmp_path / "results"
    code, store = run_cli(
        ["example", "--engine", "extractive", "--out", str(out)],
        tmp_path,
        FakeFilings.nvidia(Q2_2027),
    )
    assert code == 0
    run = written(out)
    assert run.inputs == EXAMPLE_THESIS and store.get_run(run.id) == run
    assert run.status == RunStatus.partial and run.engine == "extractive"
    printed = capsys.readouterr().out
    assert f"{run.id}: PARTIAL" in printed and STATUS_NOTES[RunStatus.partial] in printed
    for claim in run.claims:
        assert claim.verdict is not None
        assert VERDICT_LABELS[claim.verdict] in printed and claim.text in printed
    assert cli.coverage_sentence(run) in printed
    markdown = (out / f"{run.id}.md").read_text()
    assert markdown.startswith("# Evidence Desk brief: NVIDIA CORP (NVDA)")


def test_run_takes_the_thesis_from_its_arguments(tmp_path: Path) -> None:
    out = tmp_path / "results"
    argv = [
        "run",
        "--ticker",
        "nvda",
        "--decision",
        DECISION,
        "--claim",
        CLAIM,
        "--claim",
        "Gross margin is expanding this year.",
        "--filings",
        "1",
        "--engine",
        "extractive",
        "--out",
        str(out),
    ]
    code, _ = run_cli(argv, tmp_path, FakeFilings.synthetic(filing_html(SENTENCE)))
    assert code == 0
    run = written(out)
    assert run.inputs.ticker == "NVDA" and run.inputs.filings == 1
    assert [claim.text for claim in run.claims] == [CLAIM, "Gross margin is expanding this year."]
    assert json.loads((out / f"{run.id}.json").read_text())["id"] == run.id


def test_coverage_sentence_counts_what_the_backend_counted(tmp_path: Path) -> None:
    out = tmp_path / "results"
    argv = ["run", "--ticker", "NVDA", "--decision", DECISION, "--claim", CLAIM]
    argv += ["--filings", "1", "--engine", "extractive", "--out", str(out)]
    run_cli(argv, tmp_path, FakeFilings.synthetic(filing_html(SENTENCE)))
    run = written(out)
    assert cli.coverage_sentence(run) == (
        "Read 1 of 1 source(s); 1 of 1 claim(s) have verified evidence; "
        "1 finding(s) verified and 0 withheld; 1 of 1 quote(s) verified."
    )


def test_a_failed_run_exits_non_zero_and_still_writes_its_record(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    out = tmp_path / "results"
    argv = ["run", "--ticker", "NVDA", "--decision", DECISION, "--claim", CLAIM]
    argv += ["--engine", "extractive", "--out", str(out)]
    code, _ = run_cli(argv, tmp_path, FakeFilings.nvidia(Q1_2027))
    assert code == 1
    assert written(out).status == RunStatus.failed
    assert "FAILED" in capsys.readouterr().out


@pytest.mark.parametrize(
    ("argv", "message"),
    [
        (["run", "--ticker", "nv da$", "--decision", DECISION, "--claim", CLAIM], "ticker:"),
        (["run", "--ticker", "NVDA", "--decision", DECISION, "--claim", "short"], "claims:"),
        (["run", "--ticker", "ZZZZ", "--decision", DECISION, "--claim", CLAIM], "not in SEC"),
    ],
)
def test_an_invalid_thesis_exits_with_a_usage_error(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], argv: list[str], message: str
) -> None:
    code, store = run_cli([*argv, "--engine", "extractive"], tmp_path, FakeFilings.nvidia())
    assert code == 2
    assert message in capsys.readouterr().err
    assert store.list_runs() == []


def test_the_claude_engine_needs_a_key(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    code, _ = run_cli(["example", "--engine", "claude"], tmp_path, FakeFilings.nvidia())
    assert code == 2
    assert "ANTHROPIC_API_KEY" in capsys.readouterr().err
