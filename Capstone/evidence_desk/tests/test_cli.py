"""The command line: the same use case as the API, run synchronously, writing its record."""

from __future__ import annotations

import json
import re
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
        "Read 1 of 1 source(s); 1 of 1 claim(s) have verified excerpts or figures; "
        "1 finding(s) verified and 0 withheld; 1 of 1 quote(s) found word for word, "
        "0 rejected; 1 kept as evidence."
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


# Replaying a cassette


def cassette_argv(cassette: Path, out: Path) -> list[str]:
    return [
        "run",
        "--ticker",
        "NVDA",
        "--decision",
        DECISION,
        "--claim",
        CLAIM,
        "--filings",
        "1",
        "--engine",
        "cassette",
        "--cassette",
        str(cassette),
        "--out",
        str(out),
    ]


def answer(pending: dict) -> dict:
    """Answer one pending request as a model would, from what the request itself contains."""
    if pending["step"] == "plan":
        return {
            "claims": [{"claim_number": 1, "queries": ["Data Center revenue", "revenue decline"]}]
        }
    if pending["step"] == "assess":
        ids = re.findall(r'<passage id="([^"]+)"[^>]*>([^<]*)</passage>', pending["user"])
        [passage_id] = [pid for pid, text in ids if SENTENCE in text]
        return {
            "findings": [
                {
                    "statement": "Data Center revenue grew 56% from a year ago.",
                    "stance": "supports",
                    "confidence": "high",
                    "rationale": "The filing reports year-over-year growth.",
                    "quotes": [{"passage_id": passage_id, "text": SENTENCE}],
                    "figure_ids": [],
                }
            ],
            "rationale": "The MD&A reports growth.",
            "unknowns": [],
        }
    if pending["step"] == "check":
        numbers = re.findall(r'<finding number="(\d+)"', pending["user"])
        return {
            "judgements": [
                {"finding_number": int(n), "verdict": "supported", "reason": "The excerpt says so."}
                for n in numbers
            ]
        }
    return {"summary": "Data Center growth supports keeping the position.", "next_steps": []}


def answer_all(cassette: Path) -> int:
    pending = sorted((cassette / "pending").glob("*.json"))
    for path in pending:
        request = json.loads(path.read_text())
        envelope = {
            "key": request["key"],
            "step": request["step"],
            "via": "a scripted test answerer",
            "model": "scripted",
            "recorded_at": "2026-11-17T12:00:00+00:00",
            "response": answer(request),
        }
        target = cassette / "responses" / f"{request['key']}.json"
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(json.dumps(envelope))
    return len(pending)


def test_pending_requests_exit_3_and_write_no_results(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    cassette, out = tmp_path / "cassette", tmp_path / "results"
    code, _ = run_cli(
        cassette_argv(cassette, out), tmp_path, FakeFilings.synthetic(filing_html(SENTENCE))
    )
    assert code == 3
    assert not out.exists()
    assert (
        f"1 model request(s) are pending in {cassette / 'pending'}. "
        "Answer them (docs/cassettes.md) and run again."
    ) in capsys.readouterr().out
    [pending] = (cassette / "pending").glob("*.json")
    assert json.loads(pending.read_text())["step"] == "plan"


def test_answering_the_pending_requests_takes_four_rounds_then_replays(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    cassette, out = tmp_path / "cassette", tmp_path / "results"
    filings = FakeFilings.synthetic(filing_html(SENTENCE))
    answered: list[list[str]] = []
    for _ in range(6):
        code, _ = run_cli(cassette_argv(cassette, out), tmp_path, filings)
        if code != 3:
            break
        steps = [json.loads(p.read_text())["step"] for p in (cassette / "pending").glob("*.json")]
        answered.append(steps)
        answer_all(cassette)
    assert code == 0
    assert answered == [["plan"], ["assess"], ["check"], ["summarize"]]
    run = written(out)
    assert run.engine == "claude" and run.checker == "claude"
    assert run.checker_detail.startswith("replayed from cassette cassette")
    assert not any("engine failed" in error for error in run.errors)
    assert not any("meaning check" in error for error in run.errors)
    [claim] = run.claims
    assert claim.verdict is not None and VERDICT_LABELS[claim.verdict] == "Supported"
    [finding] = run.findings
    assert finding.checks.support == "passed"
    assert finding.checks.support_detail == "The excerpt says so."
    assert run.coverage.findings_checked == 1
    assert run.brief is not None
    assert run.brief.summary == "Data Center growth supports keeping the position."

    capsys.readouterr()
    assert cli.main(["cassette", str(cassette)]) == 0
    printed = capsys.readouterr().out
    assert "replayed from cassette cassette: 4 responses recorded via a scripted test" in printed
    assert "No pending requests." in printed


def test_the_cassette_command_lists_pending_keys_with_their_step(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    cassette = tmp_path / "cassette"
    run_cli(
        cassette_argv(cassette, tmp_path / "results"),
        tmp_path,
        FakeFilings.synthetic(filing_html(SENTENCE)),
    )
    [pending] = (cassette / "pending").glob("*.json")
    capsys.readouterr()
    assert cli.main(["cassette", str(cassette)]) == 0
    printed = capsys.readouterr().out
    assert "replayed from cassette cassette: no responses recorded" in printed
    assert f"{pending.stem}  plan" in printed
    assert cli.main(["cassette", str(tmp_path / "missing")]) == 2


@pytest.mark.parametrize(
    ("extra", "message"),
    [
        (["--engine", "cassette"], "--cassette"),
        (["--engine", "extractive", "--cassette", "somewhere"], "--engine cassette"),
    ],
)
def test_the_cassette_options_go_together(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], extra: list[str], message: str
) -> None:
    code, store = run_cli(["example", *extra], tmp_path, FakeFilings.nvidia())
    assert code == 2
    assert message in capsys.readouterr().err
    assert store.list_runs() == []
