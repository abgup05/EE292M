"""Browser-level checks of a run that offered the engine the figures tagged in its filings.

`make uitest` renders /?sample=run-tagged, which loads src/web/sample-run-tagged.json
({"note", "meta", "run"}), and dumps the DOM to results/dom-run-tagged.html. These tests
compare that DOM with the record: the run option, the tagged figures' own group, the
offered and cited counts as the record gives them, findings that cite a tagged figure,
and three wordings a referee found untrue, checked in every dump `make uitest` writes.
"""

from __future__ import annotations

import json
import re
from functools import cache
from pathlib import Path
from typing import Any
from urllib.parse import unquote

import pytest
from bs4 import BeautifulSoup, Tag
from test_dom import require_fresh, static_page

ROOT = Path(__file__).resolve().parents[1]
WEB = ROOT / "src" / "web"
RESULTS = ROOT / "results"
DOM = RESULTS / "dom-run-tagged.html"
SAMPLE = WEB / "sample-run-tagged.json"
TAGGED = "tagged:"
CAUTION = "The row labels are made from tag names, not taken from the company's own tables, and no person has compared them with the printed tables."
RULE_GLYPH = "ƒ"

# Review of milestone 10: three sentences that were untrue, and what replaces them.
NEW_WORDINGS = {
    "dom-sample.html": (
        "this claim or the search queries the run wrote for it",
        "Changed since the filing before each one this run read",
        "The earlier filing was fetched for this comparison; the run did not read it.",
    ),
    "dom-breakdowns.html": ("Not tied to any run",),
}
OLD_WORDINGS = (
    re.compile(r"share(?:s)? (?:at least two )?words with (?:this|the) claim(?! or the search queries)"),
    re.compile(r"Changed in the filings (?:since the one before|this run read)"),
    re.compile(r"as one filing tags them"),
)
# Every dump `make uitest` renders; each must have been written after the page last changed.
DUMPS = {
    "dom-synthetic.html": "sample-synthetic.json",
    "dom-sample.html": "sample-run-changes.json",
    "dom-changes.html": "sample-changes.json",
    "dom-breakdowns.html": "sample-breakdowns.json",
    "dom-run-tagged.html": "sample-run-tagged.json",
}


@cache
def run() -> dict[str, Any]:
    return json.loads(SAMPLE.read_text(encoding="utf-8"))["run"]


@cache
def page() -> BeautifulSoup:
    require_fresh(DOM, SAMPLE)
    soup = BeautifulSoup(DOM.read_text(encoding="utf-8"), "html.parser")
    if soup.select_one("#run-view") is None or soup.select_one("#run-view[hidden]") is not None:
        pytest.fail(f"{DOM.name}: the page did not render the run (is the sample file served?)")
    return soup


def text(node: Tag) -> str:
    return node.get_text()


def words(node: Tag) -> str:
    return " ".join(text(node).split())


def tagged_metrics() -> list[dict[str, Any]]:
    return [m for m in run()["metrics"] if m["id"].startswith(TAGGED)]


def group() -> Tag:
    node = page().select_one('#figures section[data-figure-group="tagged"]')
    assert node is not None, "the figures panel has no group of tagged figures"
    return node


def test_sample_is_the_one_described() -> None:
    coverage = run()["coverage"]
    assert run()["inputs"]["tagged_figures"] is True and run()["status"] == "partial"
    assert coverage["tagged_figures_offered"] == len(tagged_metrics()) == 40


@pytest.mark.parametrize("where", ["first screen", "rendered sample"])
def test_the_run_option_exists_and_starts_unchecked(where: str) -> None:
    soup = static_page() if where == "first screen" else page()
    box = soup.select_one("form #tagged_figures")
    assert box is not None and box.get("type") == "checkbox"
    assert not box.has_attr("checked"), "the option must be off by default"
    label = soup.select_one('label[for="tagged_figures"]')
    assert "Also offer the figures tagged in the filings (segments, products, geographies, customers)" in words(label)
    assert "did not answer the same prompt" in words(soup.select_one("#tagged-hint"))


def test_the_tagged_group_holds_exactly_the_figures_offered() -> None:
    rows = group().select("details.fig-row[data-metric-id]")
    assert len(rows) == run()["coverage"]["tagged_figures_offered"]
    assert [row["data-metric-id"] for row in rows] == [m["id"] for m in tagged_metrics()]
    by_id = {m["id"]: m for m in tagged_metrics()}
    for row in rows:
        metric = by_id[row["data-metric-id"]]
        assert text(row.select_one("summary .fig-value")) == metric["display"]
        assert words(row.select_one("summary .fig-label")).startswith(" ".join(metric["label"].split()))
        assert metric["note"] in words(row), f"{metric['id']}: its note is not shown when opened"
    outside = [r for r in page().select("#figures details.fig-row[data-metric-id]") if r.find_parent(attrs={"data-figure-group": "tagged"}) is None]
    assert not [r["data-metric-id"] for r in outside if r["data-metric-id"].startswith(TAGGED)], "a tagged figure sits among the company-facts figures"


def test_the_group_says_where_the_figures_come_from_and_carries_the_mark() -> None:
    node = group()
    said = words(node)
    assert "inline XBRL tags" in said and "newest annual and the newest quarterly report" in said
    assert CAUTION in said
    assert text(node.select_one(".fig-head .rule-mark .g-rule")) == RULE_GLYPH
    # The record's sentence on how many were read and offered sits right after the group.
    sentence = next(n for n in run()["metrics_notes"] if "tagged figures were read" in n)
    notes = node.find_next_sibling()
    assert notes is not None and "fig-notes" in notes.get("class", []), "the figures' notes do not follow the group"
    assert any(sentence in words(li) for li in notes.select("li")), "the read-and-offered sentence is not beside the group"


def test_both_offered_counts_and_the_cited_count_are_the_records() -> None:
    coverage = run()["coverage"]
    line = page().select_one("#status-banner li[data-figures-offered]")
    assert line is not None, "the banner does not say how many figures were offered"
    shown = {span["data-coverage"]: text(span) for span in line.select("[data-coverage]")}
    assert shown == {field: f"{coverage[field]:,}" for field in ("figures_offered", "tagged_figures_offered", "figures_cited")}
    said = words(line)
    assert said.startswith(f"{coverage['figures_offered']} reported figures and {coverage['tagged_figures_offered']} tagged figures offered")
    total = coverage["figures_offered"] + coverage["tagged_figures_offered"]
    assert f"{total:,}" not in said, "the page added the two counts up"


def test_every_tagged_figure_a_finding_cites_resolves_to_its_row() -> None:
    soup = page()
    cited = soup.select('#claim-list [data-cited-metric^="tagged:"], #withheld-section [data-cited-metric^="tagged:"]')
    expected = {i for f in run()["findings"] + run()["unsupported_findings"] for i in f["metric_ids"] if i.startswith(TAGGED)}
    assert {node["data-cited-metric"] for node in cited} == expected
    for node in cited:
        metric_id = node["data-cited-metric"]
        link = node.select_one("a.fig-open")
        assert link is not None, f"{metric_id}: the citation does not open its figure"
        target = unquote(link["href"].removeprefix("#"))
        row = soup.find(id=target)
        assert row is not None, f"{metric_id}: the link points at nothing ({link['href']})"
        assert row.name == "details" and row["data-metric-id"] == metric_id


def test_findings_on_figures_alone_say_so_beside_their_stance() -> None:
    soup = page()
    for finding in run()["findings"]:
        article = soup.select_one(f'#claim-list article[data-finding-id="{finding["id"]}"]')
        if article is None:
            continue
        tag = article.select_one(".finding-head [data-figures-only]")
        alone = finding["verified"] and not finding["evidence_ids"] and bool(finding["metric_ids"])
        assert (tag is not None) == alone, finding["id"]
        if alone:
            assert words(tag) == "rests on reported figures only: no excerpt"
    assert len(soup.select("#claim-list [data-figures-only]")) == run()["coverage"]["findings_without_quote"] == 3


def test_the_withheld_finding_shows_its_reason() -> None:
    withheld = [f for f in run()["unsupported_findings"] if any(i.startswith(TAGGED) for i in f["metric_ids"])]
    assert len(withheld) == 1
    finding = withheld[0]
    article = page().select_one(f'#withheld-section article[data-finding-id="{finding["id"]}"]')
    assert article is not None, "the withheld finding is not shown"
    assert f"Withheld: {finding['withheld_reason']}" in words(article)


def test_no_changed_paragraphs_block_without_a_record() -> None:
    soup = page()
    assert soup.select("[data-claim-changes]") == []
    top = soup.select_one("#run-filing-changes")
    assert top is not None and top.has_attr("hidden") and not top.contents


def test_first_screen_links_the_tagged_sample() -> None:
    soup = static_page()
    link = soup.select_one("#tagged-link")
    assert link is not None and link["href"] == "?sample=run-tagged"
    assert link.find_parent(id="sample-nav") is not None


@pytest.mark.parametrize("dump", list(NEW_WORDINGS))
def test_the_corrected_wordings_are_present(dump: str) -> None:
    path = RESULTS / dump
    require_fresh(path, WEB / DUMPS[dump])
    said = " ".join(BeautifulSoup(path.read_text(encoding="utf-8"), "html.parser").get_text().split())
    for wording in NEW_WORDINGS[dump]:
        assert wording in said, f"{dump} lacks {wording!r}"


@pytest.mark.parametrize("dump", list(DUMPS))
def test_the_untrue_wordings_are_gone(dump: str) -> None:
    path = RESULTS / dump
    require_fresh(path, WEB / DUMPS[dump])
    said = " ".join(BeautifulSoup(path.read_text(encoding="utf-8"), "html.parser").get_text().split())
    for old in OLD_WORDINGS:
        found = old.search(said)
        assert found is None, f"{dump} still says {found.group(0)!r}"
