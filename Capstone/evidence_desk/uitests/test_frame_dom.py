"""Browser-level checks of the frame: the workspace that fills the window.

`make uitest` loads uitests/frame.html in headless Chromium. That page frames the app at given
sizes (a frame's size is its viewport: 1440x900, 1280x800, 900x800, 360x740), selects claims in
the rail, switches tabs and picks items the way a reader would, and writes what it measured
after each step into its own DOM (one `li[data-step]` each). These tests read that record
against the live-run sample's JSON. What they hold the page to:

- at 1440x900 and 1280x800 the page itself does not scroll; its panes scroll inside themselves;
- at 360 wide nothing scrolls sideways, and the tabs stay at the top while the page scrolls;
- the claims are listed once (the rail), and a claim's words are drawn a second time only in
  the centre pane's head while it is selected;
- the rail's selection drives the centre pane and the inspector, and what is picked in the
  centre pane is what the inspector reads;
- a docket that is not on show is inert: nothing in it can take the focus.

The measures are the browser's (scroll and client sizes, bounding boxes); headless Chromium
with the fonts of its image is the only browser this was run in.
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
HARNESS = ROOT / "uitests" / "frame.html"

WIDE = [
    "wide-loaded",
    "wide-claim",
    "wide-claim-evidence",
    "wide-pick-finding",
    "wide-pick-test",
    "wide-noted",
    "wide-events",
    "wide-pick-event",
    "wide-pick-figure",
    "wide-claim-time",
    "wide-thesis-time",
    "wide-thesis-limits",
    "wide-code",
    "wide-code-unknown",
    "wide-vcell",
    "wide-counts-open",
    "wide-run-drawer",
    "wide-address",
]
MID = ["mid-claim-evidence", "mid-pick", "mid-escape"]
PHONE_RUN = ["phone-loaded", "phone-claim-evidence", "phone-scrolled", "phone-claim-overview", "phone-claim-time", "phone-events", "phone-figures", "phone-limits", "phone-terminal"]
EVERY = [*WIDE, "laptop-claim", "wide-first", *MID, *PHONE_RUN, "phone-first", "phone-inbox", "wide-inbox", "laptop-inbox-terminal"]
# Every step that shows the run (not the first screen, not the inbox).
RUN_STEPS = [*WIDE, "laptop-claim", *MID, *PHONE_RUN]


@cache
def run() -> dict[str, Any]:
    return json.loads((WEB / "sample-run-live.json").read_text(encoding="utf-8"))


@cache
def steps() -> dict[str, Tag]:
    dump = RESULTS / "dom-frame.html"
    require_fresh(dump, WEB / "sample-run-live.json")
    if HARNESS.stat().st_mtime > dump.stat().st_mtime:
        pytest.fail("dom-frame.html is older than uitests/frame.html: run `make uitest`")
    soup = BeautifulSoup(dump.read_text(encoding="utf-8"), "html.parser")
    done = soup.select_one("#done")
    if done is None or done.get("data-done") != "true":
        pytest.fail(f"the frame page did not finish: {done.get_text() if done else 'no status'}")
    return {li["data-step"]: li for li in soup.select("#steps > li")}


def step(name: str) -> Tag:
    """A step's record; a step the sample could not show skips its test with the harness's reason."""
    recorded = steps()[name]
    if recorded.has_attr("data-skipped"):
        pytest.skip(f"{name}: {recorded['data-skipped']}")
    return recorded


def shown(names: list[str]) -> list[str]:
    """The steps of `names` that the sample could show."""
    return [name for name in names if not steps()[name].has_attr("data-skipped")]


def plan() -> dict[str, str]:
    """Which claim of the sample each step used (uitests/frame.html chooses them from the record)."""
    chosen = steps()["plan"]
    return {key: chosen[f"data-{key}"] for key in ("main", "many", "pick", "noted", "other", "first")}


def pane(name: str, which: str) -> dict[str, Any] | None:
    """A pane's box and scroll at a step, or None when it is not drawn."""
    value = step(name)[f"data-{which}"]
    return None if value == "none" else json.loads(value)


def claim_ids() -> list[str]:
    return [claim["id"] for claim in run()["claims"]]


def claim(claim_id: str) -> dict[str, Any]:
    return next(c for c in run()["claims"] if c["id"] == claim_id)


def compiled_ids() -> list[str]:
    return [c["id"] for c in run()["claims"] if c.get("computed")]


def test_the_harness_ran_every_step() -> None:
    assert list(steps()) == ["plan", *EVERY]
    # The plan is the record's, not a name written into the harness.
    quoted = {f["claim_id"] for f in run()["findings"] if f.get("verified") is not False and f["evidence_ids"]}
    tested = [c["id"] for c in run()["claims"] if c.get("computed")]
    assert plan()["main"] == next((i for i in tested if i in quoted), "")
    assert plan()["first"] == claim_ids()[0] and plan()["other"] != plan()["main"]


# ---------------------------------------------------------------- the page does not scroll; its panes do


@pytest.mark.parametrize("name", [*WIDE, "wide-first", "wide-inbox"])
def test_the_page_does_not_scroll_at_1440_by_900(name: str) -> None:
    s = step(name)
    assert s["data-viewport"] == "1440x900"
    assert int(s["data-page-scroll-height"]) <= int(s["data-page-client-height"]) == 900, "the page is taller than the window"
    assert int(s["data-page-scroll-width"]) <= int(s["data-page-client-width"]) == 1440, "the page is wider than the window"


def test_nor_at_1280_by_800_nor_at_900_by_800() -> None:
    for name, size in [("laptop-claim", (1280, 800)), *[(m, (900, 800)) for m in MID]]:
        s = step(name)
        assert s["data-viewport"] == f"{size[0]}x{size[1]}"
        assert int(s["data-page-scroll-height"]) <= int(s["data-page-client-height"]) == size[1], name
        assert int(s["data-page-scroll-width"]) <= int(s["data-page-client-width"]) == size[0], name


@pytest.mark.parametrize("name", [*WIDE, "laptop-claim"])
def test_each_pane_is_inside_the_window_and_scrolls_inside_itself(name: str) -> None:
    height = int(step(name)["data-page-client-height"])
    width = int(step(name)["data-page-client-width"])
    rail, centre, inspector = pane(name, "rail"), pane(name, "centre"), pane(name, "inspector")
    assert rail is not None and centre is not None
    for box in (rail, centre, inspector):
        if box is None:
            continue
        assert box["top"] >= 0 and box["top"] + box["height"] <= height
        assert box["left"] >= 0 and box["left"] + box["width"] <= width
    assert rail["overflowY"] == "auto" and centre["overflowY"] == "auto"
    # Side by side: the rail, then the centre pane, then the inspector when there is one.
    assert rail["left"] == 0 and centre["left"] >= rail["width"]
    if inspector is not None:
        assert inspector["left"] >= centre["left"] + centre["width"]
        assert inspector["left"] + inspector["width"] == width
    else:
        assert centre["left"] + centre["width"] == width, "with no inspector the centre pane takes its width"


def test_the_first_screen_of_a_run_shows_every_verdict_and_the_thesis_without_scrolling() -> None:
    s = step("wide-loaded")
    rail = pane("wide-loaded", "rail")
    assert s["data-claim-rows"].split() == claim_ids()
    assert rail["scrollHeight"] <= rail["clientHeight"], "at 1440x900 the five verdicts fit the rail without scrolling it"
    assert (s["data-selected"], s["data-tab"], s["data-panels-shown"]) == ("", "overview", "panel-overview")
    assert s["data-sel-title"] == run()["inputs"]["decision"], "the whole thesis is headed by the decision it is about"
    # The status line is at the head of the rail, under the bar: the bar is the only strip across the window.
    strip = pane("wide-loaded", "strip")
    assert strip["left"] >= 0 and strip["left"] + strip["width"] <= rail["width"] and strip["height"] <= 60


def test_the_tabs_are_the_eight_views_and_exactly_one_is_selected() -> None:
    for name in shown(RUN_STEPS):
        s = step(name)
        assert s["data-tab-names"].split("|") == ["Analysis", "Overview", "Evidence", "Over time", "Events", "Figures", "Method", "Limits"], name
        assert s["data-tab-selected"] == s["data-tab"], name


# ---------------------------------------------------------------- the claims, once


@pytest.mark.parametrize("name", RUN_STEPS)
def test_the_claims_are_listed_once(name: str) -> None:
    s = step(name)
    assert s["data-claim-rows"].split() == claim_ids(), "the rail lists every claim"
    selected = s["data-selected"]
    drawn = json.loads(s["data-claim-texts-drawn"])
    # Below 1100px, and on a phone, the rail is a strip of chips (id and stamp): a claim's words are its chip's title.
    in_rail = 0 if name in MID or name in PHONE_RUN else 1
    for claim_id in claim_ids():
        # In the rail; and, for the claim selected, in the centre pane's head.
        expected = in_rail + (1 if claim_id == selected else 0)
        assert drawn.get(claim_id, 0) == expected, f"{claim_id} is drawn {drawn.get(claim_id, 0)} times"
    assert s["data-docket-headings-drawn"] == "0", "a docket's own heading is for paper"
    assert s["data-dockets-drawn"].split() in ([], [selected]), "only the selected claim's docket is drawn"


# ---------------------------------------------------------------- the selection drives the panes


def test_selecting_a_claim_shows_that_claim_and_reads_its_test_at_the_side() -> None:
    s, main = step("wide-claim"), plan()["main"]
    assert (s["data-selected"], s["data-tab"], s["data-panels-shown"]) == (main, "overview", "panel-claim")
    assert s["data-sel-title"] == claim(main)["text"]
    assert s["data-dockets-drawn"] == main
    assert s["data-inspecting"] == f"test:{main}" and s["data-picked"] == f"test:{main}"
    assert claim(main)["computed"]["canonical"] in s["data-inspector-text"]


def test_the_evidence_tab_reads_a_findings_quote_in_its_context_with_the_link() -> None:
    s = step("wide-claim-evidence")
    assert (s["data-selected"], s["data-tab"], s["data-panels-shown"]) == (plan()["main"], "evidence", "panel-claim")
    assert s["data-inspecting"] == f"finding:{s['data-first-finding']}", "with nothing picked, the first finding is read"
    assert s["data-context-drawn-in-centre"] == "0", "the context is read at the side, not twice"
    # Another finding than the first is picked on the claim that has several.
    picked = step("wide-pick-finding")
    finding = next(f for f in run()["findings"] if f["id"] == picked["data-picked-finding"])
    assert finding["id"] == plan()["pick"] and finding["claim_id"] == plan()["many"] and finding["id"] != picked["data-first-of-its-claim"]
    assert picked["data-inspecting"] == picked["data-picked"] == f"finding:{finding['id']}"
    assert picked["data-inspected-evidence"].split() == finding["evidence_ids"]
    evidence = {e["id"]: e for e in run()["evidence"]}
    for evidence_id in finding["evidence_ids"]:
        assert " ".join(evidence[evidence_id]["excerpt"].split()) in picked["data-inspector-text"]
        assert evidence[evidence_id]["link"] in picked["data-inspected-links"].split()
    assert int(picked["data-inspected-context"]) >= 1, "the inspector shows the text around the quote"


def test_a_computed_tests_operands_and_arithmetic_are_read_in_the_inspector() -> None:
    s = step("wide-pick-test")
    test = claim(plan()["main"])["computed"]
    assert s["data-inspecting"] == f"test:{plan()['main']}"
    assert s["data-inspected-operands"].split("|") == [operand["term"] for operand in test["operands"]]
    assert s["data-detail-drawn-in-centre"] == "0"
    for operand in test["operands"]:
        assert operand["display"] in s["data-inspector-text"]


def test_an_operand_with_a_long_note_stays_inside_the_inspector() -> None:
    """A value with a sentence of a note (free cash flow, in the live runs) once squeezed its term to a letter a line."""
    s = step("wide-noted")
    test = claim(plan()["noted"])["computed"]
    assert any(len(operand.get("note") or "") > 80 for operand in test["operands"])
    assert s["data-inspecting"] == f"test:{plan()['noted']}"
    assert int(s["data-inspector-spill"]) <= 0, "the inspector's content is wider than the inspector"
    assert int(s["data-tallest-term"]) <= 48, "an operand's term is broken over more than two lines"
    assert int(s["data-widest-note"]) >= 200, "the note is squeezed into the value's column"


def test_an_8k_is_read_in_the_inspector() -> None:
    first, picked = step("wide-events"), step("wide-pick-event")
    events = run()["timeline"]
    assert first["data-panels-shown"] == "panel-events"
    assert first["data-inspecting"] == f"event:{events[0]['id']}" == f"event:{first['data-first-event']}"
    assert picked["data-picked-event"] == events[1]["id"]
    assert picked["data-inspecting"] == picked["data-picked"] == f"event:{events[1]['id']}"
    assert picked["data-inspected-event"] == events[1]["id"]
    assert picked["data-openings-drawn-in-centre"] == "0"
    for item in events[1]["items"]:
        for sentence in item.get("opening") or []:
            assert " ".join(sentence.split()) in picked["data-inspector-text"]


def test_a_figures_inputs_are_read_in_the_inspector_and_its_row_stays_shut() -> None:
    s = step("wide-pick-figure")
    metric = next(m for m in run()["metrics"] if m["id"] == s["data-picked-figure"])
    assert s["data-panels-shown"] == "panel-figures"
    assert s["data-inspecting"] == f"figure:{metric['id']}"
    assert (s["data-inspected-label"], s["data-inspected-value"]) == (metric["label"], metric["display"])
    assert s["data-row-open"] == "false"
    for ref in metric["inputs"]:
        assert ref["concept"] in s["data-inspector-text"]


def test_over_time_shows_the_selected_claims_lane_and_every_lane_for_the_thesis() -> None:
    assert step("wide-claim-time")["data-lanes-drawn"].split() == [plan()["main"]]
    assert step("wide-claim-time")["data-panels-shown"] == "panel-time"
    assert step("wide-thesis-time")["data-lanes-drawn"].split() == compiled_ids()
    assert step("wide-thesis-time")["data-selected"] == ""


def test_the_inspector_stays_on_every_tab_and_reads_the_runs_facts_when_nothing_is_picked() -> None:
    before, after = pane("wide-thesis-time", "centre"), pane("wide-thesis-limits", "centre")
    assert pane("wide-thesis-time", "inspector") == pane("wide-thesis-limits", "inspector") is not None
    assert step("wide-thesis-limits")["data-panels-shown"] == "panel-limits"
    assert after["width"] == before["width"], "the centre pane does not reflow between tabs"
    s = step("wide-thesis-limits")
    assert s["data-inspecting"] == "" and s["data-picked"] == ""
    said = s["data-inspector-text"].replace(" ", "")
    coverage = run()["coverage"]
    assert f"Sourcesread{coverage['sources_read']:,}of{coverage['sources_requested']:,}" in said
    assert f"Findingsverified{coverage['findings_verified']:,}of{coverage['findings_proposed']:,}" in said
    for source in run()["sources"]:
        assert source["id"] in said
    # What the tab on show lists is not said twice: on Limits the inspector leaves the limits to the centre pane.
    for limit in run()["coverage_limits"]:
        assert "".join(limit.split()) not in said
    elsewhere = step("wide-loaded")["data-inspector-text"]
    assert elsewhere  # the Overview reads its first figure; the limits are in the run's facts on any tab but Limits


def test_the_verdicts_are_one_strip_of_cells_drawn_the_same_everywhere() -> None:
    s = step("wide-loaded")
    expected = " ".join(f"{c['id']}:v-{c['verdict']}" for c in run()["claims"])
    assert s["data-cells-bar"] == s["data-cells-rail"] == s["data-cells-overview"] == expected
    assert s["data-table-rows"] == " ".join(f"{c['id']}:{c['verdict']}" for c in run()["claims"])
    # The result first: the masthead with its strip, then the verdict table beside the figures, then the summary.
    assert s["data-overview-order"].split() == ["overview-mast", "verdicts-section", "tape-section", "summary-section"]
    picked = step("wide-vcell")
    assert picked["data-selected"] == plan()["other"] and picked["data-sel-title"] == claim(plan()["other"])["text"]


def test_a_verdict_is_a_solid_stamp_and_a_provenance_tag_is_not_a_box() -> None:
    s = step("wide-loaded")
    assert 11 <= float(s["data-stamp-font-px"].removesuffix("px")) <= 12
    assert s["data-stamp-fill"] != "rgba(0, 0, 0, 0) none", "a verdict stamp is filled"
    if s["data-badge-border"] == "":
        pytest.skip("this sample draws no model-written tag on its summary or its findings")
    assert s["data-badge-border"] == "0px", "the model-written tag has no box"


def test_a_rail_row_is_two_lines_and_the_bar_has_one_menu() -> None:
    s = step("wide-loaded")
    assert all(int(height) <= 80 for height in s["data-rail-row-heights"].split()), "a row is its id line and at most two lines of claim"
    assert s["data-menu-items"].split() == ["howto-button", "theme-toggle", "keys-button"]
    assert s["data-bar-buttons-with-hints"] == "0", "no key hint inside a button of the bar"


def test_a_code_typed_in_the_ticker_field_goes_to_its_panel() -> None:
    went, unknown = step("wide-code"), step("wide-code-unknown")
    assert (went["data-tab"], went["data-panels-shown"]) == ("events", "panel-events")
    assert went["data-ticker-error"] == "" and went["data-ticker-after"] == "", "the field gets back what it held"
    assert "ZZZ" in unknown["data-ticker-error"] and unknown["data-tab"] == "events"


def test_the_address_can_name_a_claim_and_a_tab() -> None:
    s = step("wide-address")
    assert (s["data-selected"], s["data-tab"], s["data-theme"]) == (plan()["other"], "evidence", "terminal")
    assert s["data-sel-title"] == claim(plan()["other"])["text"]


# ---------------------------------------------------------------- nothing hidden can be reached


@pytest.mark.parametrize("name", RUN_STEPS)
def test_a_docket_that_is_not_on_show_is_inert_and_out_of_the_tab_order(name: str) -> None:
    s = step(name)
    selected = s["data-selected"]
    assert s["data-dockets-inert"].split() == [c for c in claim_ids() if c != selected]
    assert s["data-focusable-in-hidden-parts"] == "0", "a hidden part that is not inert holds something focusable"
    assert s["data-tab-order-dockets"].split() in ([], [selected]), "the tab order reaches a docket that is not selected"


def test_nothing_drawn_is_inert_while_the_drawers_are_closed() -> None:
    for name in shown(RUN_STEPS):
        if name == "wide-run-drawer":
            continue
        assert step(name)["data-focusable-drawn-but-inert"] == "0", name


# ---------------------------------------------------------------- the status line and the Run drawer


def test_the_full_counts_open_over_the_panes_without_moving_them() -> None:
    assert step("wide-counts-open")["data-counts-open"] == "true"
    box = lambda name: {k: pane(name, "centre")[k] for k in ("left", "top", "width", "height")}  # noqa: E731
    # Against the step before it, with the same claim selected: the head of the centre pane is as tall as what it names.
    assert box("wide-counts-open") == box("wide-vcell")


def test_the_run_drawer_holds_who_did_the_work_the_guide_and_the_marks() -> None:
    s = step("wide-run-drawer")
    assert (s["data-drawer-open"], s["data-drawer-inert"]) == ("true", "false")
    said = s["data-drawer-text"]
    for field in ("engine_detail", "checker_detail", "claim_readers", "claim_reader_detail", "claim_reading_rule", "id"):
        assert run()[field] in said, field
    assert run()["as_of"]["line"] in said
    assert (s["data-legend-in"], s["data-howto-in"]) == ("run-drawer", "guide-slot")
    assert step("wide-loaded")["data-howto-in"] == "guide-slot"


def test_on_the_first_screen_the_guide_is_the_lead_beside_the_form() -> None:
    s = step("wide-first")
    index = BeautifulSoup((WEB / "index.html").read_text(encoding="utf-8"), "html.parser")
    assert (s["data-first-screen"], s["data-howto-in"], s["data-form-drawn"]) == ("true", "lead-slot", "true")
    assert int(s["data-samples-drawn"]) == len(index.select("#sample-nav a"))


def test_a_view_that_is_not_a_run_is_laid_out_in_the_same_three_panes() -> None:
    s = step("wide-inbox")
    assert (s["data-panel-scrolls"], s["data-panel-overflow-y"]) == ("true", "auto"), "the list scrolls inside the centre pane"
    rail, centre, aside = (tuple(int(n) for n in s[f"data-view-{name}"].split(",")) for name in ("rail", "centre", "aside"))
    assert rail[0] == 0 and centre[0] == rail[1] and aside[0] == centre[0] + centre[1] and aside[0] + aside[1] == 1440
    index = BeautifulSoup((RESULTS / "dom-inbox.html").read_text(encoding="utf-8"), "html.parser")
    assert int(s["data-rail-entries"]) == len(index.select("#inbox-items .inbox-headline, #inbox-collapsed .inbox-headline")) > 0
    assert s["data-head-in-aside"] == "true"


# ---------------------------------------------------------------- narrower windows


def test_below_1100_the_rail_is_a_strip_across_the_top_and_the_inspector_a_sheet() -> None:
    rail, centre = pane("mid-claim-evidence", "rail"), pane("mid-claim-evidence", "centre")
    assert rail["width"] == 900 and centre["width"] == 900
    assert rail["top"] + rail["height"] <= centre["top"], "the rail sits above the centre pane"
    assert rail["height"] <= 260, "a strip, not a column"
    assert pane("mid-claim-evidence", "inspector") is None, "nothing is read at the side until it is picked"
    sheet = pane("mid-pick", "inspector")
    assert sheet is not None and step("mid-pick")["data-sheet-position"] == "fixed"
    assert sheet["top"] + sheet["height"] == 800 and sheet["width"] == 900, "a sheet from the bottom"
    assert step("mid-pick")["data-inspecting"].startswith("finding:")
    assert step("mid-pick")["data-active"] == "inspect-body", "the focus goes with the sheet"
    assert pane("mid-escape", "inspector") is None, "Esc puts the sheet away"


@pytest.mark.parametrize("name", [*PHONE_RUN, "phone-first", "phone-inbox"])
def test_nothing_scrolls_sideways_at_360(name: str) -> None:
    s = step(name)
    assert s["data-viewport"] == "360x740"
    assert int(s["data-page-scroll-width"]) <= int(s["data-page-client-width"]) == 360


def test_a_phone_is_one_column_with_the_tabs_kept_in_view() -> None:
    loaded = step("phone-loaded")
    rail, centre = pane("phone-loaded", "rail"), pane("phone-loaded", "centre")
    assert rail["left"] >= 0 and rail["left"] + rail["width"] <= 360 and centre["left"] + centre["width"] <= 360
    assert rail["top"] + rail["height"] <= centre["top"], "one column: the rail, then the selection"
    assert int(loaded["data-page-scroll-height"]) > 740, "the page scrolls; the panes do not"
    assert pane("phone-loaded", "inspector") is None
    scrolled = step("phone-scrolled")
    assert scrolled["data-tabs-position"] == "sticky" and int(scrolled["data-scroll-y"]) > 0
    assert int(scrolled["data-tabs-top"]) == 0, "the tabs stay at the top of the window"


def test_a_phone_reads_in_place_what_a_wide_window_reads_in_the_inspector() -> None:
    s = step("phone-claim-evidence")
    assert (s["data-selected"], s["data-tab"]) == (plan()["main"] or plan()["first"], "evidence")
    assert int(s["data-context-drawn"]) >= 1, "the quote's context is drawn with the finding"
    assert s["data-pick-buttons-drawn"] == "0" and s["data-inspecting"] == ""


# ---------------------------------------------------------------- the bar


@pytest.mark.parametrize("name", [*WIDE, "laptop-claim", "wide-first", "wide-inbox", "laptop-inbox-terminal"])
def test_the_bar_is_one_row_with_every_control_inside_the_window(name: str) -> None:
    s = step(name)
    assert int(s["data-bar-height"]) <= 36, "the bar is one low row"
    assert int(s["data-bar-right"]) <= int(s["data-page-client-width"]), "a control of the bar is outside the window"
