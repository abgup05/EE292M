"""Independent examples check matrix direction, denominators and changes."""

import pytest

from app.flows import Dataset, Table, explore, load_dataset


@pytest.fixture
def dataset():
    """Small asymmetric matrix with a missing cell and a negative adjustment."""
    return Dataset(
        industries={"a": "Alpha", "b": "Beta"},
        products={"x": "Energy", "y": "Services", "z": "Adjustment"},
        tables={
            2020: Table(
                {
                    ("x", "a"): 20,
                    ("y", "a"): 80,
                    ("z", "a"): 0,
                    ("x", "b"): 30,
                    ("y", "b"): 10,
                    ("z", "b"): None,
                },
                {"a": 100, "b": 40},
                {"x": 50, "y": 90, "z": 0},
            ),
            2021: Table(
                {
                    ("x", "a"): 50,
                    ("y", "a"): 60,
                    ("z", "a"): -10,
                    ("x", "b"): 150,
                    ("y", "b"): 50,
                    ("z", "b"): None,
                },
                {"a": 100, "b": 200},
                {"x": 200, "y": 110, "z": -10},
            ),
        },
        source={"url": "https://example.org", "retrieved_at": "2026-10-05"},
    )


def test_input_shares_and_changes(dataset):
    result = explore(dataset, "inputs", "a", 2021, 2020, "amount", "x")
    assert [r.id for r in result.rows] == ["y", "x", "z"]
    energy = result.rows[1]
    assert energy.amount == 50
    assert energy.share == 50
    assert energy.change_pct == 150
    assert energy.share_change == 30
    assert result.total == 100  # Includes the negative adjustment.
    assert [p.amount for p in result.series] == [20, 50]


def test_buyers_transposes_matrix_and_uses_product_total(dataset):
    result = explore(dataset, "buyers", "x", 2021, 2020, "amount", "a")
    assert [r.id for r in result.rows] == ["b", "a"]
    assert result.rows[0].share == 75
    assert result.rows[1].share_change == -15
    assert [p.amount for p in result.series] == [20, 50]


def test_share_gainers_and_zero_baselines(dataset):
    result = explore(dataset, "inputs", "a", 2021, 2020, "share_change", "z")
    assert result.rows[0].id == "x"
    assert result.rows[-1].id == "y"
    adjustment = next(r for r in result.rows if r.id == "z")
    assert adjustment.change_pct is None


def test_missing_is_not_silently_zero(dataset):
    result = explore(dataset, "buyers", "z", 2021, 2020, "amount", "b")
    assert result.missing_count == 1
    assert [r.id for r in result.rows] == ["a"]
    assert all(p.amount is None for p in result.series)


@pytest.mark.parametrize(
    "args",
    [
        ("inputs", "bad", 2021, 2020, "amount", None),
        ("inputs", "a", 1999, 2020, "amount", None),
        ("inputs", "a", 2021, 2020, "amount", "bad"),
    ],
)
def test_unknown_selection_rejected(dataset, args):
    with pytest.raises(ValueError):
        explore(dataset, *args)


def test_official_workbook_matches_known_source_cells():
    data = load_dataset()
    assert len(data.industries) == 71
    assert len(data.products) == 73
    assert min(data.tables) == 1997 and max(data.tables) == 2025
    table = data.tables[2025]
    assert table.cells["211", "211"] == 35807
    assert table.industry_totals["111CA"] == 374787
    assert table.cells["Used", "111CA"] == -18
