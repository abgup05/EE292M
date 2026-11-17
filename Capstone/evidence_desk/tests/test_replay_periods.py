"""What ``make replay`` prints about the period check: the counts, and each year not found."""

from __future__ import annotations

from pathlib import Path

from app.core.models import Run, UnplacedPeriod
from tests.replay_run import period_lines

RECORDED = Path(__file__).parent.parent / "demo" / "recorded-run-v5.json"
NOT_FOUND = "is not in the quotes, the cited figures or the period of a filing quoted"
COMPARATIVE = (
    "; it is a year or two before the fiscal year of a filing quoted or a cited figure, "
    "as a report's comparison year would be"
)


def test_the_replay_prints_the_counts_and_each_unverified_year_with_its_statement() -> None:
    run = Run.model_validate_json(RECORDED.read_text())
    first, second = run.findings[0], run.findings[1]
    first.checks.periods = "unverified"
    first.checks.periods_detail = [
        "fiscal year 2027 is in a quote",
        f"fiscal 2025 {NOT_FOUND}{COMPARATIVE}",
    ]
    first.checks.periods_unverified = [
        UnplacedPeriod(
            mention="fiscal 2025", comparative=True, detail=f"fiscal 2025 {NOT_FOUND}{COMPARATIVE}"
        )
    ]
    second.checks.periods = "unverified"
    second.checks.periods_detail = [f"fiscal 2023 {NOT_FOUND}"]
    second.checks.periods_unverified = [
        UnplacedPeriod(mention="fiscal 2023", detail=f"fiscal 2023 {NOT_FOUND}")
    ]
    run.coverage.periods_checked = 3
    run.coverage.periods_unverified = 2
    run.coverage.periods_comparative = 1
    assert period_lines(run) == [
        "periods checked 3, unverified 2 (1 comparative)",
        f"  {first.id} fiscal 2025 (comparative): {first.statement}",
        f"  {second.id} fiscal 2023: {second.statement}",
    ]


def test_a_run_with_every_year_found_prints_only_the_counts() -> None:
    run = Run.model_validate_json(RECORDED.read_text())
    assert period_lines(run) == ["periods checked 0, unverified 0 (0 comparative)"]
