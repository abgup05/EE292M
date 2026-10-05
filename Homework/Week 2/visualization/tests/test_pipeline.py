"""Checks for the spreadsheet-backed sector graph."""

from pathlib import Path

import pytest

from app.pipeline import build_graph, load_catalog, search_catalog

DATA_DIR = Path(__file__).resolve().parents[1] / "data"


@pytest.fixture(scope="module")
def catalog():
    """Read the committed source workbook once for the pipeline checks."""
    return load_catalog(DATA_DIR)


def test_workbook_categories_and_security_counts_reconcile(catalog):
    """The graph's company lookup comes from the complete, unaltered workbook."""
    assert len(catalog.sectors) == 50
    assert len(catalog.listings) == 2922
    assert catalog.sectors["11"].listing_count == 44
    assert catalog.sectors["47"].listing_count == 89
    assert sum(sector.listing_count for sector in catalog.sectors.values()) == len(
        catalog.listings
    )


def test_company_membership_is_classification_not_relationship(catalog):
    """Searching a ticker reveals its sector without inventing a supplier link."""
    hits = search_catalog(catalog, "vrt", 10)
    assert hits[0].ticker == "VRT"
    assert hits[0].sector_id == "11"
    assert hits[0].sector_name == "Electrical, thermal, water and energy equipment"
    assert search_catalog(catalog, "no-such-ticker", 10) == []


def test_graph_direction_and_selected_neighbors(catalog):
    """The documented concept map is directed and its selected links are exact."""
    graph = build_graph(catalog, "47")
    assert graph.selected.id == "47"
    assert len(graph.nodes) == 7
    assert len(graph.edges) == 6
    assert {(edge.source, edge.target) for edge in graph.edges if edge.active} == {
        ("11", "47"),
        ("12", "47"),
        ("19", "47"),
        ("33", "47"),
    }
    assert all(edge.kind == "conceptual sector dependency" for edge in graph.edges)
    assert "DLR" in graph.selected.example_tickers


def test_unknown_focus_is_rejected(catalog):
    """Invalid identifiers must not silently select another sector."""
    with pytest.raises(ValueError, match="Unknown sector"):
        build_graph(catalog, "99")
