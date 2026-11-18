"""The claim-category rule against the hand-labelled claims of eval/claim-categories.json.

The labels were written before the rule and are an answer key: a change to the rule
that moves these numbers must be read claim by claim, never fixed by editing a label.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from app.evaluation.claim_categories import load_labels, main, render, score

LABELS = Path(__file__).parents[1] / "eval" / "claim-categories.json"


def test_the_labelled_set_is_large_enough_and_about_half_has_no_category() -> None:
    labelled = load_labels(LABELS)
    assert len(labelled) >= 60
    without = sum(1 for claim in labelled if not claim.categories)
    assert 0.4 <= without / len(labelled) <= 0.6


def test_precision_and_recall_per_category_are_pinned() -> None:
    result = score(load_labels(LABELS))
    table = {t.category: (t.predicted, t.labelled, t.agreed) for t in result.categories}
    assert table == {
        "leadership": (18, 16, 16),
        "accounting": (4, 4, 4),
        "deal": (9, 9, 9),
        "restructuring": (6, 6, 6),
        "incident": (3, 3, 3),
        "financing": (7, 6, 6),
        "control": (4, 4, 4),
        "listing": (2, 2, 2),
    }
    assert (result.none_kept, result.none_labelled, result.exact) == (36, 39, 81)


def test_the_disagreements_are_the_three_known_ones() -> None:
    result = score(load_labels(LABELS))
    assert [(text, got) for text, _, got in result.disagreements] == [
        ("China is gone as a market for its top chips.", ["leadership"]),
        ("Stock-based compensation is diluting shareholders.", ["financing"]),
        ("Intel has left the foundry race to TSMC.", ["leadership"]),
    ]


def test_the_traps_named_in_the_design_get_no_category() -> None:
    result = score(load_labels(LABELS))
    wrong = {text for text, _, _ in result.disagreements}
    for trap in (
        "Margins are gone.",
        "The board game segment is shrinking.",
        "The left-hand column of the segment table shows declining sales.",
    ):
        assert trap not in wrong


def test_the_report_prints_every_category_and_the_totals(capsys: pytest.CaptureFixture) -> None:
    assert main(["--labels", str(LABELS)]) == 0
    out = capsys.readouterr().out
    assert out == render(score(load_labels(LABELS)), LABELS)
    assert "all                   53       50     50      0.94   1.00" in out


def test_a_label_outside_the_substantive_categories_is_refused(tmp_path: Path) -> None:
    bad = tmp_path / "labels.json"
    bad.write_text('{"claims": [{"text": "Results were good.", "categories": ["results"]}]}')
    with pytest.raises(ValueError, match="unknown categories"):
        load_labels(bad)
