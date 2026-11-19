"""The audit of recorded excerpts against today's gate finds a cut it is shown."""

import json
from pathlib import Path

from tests.gate_edge_audit import audit, refusal


def _item(before: str, excerpt: str, after: str) -> dict[str, str]:
    return {
        "id": "e1",
        "finding_id": "f1",
        "context_before": before,
        "excerpt": excerpt,
        "context_after": after,
    }


def test_an_excerpt_cut_beside_its_unit_is_named_with_the_side() -> None:
    cut = _item("In the quarter, ", "Data Center revenue was $46.7", " billion, up 56%.")
    assert refusal(cut) == "ends between a number and its scale word or unit"
    signed = _item("Gaming revenue changed by -", "5% from the prior year", ".")
    assert refusal(signed) == "begins between a sign or currency symbol and its number"
    inside = _item("revenue was $46.", "78 billion for the quarter", ".")
    assert refusal(inside) == "begins inside a word or a number"


def test_a_whole_excerpt_is_kept_at_a_sentence_end_and_at_the_edge_of_the_text() -> None:
    assert refusal(_item("In the quarter, ", "revenue was $46.7 billion", ", up 56%.")) == ""
    assert refusal(_item("", "Revenue for the year was 46.7", ". Margin rose.")) == ""
    assert refusal(_item("", "Data Center revenue grew 56%", "")) == ""


def test_a_file_is_counted_and_only_its_refused_excerpts_are_listed(tmp_path: Path) -> None:
    kept = _item("In the quarter, ", "revenue was $46.7 billion", ", up 56%.")
    cut = _item("It was up ", "56", "% from a year ago.") | {"id": "e2"}
    path = tmp_path / "run.json"
    path.write_text(json.dumps({"evidence": [kept, cut], "claims": [{"id": "c1"}]}))
    count, lines = audit(path)
    assert count == 2 and len(lines) == 1
    assert lines[0].startswith("  e2 of f1: ends between a number and its scale word or unit")
