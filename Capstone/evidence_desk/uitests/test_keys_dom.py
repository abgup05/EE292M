"""Browser-level checks of the page's keys and its two themes.

`make uitest` loads uitests/keys.html in headless Chromium. That page frames the live-run sample,
presses the page's keys and clicks its theme button, and writes what the page did after each
step into its own DOM (one `li[data-step]` each). These tests read that record, and the
Terminal dump of /?sample&theme=terminal. The keys: / puts the cursor in the ticker, j and k move
the rail's selection between the whole thesis and the claims, 1 to 9 show a tab, r opens the Run
drawer, t switches the theme, ? shows the keys; none acts while you type in a field or with a
modifier held.
"""

from __future__ import annotations

from functools import cache
from pathlib import Path

import pytest
from bs4 import BeautifulSoup, Tag
from test_dom import require_fresh

ROOT = Path(__file__).resolve().parents[1]
WEB = ROOT / "src" / "web"
RESULTS = ROOT / "results"
HARNESS = ROOT / "uitests" / "keys.html"


@cache
def steps() -> dict[str, Tag]:
    dump = RESULTS / "dom-keys.html"
    require_fresh(dump, WEB / "sample-run-events.json")
    if HARNESS.stat().st_mtime > dump.stat().st_mtime:
        pytest.fail("dom-keys.html is older than uitests/keys.html: run `make uitest`")
    soup = BeautifulSoup(dump.read_text(encoding="utf-8"), "html.parser")
    done = soup.select_one("#done")
    if done is None or done.get("data-done") != "true":
        pytest.fail(f"the keys page did not finish: {done.get_text() if done else 'no status'}")
    return {li["data-step"]: li for li in soup.select("#steps > li")}


def test_the_harness_ran_every_step_on_the_live_run() -> None:
    names = list(steps())
    assert names == ["loaded", "slash", "j-while-typing", "escape-ticker", "j1", "j2", "j3", "k1", "ctrl-j", "t", "toggle-click", "question", "close", "e-open", "e-close", "digit-2", "r-open", "r-close", "k-top", "enter", "i"]
    assert steps()["loaded"]["data-claims"] == "2"


def test_slash_puts_the_cursor_in_the_ticker_and_escape_takes_it_out() -> None:
    assert steps()["loaded"]["data-active"] == "body"
    assert steps()["slash"]["data-active"] == "ticker"
    assert steps()["escape-ticker"]["data-active"] == "body"


def test_keys_do_nothing_while_you_type() -> None:
    step = steps()["j-while-typing"]
    assert step["data-active"] == "ticker" and step["data-selected"] == "", "the whole thesis stays selected"


def test_j_and_k_move_between_claims_in_order_and_stop_at_the_ends() -> None:
    s = steps()
    assert s["loaded"]["data-selected"] == "", "a run opens on the whole thesis"
    assert [s[k]["data-selected"] for k in ("j1", "j2", "j3", "k1")] == ["c1", "c2", "c2", "c1"]
    assert all(s[k]["data-active-select"] == s[k]["data-selected"] for k in ("j1", "j2", "j3", "k1")), "focus lands on the claim's row in the rail"
    # The selection drives the centre pane: exactly the selected claim's docket is on show.
    assert [s[k]["data-shown"] for k in ("loaded", "j1", "j2", "k1")] == ["", "c1", "c2", "c1"]
    # k goes on from the first claim to the whole thesis and stops there.
    assert (s["k-top"]["data-selected"], s["k-top"]["data-active"], s["k-top"]["data-shown"]) == ("", "rail-thesis", "")


def test_enter_on_the_selected_claim_goes_on_to_its_tabs() -> None:
    step = steps()["enter"]
    assert step["data-selected"] == "c1"
    assert step["data-active"] == f"tab-{step['data-tab']}", "the focus goes to the tab on show"


def test_a_digit_shows_that_tab_of_the_selection() -> None:
    s = steps()
    assert s["e-close"]["data-tab"] == "overview", "a run opens on its first tab"
    assert s["digit-2"]["data-tab"] == "evidence"
    assert s["digit-2"]["data-selected"] == s["e-close"]["data-selected"], "the selection stays"


def test_r_opens_the_run_drawer_and_escape_closes_it() -> None:
    s = steps()
    assert (s["digit-2"]["data-run-drawer"], s["digit-2"]["data-run-expanded"], s["digit-2"]["data-run-drawer-inert"]) == ("closed", "false", "true")
    assert (s["r-open"]["data-run-drawer"], s["r-open"]["data-run-expanded"], s["r-open"]["data-run-drawer-inert"]) == ("open", "true", "false")
    assert s["r-open"]["data-active"] == "run-drawer-close", "the drawer opens on its Close button"
    assert (s["r-close"]["data-run-drawer"], s["r-close"]["data-run-expanded"], s["r-close"]["data-run-drawer-inert"]) == ("closed", "false", "true")
    assert s["r-close"]["data-active"] == "run-button", "closing gives the focus back to the status chip"


def test_a_key_with_a_modifier_is_left_to_the_browser() -> None:
    assert steps()["ctrl-j"]["data-selected"] == steps()["k1"]["data-selected"]


def test_t_and_the_button_switch_the_theme_and_remember_it() -> None:
    s = steps()
    first = s["loaded"]["data-theme"]
    assert first in {"paper", "terminal"}
    assert s["loaded"]["data-stored"] == "", "nothing is stored before the reader chooses"
    other = "terminal" if first == "paper" else "paper"
    assert (s["t"]["data-theme"], s["t"]["data-stored"]) == (other, other)
    assert (s["toggle-click"]["data-theme"], s["toggle-click"]["data-stored"]) == (first, first)
    names = {"paper": "Paper", "terminal": "Terminal"}
    assert s["t"]["data-toggle-label"] == f"Theme: {names[other]}. Switch to {names[first]}"
    assert s["toggle-click"]["data-toggle-label"] == f"Theme: {names[first]}. Switch to {names[other]}"


def test_question_mark_opens_the_list_of_keys_and_close_closes_it() -> None:
    s = steps()
    assert s["t"]["data-dialog"] == "closed"
    assert s["question"]["data-dialog"] == "open"
    assert s["close"]["data-dialog"] == "closed"
    assert s["close"]["data-active-select"] == "c1", "closing the list gives the focus back"


def test_e_opens_the_thesis_drawer_beside_a_run_and_escape_closes_it() -> None:
    s = steps()
    assert (s["close"]["data-drawer"], s["close"]["data-thesis-expanded"]) == ("closed", "false")
    assert (s["e-open"]["data-drawer"], s["e-open"]["data-thesis-expanded"]) == ("open", "true")
    assert s["e-open"]["data-active"] == "decision", "the drawer opens on its first field"
    assert (s["e-close"]["data-drawer"], s["e-close"]["data-thesis-expanded"]) == ("closed", "false")
    assert s["e-close"]["data-active"] == "thesis-button", "closing gives the focus back to the button"


def test_i_opens_the_inbox_and_a_sample_without_one_says_so() -> None:
    step = steps()["i"]
    assert (step["data-inbox"], step["data-run"]) == ("shown", "hidden")
    assert step["data-empty"] == "sample", "the live-run sample holds no inbox, and the page says so"


@cache
def terminal() -> BeautifulSoup:
    dump = RESULTS / "dom-sample-terminal.html"
    require_fresh(dump, WEB / "sample-run.json")
    return BeautifulSoup(dump.read_text(encoding="utf-8"), "html.parser")


def test_theme_in_the_address_sets_the_terminal_theme_without_storing_it() -> None:
    soup = terminal()
    assert soup.select_one("html")["data-theme"] == "terminal"
    toggle = soup.select_one("#theme-toggle")
    assert toggle["aria-label"] == "Theme: Terminal. Switch to Paper"
    assert soup.select_one("#run-view:not([hidden])") is not None


def test_the_keys_dialog_lists_every_key_the_page_answers() -> None:
    soup = terminal()
    keys = [words.get_text() for words in soup.select("#keys-dialog .keys-list dt kbd")]
    assert keys == ["/", "e", "i", "j", "k", "1", "9", "Enter", "r", "t", "?", "Esc"]
    assert soup.select_one("#run-button")["aria-keyshortcuts"] == "r"
    assert [tab["aria-keyshortcuts"] for tab in soup.select('#tabs [role="tab"]')] == [str(n) for n in range(1, len(soup.select('#tabs [role="tab"]')) + 1)]
    assert soup.select_one("#ticker")["aria-keyshortcuts"] == "/"
    assert soup.select_one("#theme-toggle")["aria-keyshortcuts"] == "t"
    assert soup.select_one("#keys-button")["aria-keyshortcuts"] == "?"


def css_rule(selector: str) -> str:
    """The body of the stylesheet's rule whose selector is exactly ``selector``."""
    css = (WEB / "styles.css").read_text(encoding="utf-8")
    start = css.index(selector + " {")
    return css[start : css.index("}", start)]


def test_both_themes_define_every_colour_token() -> None:
    paper = css_rule(":root")
    term = css_rule(':root[data-theme="terminal"]')
    tokens = ["--bg", "--surface", "--ink", "--ink-2", "--accent", "--support", "--challenge", "--neutral", "--limit", "--model", "--reject", "--change", "--rule", "--neg", "--mark-bg"]
    for token in tokens:
        assert f"{token}:" in paper, token
        assert f"{token}:" in term, token


def test_reduced_motion_turns_off_animation() -> None:
    css = (WEB / "styles.css").read_text(encoding="utf-8")
    block = css[css.index("@media (prefers-reduced-motion: reduce)") :]
    assert "animation: none" in block[: block.index("}\n}")]
