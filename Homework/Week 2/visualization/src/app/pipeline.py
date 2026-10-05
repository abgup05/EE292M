"""Read the source workbook and prepare the sector dependency graph."""

import json
from collections import Counter
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

from openpyxl import load_workbook

from app.models import GraphEdge, GraphNode, GraphResponse, SearchHit, SectorDetail


@dataclass(frozen=True)
class Catalog:
    """Validated source classifications and the authored conceptual map."""

    sectors: dict[str, SectorDetail]
    listings: tuple[SearchHit, ...]
    theme: dict


def _required_text(value: object, field: str) -> str:
    """Reject missing source identifiers instead of turning them into blank labels."""
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"Missing or invalid {field} in source workbook")
    return value.strip()


def load_catalog(data_dir: Path) -> Catalog:
    """Load the supplied workbook and verify its sector counts before use."""
    book_path = data_dir / "raw" / "NYSE_50_sector_classification.xlsx"
    theme_path = data_dir / "conceptual_links.json"
    if not book_path.is_file() or not theme_path.is_file():
        raise FileNotFoundError("Visualization source data is missing")

    workbook = load_workbook(book_path, read_only=True, data_only=True)
    try:
        if "Sector guide" not in workbook or "All listings" not in workbook:
            raise ValueError("Expected source worksheets are missing")
        guide = workbook["Sector guide"]
        listings_sheet = workbook["All listings"]
        if tuple(cell.value for cell in listings_sheet[9][:4]) != (
            "Ticker",
            "Original listing name",
            "Security type",
            "Sector ID",
        ):
            raise ValueError("The source listing columns have changed")

        sectors: dict[str, SectorDetail] = {}
        for row in guide.iter_rows(min_row=9, values_only=True):
            if row[0] is None:
                continue
            sector_id = _required_text(row[0], "sector ID")
            if sector_id in sectors:
                raise ValueError(f"Duplicate sector ID: {sector_id}")
            if not isinstance(row[2], int) or row[2] < 0:
                raise ValueError(f"Invalid listing count for sector {sector_id}")
            sectors[sector_id] = SectorDetail(
                id=sector_id,
                name=_required_text(row[1], "sector name"),
                family=_required_text(row[6], "sector family"),
                listing_count=row[2],
                example_tickers=[
                    item.strip()
                    for item in _required_text(row[5], "examples").split("·")
                ],
            )

        listings: list[SearchHit] = []
        counts: Counter[str] = Counter()
        for row in listings_sheet.iter_rows(min_row=10, values_only=True):
            if row[0] is None:
                continue
            sector_id = _required_text(row[3], "listing sector ID")
            if sector_id not in sectors:
                raise ValueError(f"Unknown source sector: {sector_id}")
            listings.append(
                SearchHit(
                    ticker=_required_text(row[0], "ticker"),
                    name=_required_text(row[1], "listing name"),
                    sector_id=sector_id,
                    sector_name=sectors[sector_id].name,
                    security_type=_required_text(row[2], "security type"),
                    entity_type=_required_text(row[6], "entity type"),
                    review_status=_required_text(row[7], "review status"),
                    reference_url=row[13] if isinstance(row[13], str) else None,
                )
            )
            counts[sector_id] += 1
        for sector_id, sector in sectors.items():
            if counts[sector_id] != sector.listing_count:
                raise ValueError(
                    f"Source listing count does not reconcile for sector {sector_id}"
                )
    finally:
        workbook.close()

    with theme_path.open(encoding="utf-8") as stream:
        theme = json.load(stream)
    node_ids = [item["id"] for item in theme["nodes"]]
    if len(node_ids) != len(set(node_ids)) or not set(node_ids) <= set(sectors):
        raise ValueError("Concept map has duplicate or unknown sectors")
    for edge in theme["edges"]:
        if edge["from"] not in node_ids or edge["to"] not in node_ids:
            raise ValueError("Concept map has an unknown edge endpoint")
        if edge["from"] == edge["to"]:
            raise ValueError("Concept map has a self-link")
    return Catalog(sectors=sectors, listings=tuple(listings), theme=theme)


@lru_cache(maxsize=1)
def project_catalog() -> Catalog:
    """Read the committed snapshot once per app process."""
    return load_catalog(Path(__file__).resolve().parents[2] / "data")


def build_graph(catalog: Catalog, focus_id: str) -> GraphResponse:
    """Mark links incident to the selected workbook category."""
    if focus_id not in catalog.sectors:
        raise ValueError(f"Unknown sector: {focus_id}")
    nodes = [
        GraphNode(
            id=item["id"],
            label=item["label"],
            stage=item["stage"],
            sector_name=catalog.sectors[item["id"]].name,
            listing_count=catalog.sectors[item["id"]].listing_count,
            example_tickers=catalog.sectors[item["id"]].example_tickers,
        )
        for item in catalog.theme["nodes"]
    ]
    edges = [
        GraphEdge(
            source=item["from"],
            target=item["to"],
            role=item["role"],
            active=focus_id in (item["from"], item["to"]),
        )
        for item in catalog.theme["edges"]
    ]
    return GraphResponse(
        theme=catalog.theme["theme"],
        status=catalog.theme["status"],
        selected=catalog.sectors[focus_id],
        nodes=nodes,
        edges=edges,
    )


def search_catalog(catalog: Catalog, query: str, limit: int) -> list[SearchHit]:
    """Find ticker and issuer-name matches, with exact ticker hits first."""
    needle = query.strip().casefold()
    if not needle or not 1 <= limit <= 25:
        raise ValueError("Search query or limit is invalid")
    matched = [
        listing
        for listing in catalog.listings
        if needle in listing.ticker.casefold() or needle in listing.name.casefold()
    ]
    matched.sort(
        key=lambda item: (
            item.ticker.casefold() != needle,
            not item.ticker.casefold().startswith(needle),
            item.ticker,
        )
    )
    return matched[:limit]
