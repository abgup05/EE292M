"""Persistence odds: the resampled estimate agrees with an exact enumeration and is repeatable.

With 8 historical changes and 4 quarters ahead there are only 8**4 = 4,096 equally likely
paths, so the exact probability is counted here path by path, by a route that shares
nothing with the simulation but the rule for one path; the 10,000-path estimate must land
within two points of it (its standard error is at most half a point).
"""

from __future__ import annotations

import itertools
from typing import Any

import pytest

from app.core import analysis_policy as rules
from app.core.claim_eval import Measures
from app.core.claimtest import ClaimTest, compile_claim
from app.core.facts import FactBook
from app.core.periods import fiscal_calendar
from app.core.persistence import Setup, persistence, simulate
from tests.test_analytics import gross_margin, revenue, synthetic

CHANGES = (1.0, -1.0, -2.0, 3.0, 0.0, -1.0, 2.0, -3.0)


def _exact_value_test(start: float, threshold: float) -> float:
    held = 0
    for path in itertools.product(CHANGES, repeat=4):
        level, ok = start, True
        for change in path:
            level += change
            ok = ok and level > threshold
        held += ok
    return held / len(CHANGES) ** 4 * 100


def test_the_estimate_matches_the_exact_odds_for_a_threshold() -> None:
    setup = Setup("value", "points", (60.0,), CHANGES, ">", 57.0)
    exact = _exact_value_test(60.0, 57.0)
    estimate = simulate(setup, rules.PERSISTENCE_PATHS, 4, rules.PERSISTENCE_SEED)
    assert 5 < exact < 95, "the case should not be trivial"
    assert estimate == pytest.approx(exact, abs=2.0)


def test_the_estimate_matches_the_exact_odds_for_growth_on_a_year_earlier() -> None:
    relative = (0.05, -0.02, 0.10, 0.0, -0.05, 0.03, 0.08, -0.08)
    levels = (210.0, 200.0, 190.0, 180.0)  # newest first: the year-earlier bases
    held = 0
    for path in itertools.product(relative, repeat=4):
        level, ok = levels[0], True
        for h, change in enumerate(path, start=1):
            level *= 1 + change
            base = levels[4 - h]
            ok = ok and (level / base - 1) * 100 > 10
        held += ok
    exact = held / len(relative) ** 4 * 100
    setup = Setup("yoy", "relative", levels, relative, ">", 10.0)
    estimate = simulate(setup, rules.PERSISTENCE_PATHS, 4, rules.PERSISTENCE_SEED)
    assert 5 < exact < 95
    assert estimate == pytest.approx(exact, abs=2.0)


def test_the_same_seed_gives_the_same_odds() -> None:
    setup = Setup("value", "points", (60.0,), CHANGES, ">", 57.0)
    assert simulate(setup, 2_000, 4, 7) == simulate(setup, 2_000, 4, 7)


def _measures(payload: dict[str, Any]) -> Measures:
    return Measures(FactBook(payload), fiscal_calendar(payload))


def _test(claim: str) -> ClaimTest:
    test = compile_claim(claim)
    assert isinstance(test, ClaimTest), test
    return test


class _Computed:
    outcome = "holds"


def test_a_claim_gets_its_method_sample_and_seed_on_the_record() -> None:
    payload = synthetic()
    record = persistence(
        "c1",
        _test("Gross margin is above 55.5%."),
        _Computed(),
        _measures(payload),  # type: ignore[arg-type]
    )
    # The margin rose a point every quarter: every change is +1, so every path holds.
    assert record.applicable and record.probability == pytest.approx(100.0)
    assert record.changes == 11 and record.step == "points"
    assert record.seed == rules.PERSISTENCE_SEED and record.paths == rules.PERSISTENCE_PATHS
    assert record.start_value == pytest.approx(gross_margin(11) * 100)
    assert "Seed 20261118" in record.method and "not a forecast" in record.method


def test_growth_on_a_year_earlier_uses_the_known_bases() -> None:
    payload = synthetic()
    # Revenue rises by 10 M a quarter: growth on a year earlier keeps falling (23.5% now).
    record = persistence(
        "c2",
        _test("Revenue grew more than 30% year over year."),
        _Computed(),  # type: ignore[arg-type]
        _measures(payload),
    )
    assert record.applicable and record.step == "relative"
    assert record.start_value == pytest.approx(revenue(11))
    assert record.probability is not None and record.probability < 50


def test_a_company_with_few_quarters_gets_the_warning() -> None:
    from datetime import date

    payload = synthetic()
    measures = Measures(
        FactBook(payload, as_of=date(2024, 8, 31)),
        fiscal_calendar(payload, as_of=date(2024, 8, 31)),
    )
    record = persistence(
        "c1",
        _test("Gross margin is above 50.5%."),
        _Computed(),
        measures,  # type: ignore[arg-type]
    )
    assert record.applicable and record.probability is None
    assert record.changes < rules.PERSISTENCE_MIN_CHANGES
    assert "at least 8 are needed" in record.warning


def test_a_test_it_does_not_apply_to_says_why() -> None:
    payload = synthetic()
    record = persistence(
        "c1",
        _test("Gross margin is expanding."),
        _Computed(),
        _measures(payload),  # type: ignore[arg-type]
    )
    assert not record.applicable and record.note == rules.PERSISTENCE_NOT_APPLICABLE["form"]
    none = persistence("c2", None, None, None)
    assert not none.applicable and none.note == rules.PERSISTENCE_NOT_APPLICABLE["no_test"]
