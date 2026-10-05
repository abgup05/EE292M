"""Typed API contract for official industry purchase flows."""

from pydantic import BaseModel


class FlowRow(BaseModel):
    """One product-to-industry purchase relationship, in millions of dollars."""

    id: str
    name: str
    amount: float
    amount_label: str
    share: float | None
    share_label: str
    baseline_amount: float | None
    change_pct: float | None
    change_label: str
    share_change: float | None
    share_change_label: str


class Point(BaseModel):
    """One year of a relationship, with missing values preserved."""

    year: int
    amount: float | None
    amount_label: str
    share: float | None
    share_label: str


class FlowView(BaseModel):
    """All research results required by the browser."""

    mode: str
    focus: str
    focus_name: str
    year: int
    baseline: int
    total: float | None
    total_label: str
    total_change_label: str
    denominator_label: str
    rows: list[FlowRow]
    missing_count: int
    selected: str | None
    selected_name: str | None
    series: list[Point]
    insight: str
    source: dict
