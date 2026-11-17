"""Browser-level checks of the run view's "Changed in the filings since the one before" blocks.

`make uitest` renders /?sample, which loads src/web/sample-run.json and, beside it,
src/web/sample-run-changes.json (a RunChanges record), and dumps the DOM to
results/dom-sample.html. These tests compare what the page drew with that record:
each claim's counts, entries, marks, shared words and the filings compared. The
synthetic sample has no such record, so its dump must show none of it.
"""

from __future__ import annotations

import json
import re
from functools import cache
from pathlib import Path
from typing import Any

import pytest
from bs4 import BeautifulSoup, Tag
from test_dom import DECISION_GLYPHS, MEANING_GLYPHS, STANCE_GLYPHS, VERDICT_GLYPHS, page, require_fresh

ROOT = Path(__file__).resolve().parents[1]
WEB = ROOT / "src" / "web"
RESULTS = ROOT / "results"
CHANGES = WEB / "sample-run-changes.json"

# Pinned here, so a swapped mark fails: the comparison view's change family, and the rule mark.
CHANGE_GLYPHS = {"added": "+", "removed": "−", "reworded": "~", "numbers_only": "#"}
RULE_GLYPH = "ƒ"
JUDGING_GLYPHS = set(VERDICT_GLYPHS.values()) | set(STANCE_GLYPHS.values()) | set(DECISION_GLYPHS.values()) | set(MEANING_GLYPHS.values())
JUDGING_CLASSES = {"pill", "verdict", "stance", "decision-mark", "meaning-mark", "badge-model"}
WHY = "no model chose or judged them, they are not findings, and none counts toward the verdict"


@cache
def changes() -> dict[str, Any]:
    """The RunChanges record the sample page loaded."""
    return json.loads(CHANGES.read_text(encoding="utf-8"))["changes"]


@cache
def soup() -> BeautifulSoup:
    require_fresh(RESULTS / "dom-sample.html", CHANGES)
    return page("run")


def text(node: Tag) -> str:
    return node.get_text()


def words(node: Tag) -> str:
    return " ".join(text(node).split())


def block(claim_id: str) -> Tag:
    node = soup().select_one(f'#claim-list [data-claim-changes="{claim_id}"]')
    assert node is not None, f"{claim_id}: no changed-paragraphs block"
    return node


def claims() -> list[dict[str, Any]]:
    return changes()["claims"]


def test_record_is_for_the_sample_run() -> None:
    run = json.loads((WEB / "sample-run.json").read_text(encoding="utf-8"))["run"]
    assert changes()["run_id"] == run["id"]
    assert [c["claim_id"] for c in claims()] == [c["id"] for c in run["claims"]]


@pytest.mark.parametrize("index", range(5))
def test_counts_line_equals_the_records_three_numbers(index: int) -> None:
    claim = claims()[index]
    node = block(claim["claim_id"])
    assert node.name == "details" and not node.has_attr("open"), "the block must start collapsed"
    assert f"{len(claim['changes']):,} paragraph" in words(node.select_one("summary"))
    counts = node.select_one(".cc-counts")
    assert counts is not None, f"{claim['claim_id']}: no counts line"
    shown = {span["data-cc-field"]: text(span) for span in counts.select("[data-cc-field]")}
    expected = {"listed": len(claim["changes"]), "distinct_matched": claim["distinct_matched"], "considered": claim["considered"]}
    assert shown == {field: f"{value:,}" for field, value in expected.items()}
    assert "share at least two words with this claim" in words(counts)


def entries(claim_id: str) -> list[Tag]:
    return block(claim_id).select("ol.cc-list > li.cc-entry")


def test_c4_first_entry_is_the_records_added_paragraph() -> None:
    first = next(c for c in claims() if c["claim_id"] == "c4")["changes"][0]
    assert first["kind"] == "added" and first["paragraph"]["text"].startswith("Gross margin decreased")
    entry = entries("c4")[0]
    assert entry["data-change-kind"] == "added"
    mark = entry.select_one(".cc-where .chg-mark")
    assert "c-added" in mark["class"] and text(mark.select_one(".g-chg")) == CHANGE_GLYPHS["added"]
    assert text(entry.select_one(".chg-text")) == first["paragraph"]["text"]
    assert text(entry.select_one(".cc-form")) == first["form"] and text(entry.select_one(".cc-item")) == first["item"]


def test_every_entry_in_record_order_with_its_mark_terms_and_also_under() -> None:
    seen_also = 0
    for claim in claims():
        shown = entries(claim["claim_id"])
        assert len(shown) == len(claim["changes"]), claim["claim_id"]
        for change, entry in zip(claim["changes"], shown, strict=True):
            where = f"{claim['claim_id']} {change['kind']} {change['item']}"
            assert entry["data-change-kind"] == change["kind"], where
            assert text(entry.select_one(".cc-where .g-chg")) == CHANGE_GLYPHS[change["kind"]], where
            assert [text(t) for t in entry.select(".cc-term")] == change["matched_terms"], where
            also = entry.select_one(".cc-also")
            if change["also_under"]:
                seen_also += 1
                assert also is not None, f"{where}: also_under not shown"
                assert words(also) == "· also under " + "; ".join(change["also_under"]), where
            else:
                assert also is None, f"{where}: shows an also-under the record lacks"
    assert seen_also, "the sample needs an entry with also_under"


def test_a_pair_is_drawn_as_in_the_comparison_view() -> None:
    for claim in claims():
        for change, entry in zip(claim["changes"], entries(claim["claim_id"]), strict=True):
            if change["kind"] not in ("reworded", "numbers_only"):
                continue
            segments = change["pair"]["segments"]
            assert len(entry.select("ins.seg-add")) == sum(s["kind"] == "added" for s in segments)
            assert len(entry.select("del.seg-del")) == sum(s["kind"] == "removed" for s in segments)
            links = [a["href"] for a in entry.select("a.ext")]
            assert links == [change["pair"]["after"]["link"], change["pair"]["before"]["link"]]
            return
    pytest.fail("the sample needs a reworded or numbers-only entry")


def test_no_finding_mark_inside_any_block() -> None:
    nodes = [block(c["claim_id"]) for c in claims()] + [soup().select_one("#run-filing-changes")]
    for node in nodes:
        for inner in node.find_all(True):
            assert not set(inner.get("class") or []) & JUDGING_CLASSES, f"a finding's mark inside: {inner.get('class')}"
        glyphs = {text(g).strip() for g in node.select(".glyph")}
        assert not glyphs & JUDGING_GLYPHS, f"a verdict, stance, decision or meaning glyph inside: {glyphs & JUDGING_GLYPHS}"
        assert glyphs <= set(CHANGE_GLYPHS.values()) | {RULE_GLYPH}, glyphs
        assert text(node.select_one(".rule-mark .g-rule")) == RULE_GLYPH, "the block lacks the fixed-rule mark"
        assert WHY in words(node), "the block does not say why these are listed"


def test_compared_block_names_both_forms_and_both_pairs_of_period_ends() -> None:
    top = soup().select_one("#run-filing-changes")
    assert top is not None and not top.has_attr("hidden")
    pairs = top.select("ul.cc-pairs > li[data-form]")
    assert [li["data-form"] for li in pairs] == [c["form"] for c in changes()["compared"]]
    assert {c["form"] for c in changes()["compared"]} == {"10-K", "10-Q"}
    for compared, li in zip(changes()["compared"], pairs, strict=True):
        said = words(li)
        assert said.startswith(f"{compared['form']}:")
        for side in ("later", "earlier"):
            assert f"period ended {compared[side]['period_end']}" in said, f"{compared['form']} {side}"
        assert [a["href"] for a in li.select("a.ext")] == [compared["later"]["url"], compared["earlier"]["url"]]
    notes = changes()["notes"]
    assert len(top.select(".cc-notes li")) == len(notes)


def test_synthetic_sample_shows_no_such_block() -> None:
    synthetic = page("synthetic")
    assert synthetic.select("[data-claim-changes]") == []
    top = synthetic.select_one("#run-filing-changes")
    assert top is not None and top.has_attr("hidden") and not top.contents
    assert all(not slot.contents for slot in synthetic.select("[data-cc-slot]"))


def test_both_download_links_ask_for_the_changes() -> None:
    """Sample mode draws no download link, so this reads app.js: every brief URL is built by
    briefHref, which always sets changes=true, and both download links use it."""
    source = (WEB / "app.js").read_text(encoding="utf-8")
    assert source.count("export.md") == 1, "a brief URL is built outside briefHref"
    body = re.search(r"function briefHref\(runId, reviewed\) \{(.*?)\n\}", source, re.S)
    assert body is not None
    code = re.sub(r"//.*", "", body.group(1))
    assert re.search(r'^\s*query\.set\("changes", "true"\);', code, re.M), "the brief URL does not ask for the changes"
    assert 'if (reviewed) query.set("reviewed", "true")' in code
    downloads = re.findall(r'class: "download", href: (\S+ \S+?\)),', source)
    assert sorted(downloads) == ["briefHref(run.id, false)", "briefHref(run.id, true)"]


# The deep link: /?sample#claim-c4-changes opens that claim's block (and scrolls to it, which a
# DOM dump cannot show and the headless browser cannot capture: it paints nothing after a scroll).


@cache
def linked() -> BeautifulSoup:
    dump = RESULTS / "dom-sample-claim.html"
    require_fresh(dump, CHANGES)
    return BeautifulSoup(dump.read_text(encoding="utf-8"), "html.parser")


def test_the_deep_link_opens_that_claims_block_and_no_other() -> None:
    opened = {
        node["data-claim-changes"]: node.has_attr("open") or node.select_one("details[open]") is not None
        for node in linked().select("#claim-list [data-claim-changes]")
    }
    assert set(opened) == {found["claim_id"] for found in changes()["claims"]}
    assert opened["c4"], "the block named in the hash is not open"
    assert not any(is_open for claim_id, is_open in opened.items() if claim_id != "c4")


def test_without_the_hash_no_block_is_open() -> None:
    for node in soup().select("#claim-list [data-claim-changes]"):
        assert not node.has_attr("open") and node.select_one("details[open]") is None

