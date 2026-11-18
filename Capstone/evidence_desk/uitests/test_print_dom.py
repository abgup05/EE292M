"""Browser-level checks of the printed note.

`make uitest` loads uitests/print.html in headless Chromium. That page frames the live-run
sample with a claim selected and a tab that is not the first, fires the page's own
`beforeprint`, turns the stylesheet's `@media print` rules on and its `@media screen` rules
off, and writes what is then drawn into its own DOM. These tests read that record: on paper
the workspace is a document, with every claim's docket under its own heading and every tab's
panel one after another, whatever was selected on screen.

It is an emulation in a screen browser. Page breaks, margins, and what a printer or a PDF
viewer does with the result are not checked here.
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
HARNESS = ROOT / "uitests" / "print.html"


@cache
def run() -> dict[str, Any]:
    return json.loads((WEB / "sample-run-events.json").read_text(encoding="utf-8"))


@cache
def steps() -> dict[str, Tag]:
    dump = RESULTS / "dom-print.html"
    require_fresh(dump, WEB / "sample-run-events.json")
    if HARNESS.stat().st_mtime > dump.stat().st_mtime:
        pytest.fail("dom-print.html is older than uitests/print.html: run `make uitest`")
    soup = BeautifulSoup(dump.read_text(encoding="utf-8"), "html.parser")
    done = soup.select_one("#done")
    if done is None or done.get("data-done") != "true":
        pytest.fail(f"the print page did not finish: {done.get_text() if done else 'no status'}")
    return {li["data-step"]: li for li in soup.select("#steps > li")}


def claim_ids() -> list[str]:
    return [claim["id"] for claim in run()["claims"]]


def test_the_harness_ran_from_a_claim_and_a_tab_that_is_not_the_first() -> None:
    assert list(steps()) == ["screen", "print", "after"]
    screen = steps()["screen"]
    assert screen["data-dockets-drawn"] == "" and screen["data-panels-drawn"] == "panel-events"
    assert "tabs" in screen["data-chrome-drawn"].split() and "cmdbar" in screen["data-chrome-drawn"].split()
    assert screen["data-page-scrolls"] == "false", "on screen the page itself does not scroll"


def test_on_paper_every_docket_prints_open_under_its_own_heading() -> None:
    printed = steps()["print"]
    assert printed["data-dockets-drawn"].split() == claim_ids()
    assert printed["data-dockets-open"].split() == claim_ids()
    assert printed["data-docket-headings"].split("|") == [claim["text"] for claim in run()["claims"]]


def test_on_paper_every_tabs_panel_prints_in_reading_order() -> None:
    printed = steps()["print"]
    assert printed["data-panels-drawn"].split() == ["panel-overview", "panel-claim", "panel-evidence", "panel-time", "panel-events", "panel-figures", "panel-limits"]
    # The company and the decision, the verdicts, how the run was made, the counts, then the note.
    assert printed["data-order"].split() == ["rail-head", "scorecard", "run-info", "status-banner", "tape-section", "summary-section", "claim-list", "sources", "timeline-section", "events-section", "figures-section", "coverage-limits"]
    assert int(printed["data-note-height"]) > 1000, "a document taller than the 1000px window it was laid out in, not a frame that fits it"


def test_on_paper_there_is_no_frame_and_nothing_to_press() -> None:
    printed = steps()["print"]
    assert printed["data-chrome-drawn"] == "", "the bar, the tabs, the inspector and the drawer are for a screen"
    assert printed["data-pick-buttons-drawn"] == "0"
    assert printed["data-background"] == "rgb(255, 255, 255)", "paper is white in either theme"
    # Printed from Terminal: the note prints as Paper, and the theme comes back after.
    assert (steps()["screen"]["data-theme"], printed["data-theme"], steps()["after"]["data-theme"]) == ("terminal", "paper", "terminal")
    assert printed["data-selected-row-background"] == "rgba(0, 0, 0, 0)", "the row selected on screen is not marked on paper"


def test_on_paper_what_the_inspector_reads_is_printed_in_place() -> None:
    printed, screen = steps()["print"], steps()["screen"]
    evidence = {e["id"] for e in run()["evidence"]}
    cited = [e for f in run()["findings"] if f.get("verified") is not False for e in f["evidence_ids"] if e in evidence]
    assert int(printed["data-contexts-drawn"]) >= len(cited) > 0, "each quote prints in the text around it"
    openings = sum(1 for event in run()["timeline"] for item in event["items"] if item.get("opening"))
    assert int(printed["data-openings-drawn"]) == openings > 0
    assert printed["data-counts-drawn"] == "true", "the status line prints with every count"
    assert screen["data-openings-drawn"] == "0", "on screen an 8-K's opening sentences are read in the inspector"


def test_on_paper_how_the_run_was_made_follows_the_verdicts_and_goes_back_after() -> None:
    printed, after = steps()["print"], steps()["after"]
    assert (printed["data-run-info-in"], printed["data-run-info-after"]) == ("workspace", "rail")
    for field in ("engine_detail", "checker_detail", "id"):
        assert run()[field] in printed["data-run-info"], field
    assert after["data-run-info-in"] == "run-drawer", "after printing it is back in the Run drawer"
