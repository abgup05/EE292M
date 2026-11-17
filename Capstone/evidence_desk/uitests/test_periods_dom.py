"""Browser-level checks of the period check (milestone 11) as each finding and the banner show it.

The check compares each year a verified finding names with its evidence and REPORTS: it
withholds nothing and changes no verdict or status. These tests read the dumps `make uitest`
writes for /?sample=synthetic (the only record with a year not found), /?sample and
/?sample=run-tagged, against their sample files.
"""

from __future__ import annotations

import copy
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
PAGES = {
    "synthetic": ("dom-synthetic.html", "sample-synthetic.json"),
    "run": ("dom-sample.html", "sample-run.json"),
    "run-tagged": ("dom-run-tagged.html", "sample-run-tagged.json"),
}
RECORDED = ("run", "run-tagged")
CAUTION_TITLE = "Period not found in its evidence:"
PASSED_WORDS = "Years named: all in its evidence"
NONE_WORDS = "No year checked"
FAILED_CHECK_WORDS = ("A number did not match", "Quote: not found", "Withheld", "failed")


@cache
def record(name: str) -> dict[str, Any]:
    return json.loads((WEB / PAGES[name][1]).read_text(encoding="utf-8"))["run"]


@cache
def page(name: str) -> BeautifulSoup:
    dump = RESULTS / PAGES[name][0]
    require_fresh(dump, WEB / PAGES[name][1])
    soup = BeautifulSoup(dump.read_text(encoding="utf-8"), "html.parser")
    if soup.select_one("#run-view") is None or soup.select_one("#run-view[hidden]") is not None:
        pytest.fail(f"{dump.name}: the page did not render a run")
    return soup


def words(node: Tag) -> str:
    return " ".join(node.get_text().split())


def finding_checks(name: str, finding_id: str) -> Tag:
    article = page(name).select_one(f'#claim-list article[data-finding-id="{finding_id}"]')
    assert article is not None, f"{name}: finding {finding_id} is not shown under its claim"
    checks = article.select_one(".checks")
    assert checks is not None, f"{name}: {finding_id} shows no checks"
    return checks


def unverified() -> dict[str, Any]:
    found = [f for f in record("synthetic")["findings"] if f["checks"].get("periods") == "unverified"]
    assert len(found) == 1, "the synthetic sample needs exactly one finding with a year not found"
    return found[0]


def test_synthetic_sample_holds_every_state_and_its_counts_add_up() -> None:
    run = record("synthetic")
    states = {f["checks"].get("periods") for f in run["findings"]}
    assert {"none", "passed", "unverified"} <= states
    unplaced = unverified()["checks"]["periods_unverified"]
    assert sorted(u["comparative"] for u in unplaced) == [False, True]
    coverage = run["coverage"]
    named = sum(len(f["checks"].get("periods_detail", [])) for f in run["findings"])
    assert coverage["periods_checked"] == named == 4
    assert coverage["periods_unverified"] == sum(len(f["checks"].get("periods_unverified", [])) for f in run["findings"]) == 2
    assert coverage["periods_comparative"] == sum(u["comparative"] for f in run["findings"] for u in f["checks"].get("periods_unverified", [])) == 1


def test_the_caution_shows_each_detail_as_the_record_gives_it() -> None:
    finding = unverified()
    checks = finding_checks("synthetic", finding["id"])
    caution = checks.select_one('li.period-caution[data-periods="unverified"]')
    assert caution is not None, "the finding shows no period caution"
    assert words(caution.select_one(".period-caution-title")) == CAUTION_TITLE
    shown = caution.select("ul.period-unplaced > li")
    expected = finding["checks"]["periods_unverified"]
    assert [li.get_text() for li in shown] == [u["detail"] for u in expected]
    assert [li["data-comparative"] for li in shown] == [str(u["comparative"]).lower() for u in expected]
    detail = caution.select("ul[data-periods-detail] > li")
    assert [li.get_text() for li in detail] == finding["checks"]["periods_detail"]


def test_the_caution_is_a_caution_not_a_failed_check_or_a_withheld_finding() -> None:
    finding = unverified()
    assert finding["verified"] is True
    soup = page("synthetic")
    article = soup.select_one(f'#claim-list article[data-finding-id="{finding["id"]}"]')
    assert "is-withheld" not in (article.get("class") or [])
    assert soup.select_one(f'#withheld-section article[data-finding-id="{finding["id"]}"]') is None
    caution = article.select_one("li.period-caution")
    # Drawn with the limit mark in ink, as the coverage limits are; the words are the record's.
    assert caution.select_one(".mark-limit .g-limit") is not None
    own_words = copy.copy(caution)
    for node in own_words.select("ul.period-unplaced, details"):
        node.decompose()
    for failed in FAILED_CHECK_WORDS:
        assert failed not in words(own_words), f"the caution says {failed!r}"
    # The finding keeps its stance, its place among the verified findings and the reader's review.
    pill = article.select_one(".finding-head .pill.stance")
    assert pill is not None and f"s-{finding['stance']}" in pill["class"]
    assert article.select_one(f'[data-review-finding="{finding["id"]}"]') is not None
    assert len(article.select("li.period-caution")) == 1


@pytest.mark.parametrize("name", list(PAGES))
def test_passed_and_none_read_as_the_other_checks_do(name: str) -> None:
    seen = set()
    for finding in record(name)["findings"]:
        state = finding["checks"].get("periods")
        checks = finding_checks(name, finding["id"])
        item = checks.select_one("li[data-periods]")
        if state is None:
            assert item is None, f"{finding['id']}: a period line for a record without the check"
            continue
        seen.add(state)
        assert item is not None and item["data-periods"] == state, finding["id"]
        if state == "passed":
            assert words(item).startswith(PASSED_WORDS), finding["id"]
            detail = item.select("ul[data-periods-detail] > li")
            assert [li.get_text() for li in detail] == finding["checks"]["periods_detail"], finding["id"]
            assert "period-caution" not in (item.get("class") or [])
        elif state == "none":
            assert words(item) == NONE_WORDS, finding["id"]
    assert "passed" in seen


@pytest.mark.parametrize("name", RECORDED)
def test_recorded_runs_show_no_caution(name: str) -> None:
    assert record(name)["coverage"]["periods_unverified"] == 0
    assert page(name).select("li.period-caution") == []
    assert CAUTION_TITLE not in words(page(name).select_one("#claim-list"))


@pytest.mark.parametrize("name", list(PAGES))
def test_the_banner_line_shows_the_records_counts(name: str) -> None:
    coverage = record(name)["coverage"]
    line = page(name).select_one("#status-banner li[data-periods-line]")
    assert line is not None, f"{name}: the banner does not report the period check"
    shown = {span["data-coverage"]: span.get_text() for span in line.select("[data-coverage]")}
    expected = {"periods_checked", "periods_unverified"}
    if coverage["periods_unverified"] > 0:
        expected.add("periods_comparative")
    assert shown == {field: f"{coverage[field]:,}" for field in expected}
    said = words(line)
    assert said.startswith(f"{coverage['periods_checked']} years named in verified findings checked against their evidence, {coverage['periods_unverified']} not found")
    if name in RECORDED:
        assert said.endswith("0 not found") and coverage["periods_checked"] == {"run": 10, "run-tagged": 12}[name]
    else:
        assert said.endswith(f"({coverage['periods_comparative']} of them a comparison year)")


@pytest.mark.parametrize("name", list(PAGES))
def test_the_legend_explains_the_caution(name: str) -> None:
    entry = page(name).select_one('#legend [data-legend="period-caution"]')
    assert entry is not None, "the legend has no entry for the period caution"
    said = words(entry)
    assert "reported only" in said and "withholds nothing" in said and "changes no verdict" in said
    assert "one below the filing's own is often the comparison year" in said
    assert entry.select_one("dt .g-limit") is not None
