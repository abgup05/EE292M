"""Parse and analyze the BEA commodity-by-industry use matrix."""

import hashlib
import json
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

from openpyxl import load_workbook

from app.flow_models import FlowRow, FlowView, Point

DATA_DIR = Path(__file__).resolve().parents[2] / "data" / "raw" / "bea"


@dataclass
class Table:
    """One year of published flows and official intermediate-use totals."""

    cells: dict[tuple[str, str], float | None]
    industry_totals: dict[str, float | None]
    product_totals: dict[str, float | None]


@dataclass
class Dataset:
    """Aligned annual BEA use tables and their provenance."""

    industries: dict[str, str]
    products: dict[str, str]
    tables: dict[int, Table]
    source: dict


def number(value: object) -> float | None:
    """Preserve BEA ellipses as unreported cells; reject unfamiliar tokens."""
    if value == "...":
        return None
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return float(value)
    raise ValueError(f"Unexpected BEA cell: {value!r}")


@lru_cache(maxsize=1)
def load_dataset() -> Dataset:
    """Validate the source checksum, axes and rounded published totals."""
    source = json.loads((DATA_DIR / "source.json").read_text())
    path = DATA_DIR / "Use_Summary.xlsx"
    if hashlib.sha256(path.read_bytes()).hexdigest() != source["sha256"]:
        raise ValueError("BEA workbook checksum mismatch")
    book = load_workbook(path, read_only=True, data_only=True)
    tables = {}
    industries, products = {}, {}
    try:
        for sheet in book:
            year = int(sheet.title)
            rows = list(sheet.values)
            if rows[1][0] != "(Millions of dollars)":
                raise ValueError("Unexpected BEA units")
            codes = rows[5]
            end_col = codes.index("T001")
            end_row = next(i for i, row in enumerate(rows) if row[0] == "T005")
            inds = {str(codes[c]): str(rows[6][c]) for c in range(2, end_col)}
            prods = {str(rows[r][0]): str(rows[r][1]) for r in range(7, end_row)}
            if industries and (inds != industries or prods != products):
                raise ValueError("BEA classifications differ between years")
            industries, products = inds, prods
            cells = {
                (str(rows[r][0]), str(codes[c])): number(rows[r][c])
                for r in range(7, end_row)
                for c in range(2, end_col)
            }
            itot = {str(codes[c]): number(rows[end_row][c]) for c in range(2, end_col)}
            ptot = {
                str(rows[r][0]): number(rows[r][end_col]) for r in range(7, end_row)
            }
            # Source values are rounded independently to whole millions.
            for ind, total in itot.items():
                actual = sum(cells[p, ind] or 0 for p in products)
                if total is None and actual == 0:
                    continue
                if total is None:
                    raise ValueError("Missing intermediate total with numeric flows")
                if abs(actual - total) > len(products) * 0.5 + 0.5:
                    raise ValueError(f"Industry total does not reconcile: {year} {ind}")
            for prod, total in ptot.items():
                actual = sum(cells[prod, i] or 0 for i in industries)
                if total is None and actual == 0:
                    continue
                if total is None:
                    raise ValueError("Missing intermediate total with numeric flows")
                if abs(actual - total) > len(industries) * 0.5 + 0.5:
                    raise ValueError(f"Product total does not reconcile: {year} {prod}")
            tables[year] = Table(cells, itot, ptot)
    finally:
        book.close()
    return Dataset(industries, products, tables, source)


def money(value: float | None) -> str:
    """Format source millions into readable nominal dollar amounts."""
    if value is None:
        return "Not reported"
    sign = "−" if value < 0 else ""
    magnitude = abs(value)
    if magnitude >= 1_000_000:
        return f"{sign}${magnitude / 1_000_000:,.2f}T"
    if magnitude >= 1_000:
        return f"{sign}${magnitude / 1_000:,.2f}B"
    return f"{sign}${magnitude:,.0f}M"


def share(value: float | None, total: float | None) -> float | None:
    """Express a flow against a positive published intermediate total."""
    return (
        value / total * 100
        if value is not None and total is not None and total > 0
        else None
    )


def growth(value: float | None, old: float | None) -> float | None:
    """Return nominal growth only for a positive comparison value."""
    return (
        (value / old - 1) * 100
        if value is not None and old is not None and old > 0
        else None
    )


def percent(value: float | None, signed: bool = False, unit: str = "%") -> str:
    """Format a percentage or percentage-point change on the server."""
    if value is None:
        return "N/A"
    return f"{value:+.1f}{unit}" if signed else f"{value:.1f}{unit}"


def explore(
    data: Dataset,
    mode: str,
    focus: str,
    year: int,
    baseline: int,
    sort: str = "amount",
    selected: str | None = None,
) -> FlowView:
    """Rank one matrix axis, compare shares, and trace one relationship."""
    if mode not in {"inputs", "buyers"} or sort not in {"amount", "share_change"}:
        raise ValueError("Unknown view or ranking")
    focuses = data.industries if mode == "inputs" else data.products
    counterparts = data.products if mode == "inputs" else data.industries
    if focus not in focuses or year not in data.tables or baseline not in data.tables:
        raise ValueError("Unknown industry, product or year")
    if selected is not None and selected not in counterparts:
        raise ValueError("Unknown relationship")

    def cell(t: Table, other: str) -> float | None:
        return t.cells[(other, focus) if mode == "inputs" else (focus, other)]

    def total(t: Table) -> float | None:
        return (t.industry_totals if mode == "inputs" else t.product_totals)[focus]

    now, before = data.tables[year], data.tables[baseline]
    rows = []
    for code, name in counterparts.items():
        value, old = cell(now, code), cell(before, code)
        if value is None:
            continue
        portion, previous = share(value, total(now)), share(old, total(before))
        delta = (
            portion - previous if portion is not None and previous is not None else None
        )
        change = growth(value, old)
        rows.append(
            FlowRow(
                id=code,
                name=name,
                amount=value,
                amount_label=money(value),
                share=portion,
                share_label=percent(portion),
                baseline_amount=old,
                change_pct=change,
                change_label=percent(change, True),
                share_change=delta,
                share_change_label=percent(delta, True, " pp"),
            )
        )
    rows.sort(
        key=lambda r: (
            getattr(r, sort) is not None,
            getattr(r, sort) if getattr(r, sort) is not None else float("-inf"),
            r.amount,
            r.id,
        ),
        reverse=True,
    )
    if selected is None and rows:
        selected = rows[0].id
    series = []
    if selected is not None:
        for y, table in sorted(data.tables.items()):
            value = cell(table, selected)
            portion = share(value, total(table))
            series.append(
                Point(
                    year=y,
                    amount=value,
                    amount_label=money(value),
                    share=portion,
                    share_label=percent(portion),
                )
            )
    if rows:
        leader = rows[0]
        if sort == "share_change" and leader.share_change is not None:
            insight = (
                f"{leader.name}: {leader.share_change_label} of the total versus {baseline}; "
                f"{leader.amount_label} in {year}."
            )
        else:
            insight = f"{leader.name} accounts for {leader.share_label} of this total ({leader.amount_label})."
    else:
        insight = "No numeric intermediate purchases are reported for this selection."
    return FlowView(
        mode=mode,
        focus=focus,
        focus_name=focuses[focus],
        year=year,
        baseline=baseline,
        total=total(now),
        total_label=money(total(now)),
        total_change_label=percent(growth(total(now), total(before)), True),
        denominator_label=(
            "All intermediate inputs purchased by this industry"
            if mode == "inputs"
            else "Purchases of this product by all industries; excludes final uses"
        ),
        rows=rows,
        missing_count=len(counterparts) - len(rows),
        selected=selected,
        selected_name=counterparts.get(selected),
        series=series,
        insight=insight,
        source=data.source,
    )
