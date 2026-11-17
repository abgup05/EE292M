"""The two breakdown samples the page can show (``src/web/sample-breakdowns*.json``).

``sample-breakdowns.json`` is a real record written by ``make breakdowns``;
``sample-breakdowns-gap.json`` is that record with one value taken out, for the page
tests. These tests keep both valid records and keep the second from drifting.
"""

from __future__ import annotations

import json

from app.api import WEB_DIR
from app.core.breakdown_models import BreakdownReport

RECORDED = WEB_DIR / "sample-breakdowns.json"
GAP = WEB_DIR / "sample-breakdowns-gap.json"


def load(path) -> BreakdownReport:
    payload = json.loads(path.read_text(encoding="utf-8"))
    assert set(payload) == {"note", "report"} and payload["note"].strip()
    return BreakdownReport.model_validate(payload["report"])


def test_the_recorded_sample_is_a_record_whose_cells_are_ready_to_draw() -> None:
    report = load(RECORDED)
    assert {b.id for b in report.breakdowns} >= {"revenue_by_segment", "revenue_by_product"}
    for breakdown in report.breakdowns:
        assert breakdown.unit_label and breakdown.periods
        columns = {(p.period_start, p.period_end) for p in breakdown.periods}
        for row in breakdown.rows:
            assert row.label and row.values
            for value in row.values:
                assert value.display, (breakdown.id, row.member)
                assert (value.period_start, value.period_end) in columns
                assert bool(value.change_display) == (value.change is not None)


def test_the_gap_sample_is_the_recorded_one_with_exactly_one_value_taken_out() -> None:
    recorded, gap = load(RECORDED), load(GAP)
    assert "SYNTHETIC" in json.loads(GAP.read_text(encoding="utf-8"))["note"]
    missing = []
    for before, after in zip(recorded.breakdowns, gap.breakdowns, strict=True):
        assert before.model_copy(update={"rows": []}) == after.model_copy(update={"rows": []})
        for old, new in zip(before.rows, after.rows, strict=True):
            assert (old.member, old.label) == (new.member, new.label)
            gone = [v for v in old.values if v not in new.values]
            assert all(v in old.values for v in new.values)
            missing += [(before.id, old.label, v.period_end) for v in gone]
    middle = recorded.breakdowns[1].periods[1].period_end
    assert missing == [("revenue_by_product", "Gaming", middle)]
