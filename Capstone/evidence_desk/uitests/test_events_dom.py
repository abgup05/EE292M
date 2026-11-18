"""Browser-level checks of the 8-Ks since the annual report and the as-of line (version 12).

`make uitest` renders the recorded sample runs (/?sample, /?sample=run-tagged), whose replayed
EDGAR lists NVIDIA's 8-Ks filed after its 10-K, and the synthetic sample, a record without an
as-of block, as a run from before version 12 has. These tests compare each dump with its
JSON: the as-of line, the counts line, and every 8-K in the record's order with its date,
form, link, kind, status, items, categories, opening sentences and roles. The page computes
none of these; each is a record field or wording from /api/meta.
"""

from __future__ import annotations

import json
from functools import cache
from pathlib import Path
from typing import Any

import pytest
from bs4 import BeautifulSoup, Tag
from test_dom import require_fresh

ROOT = Path(__file__).resolve().parents[1]
WEB = ROOT / "src" / "web"
RESULTS = ROOT / "results"
RUNS = {
    "run": ("sample-run.json", "dom-sample.html"),
    "run-tagged": ("sample-run-tagged.json", "dom-run-tagged.html"),
}
both = pytest.mark.parametrize("name", sorted(RUNS))


@cache
def sample(name: str) -> dict[str, Any]:
    return json.loads((WEB / RUNS[name][0]).read_text(encoding="utf-8"))


@cache
def page(name: str) -> BeautifulSoup:
    dump = RESULTS / RUNS[name][1]
    require_fresh(dump, WEB / RUNS[name][0])
    soup = BeautifulSoup(dump.read_text(encoding="utf-8"), "html.parser")
    if soup.select_one("#run-view") is None or soup.select_one("#run-view[hidden]") is not None:
        pytest.fail(f"{dump.name}: the page did not render the run")
    return soup


def words(node: Tag) -> str:
    return " ".join(node.get_text().split())


@both
def test_the_record_has_a_timeline_to_show(name: str) -> None:
    run = sample(name)["run"]
    assert run["as_of"] is not None and len(run["timeline"]) >= 1


@both
def test_the_as_of_line_is_the_records(name: str) -> None:
    line = page(name).select_one("#run-head [data-as-of]")
    assert line is not None
    assert sample(name)["run"]["as_of"]["line"] in words(line)
    assert line.select_one('a[href="#events-section"]') is not None


@both
def test_the_panel_has_metas_heading_and_note_and_the_records_counts(name: str) -> None:
    soup, record = page(name), sample(name)
    section = soup.select_one("#events-section")
    assert section is not None and not section.has_attr("hidden")
    assert words(section.select_one("#events-title")) == record["meta"]["events"]["heading"]
    assert record["meta"]["events"]["note"] in words(section)
    counts = section.select_one("[data-event-counts]")
    assert counts is not None and words(counts) == record["run"]["as_of"]["counts"]["line"]


@both
def test_every_8k_is_shown_in_the_records_order_with_its_fields(name: str) -> None:
    soup, record = page(name), sample(name)
    labels = record["meta"]["events"]
    shown = soup.select("#events-section li.event")
    timeline = record["run"]["timeline"]
    assert [node["data-event-id"] for node in shown] == [event["id"] for event in timeline]
    for node, event in zip(shown, timeline, strict=True):
        assert node.get("id") == f"event-{event['id']}"
        kind = "substantive" if event["substantive"] else "routine"
        assert f"ev-{kind}" in node["class"]
        assert words(node.select_one("[data-event-kind]")) == labels["kind_labels"][kind]
        assert words(node.select_one("[data-event-status]")) == labels["status_labels"][event["status"]]
        head = words(node.select_one(".event-head"))
        assert event["filed_label"] in head and event["accession"] in head
        assert node.select_one(".event-head a")["href"] == event["url"]
        rows = node.select("li.event-item")
        assert [row["data-item"] for row in rows] == [item["number"] for item in event["items"]]
        for row, item in zip(rows, event["items"], strict=True):
            assert f"Item {item['number']}. {item['title']}" in words(row)
            category = row.select_one("[data-category]")
            assert words(category) == labels["category_labels"][item["category"]]
            quote = row.select_one("blockquote.event-opening")
            if item["opening"]:
                assert [words(p) for p in quote.select("p")] == [
                    " ".join(s.split()) for s in item["opening"]
                ]
                assert row.select_one(".event-link a")["href"] == event["url"]
            else:
                assert quote is None
            roles = row.select_one("[data-event-roles]")
            if item["roles"]:
                assert words(roles).endswith("Roles named: " + ", ".join(item["roles"]))
            else:
                assert roles is None


def test_the_resignation_is_shown_substantive_with_its_opening_sentence() -> None:
    node = page("run").select_one('li.event[data-event-id="ev-0001045810-26-000082"]')
    assert node is not None and "ev-substantive" in node["class"]
    assert "accepted the resignation of Jen-Hsun Huang" in words(node)


@both
def test_no_claim_or_finding_shows_an_8k_mark_the_record_does_not_carry(name: str) -> None:
    soup, run = page(name), sample(name)["run"]
    cautions = {c["id"] for c in run["claims"] if c["caution"]}
    notes = {c["id"] for c in run["claims"] if c["event_note"]}
    marks = {(f["id"], m["event_id"]) for f in run["findings"] for m in f["predated_by"]}
    assert {n["data-claim-caution"] for n in soup.select("[data-claim-caution]")} == cautions
    assert {n["data-claim-event-note"] for n in soup.select("[data-claim-event-note]")} == notes
    shown = {
        (n.find_parent("article")["data-finding-id"], n["data-predated-by"])
        for n in soup.select("#claim-list [data-predated-by]")
    }
    assert shown == marks


def test_a_record_without_an_as_of_block_shows_no_panel_and_no_line() -> None:
    dump = RESULTS / "dom-synthetic.html"
    require_fresh(dump, WEB / "sample-synthetic.json")
    soup = BeautifulSoup(dump.read_text(encoding="utf-8"), "html.parser")
    assert json.loads((WEB / "sample-synthetic.json").read_text())["run"].get("as_of") is None
    assert soup.select_one("#events-section").has_attr("hidden")
    assert soup.select_one("[data-as-of]") is None
