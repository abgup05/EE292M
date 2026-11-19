"""Persistence odds: how likely a claim's test is to still hold over the next quarters.

Pure and deterministic given the seed. A bootstrap: each of
:data:`~app.core.analysis_policy.PERSISTENCE_PATHS` paths draws, with replacement, one of the
measure's own historical quarterly changes for each of the next
:data:`~app.core.analysis_policy.PERSISTENCE_HORIZON` quarters, starting from the current
value, and the estimate is the share of paths in which the test holds in every one of those
quarters. A ratio steps by points (its changes are differences), an amount by relative
changes (its changes are growth rates). For growth on a year earlier, each future quarter is
compared with the known quarter four before it.

It applies to a test of a quarterly measure of the whole company against a constant: a
threshold on its value (``gross_margin[Q] > 70%``, also held in each of several quarters) or
on its growth on a year earlier (``yoy(revenue)[Q] > 50%``). With fewer than
:data:`~app.core.analysis_policy.PERSISTENCE_MIN_CHANGES` changes in the facts it gives no
number, only a warning. It assumes the past changes are exchangeable (no trend, no
seasonality, no regime change); it describes the history and is not a forecast.
"""

from __future__ import annotations

import operator
import random
from collections.abc import Callable, Sequence
from dataclasses import dataclass

from ed_v14.core import analysis_policy as rules
from ed_v14.core.analysis_models import Persistence
from ed_v14.core.analytics import display, quarterly
from ed_v14.core.claim_eval import Measures
from ed_v14.core.claim_test_models import ComputedTest
from ed_v14.core.claimtest import METRICS, ClaimTest, Number

OPS: dict[str, Callable[[float, float], bool]] = {
    ">": operator.gt,
    ">=": operator.ge,
    "<": operator.lt,
    "<=": operator.le,
}


@dataclass(frozen=True)
class Setup:
    """What the simulation needs: the start, the changes, the threshold and the test's kind.

    ``levels`` are the latest quarters' values, newest first (the year-earlier bases of a
    growth test); ``changes`` the historical quarterly changes, newest first.
    """

    kind: str  # "value" or "yoy"
    step: str  # "points" or "relative"
    levels: tuple[float, ...]
    changes: tuple[float, ...]
    op: str
    threshold: float


def holds_on_path(setup: Setup, draws: Sequence[float]) -> bool:
    """True when the test holds in every future quarter of one path of drawn changes."""
    compare = OPS[setup.op]
    value = setup.levels[0]
    # The quarter four before future quarter h (1-based) is levels[4 - h].
    for h, change in enumerate(draws, start=1):
        value = value + change if setup.step == "points" else value * (1 + change)
        if setup.kind == "value":
            tested = value
        else:
            base = setup.levels[4 - h] if 4 - h >= 0 else None
            if base is None or base <= 0:
                return False
            tested = (value - base) / base * 100
        if not compare(tested, setup.threshold):
            return False
    return True


def simulate(setup: Setup, paths: int, horizon: int, seed: int) -> float:
    """The percent of ``paths`` resampled paths in which the test holds throughout."""
    rng = random.Random(seed)
    held = 0
    for _ in range(paths):
        draws = rng.choices(setup.changes, k=horizon)
        held += holds_on_path(setup, draws)
    return held / paths * 100


def _setup(test: ClaimTest, measures: Measures) -> Setup | str:
    """The simulation's inputs from the facts, or the key of why it does not apply."""
    if test.also is not None or not isinstance(test.right, Number):
        return "form"
    left = test.left
    if left.axis or left.period.kind != "Q" or left.period.back or left.period.named:
        return "form"
    if left.subject not in METRICS or left.fn not in ("value", "yoy"):
        return "form"
    kind = METRICS[left.subject][1]
    if left.fn == "yoy" and kind == "ratio":
        return "form"
    if kind not in ("ratio", "flow", "instant", "per_share"):
        return "form"
    step = "points" if kind == "ratio" else "relative"
    points, _ = quarterly(measures, left.subject, rules.PERSISTENCE_MAX_HISTORY + 1)
    values = [p.value for p in points]
    changes: list[float] = []
    for newer, older in zip(values, values[1:], strict=False):
        if step == "points":
            changes.append(newer - older)
        elif older > 0:
            changes.append(newer / older - 1)
    if not values:
        return "uncomputed"
    return Setup(
        kind=left.fn,
        step=step,
        levels=tuple(values[:4]),
        changes=tuple(changes),
        op=test.op,
        threshold=test.right.value,
    )


def persistence(
    claim_id: str,
    test: ClaimTest | None,
    computed: ComputedTest | None,
    measures: Measures | None,
    *,
    paths: int = rules.PERSISTENCE_PATHS,
    horizon: int = rules.PERSISTENCE_HORIZON,
    seed: int = rules.PERSISTENCE_SEED,
) -> Persistence:
    """The resampled odds that ``claim_id``'s test holds in each of the next ``horizon``
    quarters, or why there are none."""
    record = Persistence(id=f"odds:{claim_id}", claim_id=claim_id)
    if test is None or computed is None:
        return record.model_copy(update={"note": rules.PERSISTENCE_NOT_APPLICABLE["no_test"]})
    if computed.outcome == "cannot_compute" or measures is None:
        return record.model_copy(update={"note": rules.PERSISTENCE_NOT_APPLICABLE["uncomputed"]})
    setup = _setup(test, measures)
    if isinstance(setup, str):
        return record.model_copy(update={"note": rules.PERSISTENCE_NOT_APPLICABLE[setup]})
    unit = "percent" if METRICS[test.left.subject][1] == "ratio" else "USD"
    if METRICS[test.left.subject][1] == "per_share":
        unit = "USD_per_share"
    words = "differences in points" if setup.step == "points" else "growth rates"
    common = {
        "applicable": True,
        "test": test.canonical,
        "step": setup.step,
        "changes": len(setup.changes),
        "paths": paths,
        "seed": seed,
        "horizon": horizon,
        "start_value": setup.levels[0],
        "start_display": display(setup.levels[0], unit),  # type: ignore[arg-type]
        "caveat": rules.PERSISTENCE_CAVEAT,
        "method": rules.PERSISTENCE_METHOD.format(
            paths=paths, horizon=horizon, changes=len(setup.changes), step=words, seed=seed
        ),
    }
    if len(setup.changes) < rules.PERSISTENCE_MIN_CHANGES:
        warning = rules.PERSISTENCE_SHORT.format(
            changes=len(setup.changes), needed=rules.PERSISTENCE_MIN_CHANGES
        )
        return record.model_copy(update={**common, "warning": warning, "display": "n/a"})
    if setup.kind == "yoy" and len(setup.levels) < 4:
        return record.model_copy(
            update={**common, "warning": "Four quarters are needed as year-earlier bases."}
        )
    probability = simulate(setup, paths, horizon, seed)
    shown = f"{probability:.0f}%"
    return record.model_copy(
        update={
            **common,
            "probability": probability,
            "display": shown,
            "note": (
                f"In {shown} of {paths:,} resampled paths the test held in each of the next "
                f"{horizon} quarters, drawing from its last {len(setup.changes)} quarterly "
                f"{words}."
            ),
        }
    )
