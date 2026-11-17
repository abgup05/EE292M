"""Browser-level checks of what changed between two filings, against the record the page was given.

`make uitest` renders /?sample=changes in headless Chromium and writes the resulting DOM to
results/dom-changes.html; these tests read it and src/web/sample-changes.json (a recorded
FilingChanges for two annual reports). They check what a reader sees: the totals and each
Item's counts, the paragraphs added and removed with links into the right filing, the words
a reworded paragraph added and dropped, truncated lists, and the change marks in the legend.
"""

from __future__ import annotations

import copy
import json
import re
from functools import cache
from pathlib import Path
from typing import Any

import pytest
from bs4 import BeautifulSoup, Tag
from test_dom import require_fresh

ROOT = Path(__file__).resolve().parents[1]
WEB = ROOT / "src" / "web"
DOM = ROOT / "results" / "dom-changes.html"

# Pinned here, not read from app.js or index.html, so a swapped glyph fails.
CHANGE_GLYPHS = {"numbers_only": "#", "reworded": "~", "added": "+", "removed": "−"}
CHANGE_LABELS = {"numbers_only": "Numbers only", "reworded": "Reworded", "added": "Added", "removed": "Removed"}
# Every mark the run pages already use: the change family must take none of them.
OTHER_GLYPHS = {"✓", "✕", "±", "?", "∅", "•", "▲", "✎", "◎", "◐", "!", "▣", "☒", "☐"}
# The five paragraph counts, then the four for short lines and table rows: every line of each
# filing is in exactly one of them.
COUNTS = ("unchanged", "numbers_only", "reworded", "added", "removed")
MINOR = ("minor_unchanged", "minor_numbers_only", "minor_added", "minor_removed")
LISTS = {
    "added": "added_paragraphs",
    "removed": "removed_paragraphs",
    "reworded": "reworded_paragraphs",
    "numbers_only": "numbers_only_paragraphs",
}
SUBHEADINGS = {"later": ("subheadings_added", "added"), "earlier": ("subheadings_removed", "removed")}
PLACEHOLDERS = ("undefined", "NaN", "[object Object]", "null")


@cache
def sample() -> dict[str, Any]:
    """The sample file the page loaded: {"note", "changes"}."""
    return json.loads((WEB / "sample-changes.json").read_text(encoding="utf-8"))


def record() -> dict[str, Any]:
    return sample()["changes"]


@cache
def page() -> BeautifulSoup:
    """The DOM the headless browser dumped after the page rendered the comparison."""
    require_fresh(DOM, WEB / "sample-changes.json")
    soup = BeautifulSoup(DOM.read_text(encoding="utf-8"), "html.parser")
    view = soup.select_one("#changes-view")
    if view is None or view.has_attr("hidden"):
        pytest.fail(f"{DOM.name}: the page did not render the comparison (is the sample file served?)")
    return soup


def text(node: Tag) -> str:
    return node.get_text()


def words(node: Tag) -> str:
    return " ".join(text(node).split())


def visible_text(node: Tag) -> str:
    """The node's text without the visually hidden words meant for screen readers."""
    clone = copy.copy(node)
    for hidden in clone.select(".visually-hidden"):
        hidden.decompose()
    return text(clone)


def rows() -> list[Tag]:
    return page().select("#changes-body details.chg-item")


def row_and_item(prefix: str) -> tuple[Tag, dict[str, Any]]:
    items = record()["items"]
    index = next(i for i, item in enumerate(items) if item["item"].startswith(prefix))
    return rows()[index], items[index]


def rule_body(selector: str) -> str:
    css = re.sub(r"/\*.*?\*/", "", (WEB / "styles.css").read_text(encoding="utf-8"), flags=re.S)
    bodies = [body for selectors, body in re.findall(r"([^{}]+)\{([^{}]*)\}", css) if selector in [s.strip() for s in selectors.split(",")]]
    assert bodies, f"styles.css has no rule for {selector}"
    return " ".join(bodies)


def test_the_message_comes_first_and_names_both_filings() -> None:
    later, earlier = record()["later"], record()["earlier"]
    soup = page()
    lead = soup.select_one("#changes-body .changes-lead")
    assert lead is not None, "no sentence says what is compared"
    said = words(lead)
    assert said.index(later["period_end"]) < said.index(earlier["period_end"]), "the later filing comes first"
    for side in (later, earlier):
        assert side["form"] in said and side["filed_date"] in said
    assert [a["href"] for a in lead.select("a.ext")] == [later["url"], earlier["url"]]
    body = text(soup.select_one("#changes-body"))
    assert body.index(text(lead)) < body.index("All Items"), "the totals come after the message"
    assert "does not know why anything changed" in words(soup.select_one("#changes-body .changes-unknown"))
    explained = words(soup.select_one("#changes-body .changes-explain"))
    for phrase in ("The five counts are of paragraphs", "counted apart", "never listed", "exactly one count", "A sub-heading is not a line"):
        assert phrase in explained, f"the explanation does not say {phrase!r}"
    head = soup.select_one("#changes-head")
    assert head.select_one(".page-tag") is not None and "Sample record" in text(head.select_one(".page-tag"))
    assert sample()["note"] in words(head)


def test_totals_equal_the_record() -> None:
    totals = record()["totals"]
    for field in COUNTS + MINOR:
        node = page().select_one(f'#changes-body [data-chg-total="{field}"]')
        assert node is not None, f"the totals do not show {field}"
        assert text(node) == f"{totals[field]:,}", f"{field}: shows {text(node)!r}"


def test_each_item_row_shows_its_counts() -> None:
    items = record()["items"]
    assert len(rows()) == len(items)
    for item, row in zip(items, rows(), strict=True):
        assert row["data-item"] == item["item"]
        summary = row.select_one("summary")
        assert text(summary.select_one(".chg-item-title")) == item["item"]
        for field in COUNTS + MINOR:
            node = summary.select_one(f'[data-chg-field="{field}"]')
            assert node is not None and text(node) == f"{item[field]:,}", f"{item['item']}: {field}"
        presence = summary.select_one(".chg-presence")
        if item["present_in"] == "both":
            assert presence is None, f"{item['item']} is in both filings"
        else:
            assert presence is not None and presence["data-present-in"] == item["present_in"]


@pytest.mark.parametrize(("kind", "side"), [("added", "later"), ("removed", "earlier")])
def test_item_1a_paragraphs_link_into_their_own_filing(kind: str, side: str) -> None:
    row, item = row_and_item("Item 1A")
    first = item[LISTS[kind]][0]
    entry = row.select_one(f'.chg-list[data-list="{kind}"] ol.chg-paras > li')
    assert entry is not None, f"Item 1A shows no {kind} paragraph"
    assert text(entry.select_one(".chg-text")) == first["text"]
    link = entry.select_one("a.ext")
    assert link is not None, f"the first {kind} paragraph has no link"
    other = "earlier" if side == "later" else "later"
    assert record()[side]["url"] != record()[other]["url"]
    assert link["href"].startswith("https://www.sec.gov/"), link["href"]
    assert link["href"].startswith(record()[side]["url"]), f"a {kind} paragraph must open the {side} filing"
    assert link["href"] == first["link"]


def test_a_reworded_paragraph_marks_added_and_removed_words() -> None:
    for item, row in zip(record()["items"], rows(), strict=True):
        pairs = item["reworded_paragraphs"]
        position = next((i for i, p in enumerate(pairs) if {"added", "removed"} <= {s["kind"] for s in p["segments"]}), None)
        if position is not None:
            break
    else:
        pytest.fail("the record has no reworded paragraph with both added and removed words")
    pair = pairs[position]
    entries = row.select('.chg-list[data-list="reworded"] ol.chg-paras > li')
    assert_segments(entries[position], pair)
    similarity = entries[position].select_one("[data-similarity]")
    assert similarity is not None and float(text(similarity)) == pair["similarity"]
    assert "underline" in rule_body("ins.seg-add") and "line-through" in rule_body("del.seg-del")


def assert_segments(entry: Tag, pair: dict[str, Any]) -> None:
    """The entry draws the pair's segments in reading order, added words in <ins>, removed in <del>."""
    quote = entry.select_one("blockquote.chg-reworded")
    assert quote is not None, "the pair is not drawn from its segments"
    added = [visible_text(node) for node in quote.select("ins.seg-add")]
    removed = [visible_text(node) for node in quote.select("del.seg-del")]
    assert added == [s["text"] for s in pair["segments"] if s["kind"] == "added"]
    assert removed == [s["text"] for s in pair["segments"] if s["kind"] == "removed"]
    assert not quote.select("ins.seg-del, del.seg-add"), "an added word marked as removed, or the reverse"
    assert visible_text(quote) == " ".join(s["text"] for s in pair["segments"]), "segments out of reading order"


def test_a_numbers_only_pair_marks_the_figures_that_moved() -> None:
    for item, row in zip(record()["items"], rows(), strict=True):
        pairs = item["numbers_only_paragraphs"]
        position = next((i for i, p in enumerate(pairs) if {"added", "removed"} <= {s["kind"] for s in p["segments"]}), None)
        if position is not None:
            break
    else:
        pytest.fail("the record has no numbers-only pair with both added and removed figures")
    section = row.select_one('.chg-list[data-list="numbers_only"]')
    assert section is not None, f"{item['item']}: no numbers-only list"
    title = section.select_one(".chg-list-title")
    assert text(title.select_one(".chg-mark.c-numbers_only .g-chg")) == CHANGE_GLYPHS["numbers_only"]
    assert "Numbers only: the same words, the figures that moved" in words(title)
    entry = section.select("ol.chg-paras > li")[position]
    assert_segments(entry, pairs[position])
    assert entry.select_one("[data-similarity]") is None, "a numbers-only pair shows a similarity"
    hrefs = [a["href"] for a in entry.select("a.ext")]
    assert hrefs == [pairs[position]["after"]["link"], pairs[position]["before"]["link"]], "both links, later then earlier"


@pytest.mark.parametrize("side", list(SUBHEADINGS))
def test_subheadings_in_one_filing_only_are_named_under_their_item(side: str) -> None:
    key, kind = SUBHEADINGS[side]
    for item, row in zip(record()["items"], rows(), strict=True):
        section = row.select_one(f'[data-subheadings="{side}"]')
        if not item[key]:
            assert section is None, f"{item['item']}: an empty {side} sub-heading list is shown"
            continue
        assert section is not None, f"{item['item']}: the {side} sub-headings are not named"
        assert text(section.select_one(".chg-mark .g-chg")) == CHANGE_GLYPHS[kind], f"{item['item']}: not the {kind} mark"
        assert [text(li) for li in section.select("li")] == item[key], item["item"]
        lists = row.select(".chg-lists > section")
        assert lists.index(section) < len(lists) - sum(bool(item[k]) for k in LISTS.values()), "sub-headings come first"


def test_item_1_business_names_its_seven_removed_subheadings() -> None:
    row, item = row_and_item("Item 1. ")
    names = item["subheadings_removed"]
    assert len(names) == 7, "the sample's Item 1 has seven sub-headings only in the earlier filing"
    section = row.select_one('[data-subheadings="earlier"]')
    assert section is not None and [text(li) for li in section.select("li")] == names


def link_entries() -> list[tuple[dict[str, Any], str, Tag]]:
    """Every paragraph link in the view with the record's paragraph it opens: (paragraph, side, <a>)."""
    found = []
    for item, row in zip(record()["items"], rows(), strict=True):
        for kind, side in (("added", "later"), ("removed", "earlier")):
            entries = row.select(f'.chg-list[data-list="{kind}"] ol.chg-paras > li')
            for paragraph, entry in zip(item[LISTS[kind]], entries, strict=True):
                found.append((paragraph, side, entry.select_one("a.ext")))
        for kind in ("reworded", "numbers_only"):
            entries = row.select(f'.chg-list[data-list="{kind}"] ol.chg-paras > li')
            for pair, entry in zip(item[LISTS[kind]], entries, strict=True):
                later_link, earlier_link = entry.select("a.ext")
                found += [(pair["after"], "later", later_link), (pair["before"], "earlier", earlier_link)]
    return found


def test_link_words_say_what_each_link_opens() -> None:
    seen = set()
    for paragraph, side, link in link_entries():
        assert link is not None and link["href"] == paragraph["link"]
        said = str(link.contents[0])
        kind = paragraph.get("link_kind") or ""
        seen.add(kind)
        assert f"the {side} filing" in said, f"{said!r} does not name the {side} filing"
        if kind == "document":
            assert "at this paragraph" not in said and "cannot be located" in said, said
        elif kind == "first-line":
            assert "at its first line" in said, said
        else:
            assert "at this paragraph" in said, said
    assert {"document", "passage"} <= seen, "the sample needs both a document link and a passage link"


def test_item_1a_starts_open() -> None:
    opened = [row["data-item"] for row in rows() if row.has_attr("open")]
    assert len(opened) == 1 and opened[0].startswith("Item 1A"), opened


def test_truncated_lists_say_how_many_they_show() -> None:
    seen = 0
    for item, row in zip(record()["items"], rows(), strict=True):
        for kind, key in LISTS.items():
            node = row.select_one(f'[data-truncated="{kind}"]')
            if not item["truncated"][kind]:
                assert node is None, f"{item['item']}: {kind} is not truncated"
                continue
            seen += 1
            assert node is not None, f"{item['item']}: the truncated {kind} list does not say so"
            expected = f"showing the first {len(item[key]):,} of {item[kind]:,}"
            assert expected in words(node), f"{item['item']}: {words(node)!r}, expected {expected!r}"
            assert len(row.select(f'.chg-list[data-list="{kind}"] ol.chg-paras > li')) == len(item[key])
    assert seen, "the sample needs a truncated list"


def test_legend_has_the_change_marks() -> None:
    legend = page().select_one("#changes-legend")
    assert legend is not None, "the comparison has no legend"
    shown = {}
    for mark in legend.select(".chg-mark"):
        kind = next(c[2:] for c in mark["class"] if c.startswith("c-"))
        shown[kind] = (text(mark.select_one(".g-chg")), text(mark.select_one(".chg-label")))
    assert shown == {kind: (CHANGE_GLYPHS[kind], CHANGE_LABELS[kind]) for kind in CHANGE_GLYPHS}
    assert legend.select_one("ins.seg-add") is not None and legend.select_one("del.seg-del") is not None
    assert not set(CHANGE_GLYPHS.values()) & OTHER_GLYPHS, "a change mark reuses another family's glyph"
    body = rule_body(".chg-mark")
    assert "--change" in body
    for colour in ("--support", "--challenge", "--limit", "--model", "--reject", "--accent", "--neutral"):
        assert colour not in body, f".chg-mark uses {colour}"
    for node in page().select("#changes-body .g-chg"):
        assert text(node) in CHANGE_GLYPHS.values(), f"an unknown change glyph {text(node)!r}"


RULE_GLYPH = "ƒ"
RULE_MEANING = "Computed by a fixed rule; not checked by a person"


def test_rule_mark_is_defined_once_and_sits_on_the_classification() -> None:
    """Review 5, interface finding 4: what only a fixed rule decided carries its own mark."""
    soup = page()
    defined = [mark.find_parent("div") for mark in soup.select("#changes-legend .rule-mark")]
    assert len(defined) == 1, "the comparison's legend must define the fixed-rule mark exactly once"
    assert text(defined[0].select_one(".g-rule")) == RULE_GLYPH
    assert RULE_MEANING in words(defined[0])
    assert RULE_GLYPH not in OTHER_GLYPHS | set(CHANGE_GLYPHS.values()), "the rule mark reuses another glyph"
    # On the classification: the All Items totals and the per-Item counts and lists.
    for where in ("totals", "items"):
        note = soup.select_one(f'#changes-body .rule-note[data-rule="{where}"]')
        assert note is not None, f"the {where} carry no fixed-rule mark"
        assert text(note.select_one(".rule-mark .g-rule")) == RULE_GLYPH
    totals_title = soup.select_one("#chg-totals-title")
    assert totals_title.find_next("p", class_="rule-note")["data-rule"] == "totals"
    items_title = soup.select_one("#chg-items-title")
    assert items_title.find_next("p", class_="rule-note")["data-rule"] == "items"
    body = rule_body(".rule-mark")
    assert "--rule" in body and "dotted" in body
    for colour in ("--support", "--challenge", "--limit", "--model", "--reject", "--accent", "--neutral", "--change", "--ink"):
        assert re.search(rf"var\({colour}\)", body) is None, f".rule-mark uses {colour}"


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
