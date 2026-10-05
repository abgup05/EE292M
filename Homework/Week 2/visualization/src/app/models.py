"""Typed data returned by the Radius visualization API."""

from pydantic import BaseModel


class SectorDetail(BaseModel):
    """One full category from the source workbook."""

    id: str
    name: str
    family: str
    listing_count: int
    example_tickers: list[str]


class GraphNode(BaseModel):
    """A workbook category shown in the curated theme."""

    id: str
    label: str
    stage: int
    sector_name: str
    listing_count: int
    example_tickers: list[str]


class GraphEdge(BaseModel):
    """A directed, conceptual relationship between two categories."""

    source: str
    target: str
    role: str
    kind: str = "conceptual sector dependency"
    active: bool = False


class GraphResponse(BaseModel):
    """Everything the page needs to draw and inspect one theme graph."""

    theme: str
    status: str
    selected: SectorDetail
    nodes: list[GraphNode]
    edges: list[GraphEdge]


class SearchHit(BaseModel):
    """A workbook security matching a ticker or company-name query."""

    ticker: str
    name: str
    sector_id: str
    sector_name: str
    security_type: str
    entity_type: str
    review_status: str
    reference_url: str | None = None
