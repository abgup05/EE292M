"""Browser-level checks of the tagged-breakdowns view, against the record the page was given.

`make uitest` renders /?sample=breakdowns, which loads src/web/sample-breakdowns.json
({"note", "report": BreakdownReport}), and dumps the DOM to results/dom-breakdowns.html.
The page computes nothing here: every heading, cell and change must be the record's own
string, in the column of its period.
"""

from __future__ import annotations

import copy
import json
from functools import cache
from pathlib import Path
from typing import Any

import pytest
from bs4 import BeautifulSoup, Tag
from test_dom import require_fresh, static_page

ROOT = Path(__file__).resolve().parents[1]
WEB = ROOT / "src" / "web"
DOM = ROOT / "results" / "dom-breakdowns.html"
SAMPLE = WEB / "sample-breakdowns.json"
PLACEHOLDERS = ("undefined", "NaN", "[object Object]", "null")
ADDS_UP = {True: ("yes", "Adds up"), False: ("no", "Does not add up"), None: ("unchecked", "Not checked")}


@cache
def report() -> dict[str, Any]:
    return json.loads(SAMPLE.read_text(encoding="utf-8"))["report"]


@cache
def page() -> BeautifulSoup:
    require_fresh(DOM, SAMPLE)
    soup = BeautifulSoup(DOM.read_text(encoding="utf-8"), "html.parser")
    view = soup.select_one("#breakdowns-view")
    if view is None or view.has_attr("hidden"):
        pytest.fail(f"{DOM.name}: the page did not render the breakdowns (is the sample file served?)")
    return soup


def text(node: Tag) -> str:
    return node.get_text()


def words(node: Tag) -> str:
    return " ".join(text(node).split())


def visible(node: Tag) -> str:
    clone = copy.copy(node)
    for hidden in clone.select(".visually-hidden"):
        hidden.decompose()
    return words(clone)


def key(item: dict[str, Any]) -> str:
    return f"{item['period_start'] or ''}|{item['period_end']}"


def breakdowns() -> list[dict[str, Any]]:
    return report()["breakdowns"]


def section(breakdown: dict[str, Any]) -> Tag:
    node = page().select_one(f'#breakdowns-body section[data-breakdown-id="{breakdown["id"]}"]')
    assert node is not None, f"{breakdown['id']}: no table"
    return node


def test_one_table_per_breakdown_in_record_order() -> None:
    shown = [s["data-breakdown-id"] for s in page().select("#breakdowns-body section[data-breakdown-id]")]
    assert shown == [b["id"] for b in breakdowns()]
    assert len(shown) == 5


@pytest.mark.parametrize("index", range(5))
def test_title_unit_and_column_labels_are_the_records(index: int) -> None:
    breakdown = breakdowns()[index]
    node = section(breakdown)
    assert text(node.select_one("h3.bd-title")) == breakdown["title"]
    units = node.select(".bd-unit")
    assert [text(u) for u in units] == [breakdown["unit_label"]], "the unit must appear exactly once"
    columns = node.select("thead th.bd-period")
    assert [text(th) for th in columns] == [p["label"] for p in breakdown["periods"]]
    assert [th["data-period"] for th in columns] == [key(p) for p in breakdown["periods"]]
    meta = words(node.select_one(".bd-meta"))
    assert breakdown["concept"] in meta and breakdown["axis"] in meta


def check_cells(tr: Tag, values: list[dict[str, Any]], periods: list[dict[str, Any]], where: str) -> None:
    by_period = {key(v): v for v in values}
    cells = tr.select("td.bd-cell")
    assert [td["data-period"] for td in cells] == [key(p) for p in periods], where
    for period, td in zip(periods, cells, strict=True):
        value = by_period.get(key(period))
        here = f"{where}, {period['label']}"
        if value is None:
            assert td.select_one(".bd-display") is None and visible(td) == "", f"{here}: should be empty, shows {visible(td)!r}"
            continue
        assert text(td.select_one(".bd-display")) == value["display"], here
        change = td.select_one(".bd-change-display")
        if value["change_display"]:
            assert change is not None and text(change) == value["change_display"], here
        else:
            assert change is None, f"{here}: shows a change the record lacks"
        formula = td.select_one(".bd-formula")
        if value["change_formula"]:
            assert formula is not None and text(formula) == value["change_formula"], here
        else:
            assert formula is None, here


@pytest.mark.parametrize("index", range(5))
def test_every_cell_is_the_records_display_and_change_in_its_column(index: int) -> None:
    breakdown = breakdowns()[index]
    rows = section(breakdown).select("tbody > tr")
    assert [tr["data-member"] for tr in rows] == [r["member"] for r in breakdown["rows"]]
    for record_row, tr in zip(breakdown["rows"], rows, strict=True):
        assert text(tr.select_one("th.bd-label")) == record_row["label"]
        check_cells(tr, record_row["values"], breakdown["periods"], f"{breakdown['id']} {record_row['label']}")


def test_a_row_lacking_a_period_shows_an_empty_cell() -> None:
    seen = 0
    for breakdown in breakdowns():
        for record_row, tr in zip(breakdown["rows"], section(breakdown).select("tbody > tr"), strict=True):
            have = {key(v) for v in record_row["values"]}
            for period, td in zip(breakdown["periods"], tr.select("td.bd-cell"), strict=True):
                if key(period) not in have:
                    seen += 1
                    assert "bd-empty" in td["class"] and visible(td) == "", f"{record_row['label']} {period['label']}"
    assert seen, "the sample needs a row with a missing period"


@pytest.mark.parametrize("index", range(5))
def test_total_row_is_the_records(index: int) -> None:
    breakdown = breakdowns()[index]
    total = section(breakdown).select("tfoot tr.bd-total")
    if not breakdown["total"]:
        assert total == [], f"{breakdown['id']}: a total row the record lacks"
        return
    assert len(total) == 1
    check_cells(total[0], breakdown["total"], breakdown["periods"], f"{breakdown['id']} total")


def test_adds_up_shows_the_right_one_of_three_states() -> None:
    states = set()
    for breakdown in breakdowns():
        state, words_shown = ADDS_UP[breakdown["adds_up"]]
        states.add(breakdown["adds_up"])
        line = section(breakdown).select_one("[data-adds-up]")
        assert line is not None, breakdown["id"]
        assert line["data-adds-up"] == state, breakdown["id"]
        assert f"bd-adds-{state}" in line["class"]
        said = copy.copy(line)
        for glyph in said.select(".glyph"):
            glyph.decompose()
        assert visible(said).startswith(words_shown), visible(said)
        assert (line.select_one(".g-limit") is not None) == (state == "no"), "only 'no' carries the limit mark"
    assert states == {True, None}, "the sample has true and null"


def test_facts_line_is_the_records_two_numbers() -> None:
    line = page().select_one("#breakdowns-body .bd-facts")
    shown = {span["data-bd-field"]: text(span) for span in line.select("[data-bd-field]")}
    assert shown == {"facts_read": f"{report()['facts_read']:,}", "facts_unparsed": f"{report()['facts_unparsed']:,}"}


def test_message_first_links_the_filing_and_says_what_this_is_not() -> None:
    body = page().select_one("#breakdowns-body")
    first, second = body.find_all("p", recursive=False)[:2]
    filing = report()["filing"]
    link = first.select_one("a.ext")
    assert link is not None and link["href"] == filing["url"]
    for part in (filing["form"], filing["period_end"], filing["filed_date"]):
        assert part in words(link), part
    said = words(second)
    assert "derived from tag names" in said and "not the company's own" in said and "by a person" in said
    assert second.select_one(".rule-mark .g-rule") is not None, "the view lacks the fixed-rule mark"
    assert len(body.select("#breakdowns-notes li.mark-limit")) == len(report()["notes"])


def test_no_placeholder_text() -> None:
    soup = page()
    for node in soup.find_all(string=True):
        if node.parent and node.parent.name in ("script", "style"):
            continue
        for bad in PLACEHOLDERS:
            assert bad not in node, f"text {node.strip()[:80]!r} contains {bad!r}"
    for tag in soup.find_all(attrs={"title": True}):
        for bad in PLACEHOLDERS:
            assert bad not in tag["title"], f"title {tag['title'][:80]!r} contains {bad!r}"


def test_first_screen_has_the_third_sample_link() -> None:
    soup = static_page()
    link = soup.select_one("#breakdowns-link")
    assert link is not None and link["href"] == "?sample=breakdowns"
    assert link.find_parent(id="sample-nav") is not None, "the link is not beside the other two samples"
    assert soup.select_one("#takeaway").parent in link.parents


# A value under the wrong period is a wrong result. The recorded sample cannot show it: every
# value it lacks is in the oldest column. The gap sample lacks one in the middle.


def test_a_value_missing_in_the_middle_leaves_that_column_empty_and_moves_nothing() -> None:
    web = Path(__file__).resolve().parents[1] / "src" / "web"
    dump = Path(__file__).resolve().parents[1] / "results" / "dom-breakdowns-gap.html"
    require_fresh(dump, web / "sample-breakdowns-gap.json")
    gap = json.loads((web / "sample-breakdowns-gap.json").read_text(encoding="utf-8"))["report"]
    product = next(b for b in gap["breakdowns"] if b["id"] == "revenue_by_product")
    record_row = next(r for r in product["rows"] if r["label"] == "Gaming")
    assert len(record_row["values"]) == len(product["periods"]) - 1 == 2
    soup = BeautifulSoup(dump.read_text(encoding="utf-8"), "html.parser")
    section = soup.select_one('#breakdowns-body section[data-breakdown-id="revenue_by_product"]')
    assert section is not None, "the gap sample did not render"
    (tr,) = [row for row in section.select("tbody > tr") if row["data-member"] == record_row["member"]]
    check_cells(tr, record_row["values"], product["periods"], "revenue_by_product / Gaming")
    cells = tr.select("td.bd-cell")
    assert cells[1].select_one(".bd-display") is None, "the middle column should be empty"
    assert text(cells[2].select_one(".bd-display")) == record_row["values"][1]["display"]

