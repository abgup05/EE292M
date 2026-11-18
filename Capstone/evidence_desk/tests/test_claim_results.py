"""The evaluator against the golden computed claims of ``eval/claim-results.json``.

The expected results were written by :mod:`app.evaluation.claim_oracle`, which reads
the raw recorded facts and never calls the evaluator. Two checks: the key is exactly
what that route gives (no expected value was edited by hand), and the evaluator, run
as of each case's date, agrees with it on the outcome, the bound test and both sides.
"""

from __future__ import annotations

import json
from datetime import date
from pathlib import Path
from typing import Any

import pytest

from app.core.claim_eval import evaluate
from app.core.claimtest import ClaimTest, compile_claim
from app.core.facts import FactBook
from app.core.periods import fiscal_calendar
from app.evaluation.claim_oracle import compute_all, load_payload, recorded_report
from tests.lookahead import late_refs

KEY = Path("eval/claim-results.json")
CASES: list[dict[str, Any]] = json.loads(KEY.read_text(encoding="utf-8"))["cases"]


def test_there_are_at_least_forty_cases_over_the_three_companies() -> None:
    assert len(CASES) >= 40
    assert {case["ticker"] for case in CASES} == {"NVDA", "AAPL", "MSFT"}
    outcomes = {case["expected"]["outcome"] for case in CASES}
    assert outcomes == {"holds", "fails", "cannot_compute"}


def test_the_key_is_what_the_independent_route_gives() -> None:
    assert [case["expected"] for case in CASES] == compute_all(CASES)


@pytest.fixture(scope="module")
def payloads() -> dict[str, dict[str, Any]]:
    return {ticker: load_payload(ticker) for ticker in ("NVDA", "AAPL", "MSFT")}


@pytest.mark.parametrize("case", CASES, ids=[case["id"] for case in CASES])
def test_the_evaluator_agrees_with_the_key(case: dict[str, Any], payloads) -> None:
    test = compile_claim(case["claim"])
    assert isinstance(test, ClaimTest), test
    assert test.canonical == case["canonical"]
    day = date.fromisoformat(case["as_of"])
    payload = payloads[case["ticker"]]
    shares = test.left.fn in ("share", "max_share")
    result = evaluate(
        test,
        FactBook(payload, as_of=day),
        calendar=fiscal_calendar(payload, as_of=day),
        reports=[recorded_report()] if shares else [],
    )
    expected = case["expected"]
    assert result.outcome == expected["outcome"], result.reason
    if expected["bound"] is not None:
        assert result.bound == expected["bound"]
    for side, value in ((result.left, expected["left"]), (result.right, expected["right"])):
        if value is None:
            assert side is None or side.value is None
        else:
            assert side is not None and side.value == pytest.approx(value, rel=1e-9)
    assert late_refs(result, day) == []
