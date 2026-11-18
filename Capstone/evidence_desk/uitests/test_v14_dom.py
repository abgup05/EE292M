"""Browser-level checks of version 14 on the page: computed claims, the thesis over time, as-of runs, the ledger.

`make uitest` renders the version 14 samples (/?sample=computed, /?sample=as-of in the Terminal
theme, /?sample=restatements), which draw the backend's example payloads (docs/examples/v14,
written by `make examples`, copied unedited by `make sample-v14`), and runs uitests/v14.html,
which drives the page's own code for what the examples do not show (a second reader, the
ledger lookup's answers, a run asked for as of a date, the watch API's version 14 fields).
These tests compare what the page drew with the JSON: the page computes no outcome, margin,
flip or change, and draws every one of them.
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
EXAMPLES = ROOT / "docs" / "examples" / "v14"
RESULTS = ROOT / "results"
COPIES = {
    "sample-computed.json": "run.json",
    "sample-as-of.json": "as-of-run.json",
    "sample-restatements.json": "restatements.json",
    "sample-readers.json": "run-readers.json",
}
DUMPS = {"computed": ("dom-computed.html", "sample-computed.json"), "as-of": ("dom-as-of.html", "sample-as-of.json")}
OUTCOME_GLYPH = {"holds": "⊨", "fails": "⊭", "cannot_compute": "⊘"}
COUNTED = {"supports": "Counted as support", "challenges": "Counted as a challenge"}
MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]


def payload(name: str) -> Any:
    return json.loads((WEB / name).read_text(encoding="utf-8"))


def words(node: Tag | None) -> str:
    assert node is not None
    return " ".join(node.get_text().split())


def date_label(day: str) -> str:
    """The page's way of writing a date: 1 Mar 2026 (formatting, not a result)."""
    year, month, dom = day[:10].split("-")
    return f"{int(dom)} {MONTHS[int(month) - 1]} {year}"


@cache
def page(name: str) -> BeautifulSoup:
    dump_name, sample = DUMPS[name]
    dump = RESULTS / dump_name
    require_fresh(dump, WEB / sample)
    soup = BeautifulSoup(dump.read_text(encoding="utf-8"), "html.parser")
    if soup.select_one("#run-view") is None or soup.select_one("#run-view[hidden]") is not None:
        pytest.fail(f"{dump.name}: the page did not render a run")
    return soup


@cache
def ledger_page() -> BeautifulSoup:
    dump = RESULTS / "dom-restatements.html"
    require_fresh(dump, WEB / "sample-restatements.json")
    soup = BeautifulSoup(dump.read_text(encoding="utf-8"), "html.parser")
    if soup.select_one("#ledger-view") is None or soup.select_one("#ledger-view[hidden]") is not None:
        pytest.fail(f"{dump.name}: the page did not show the ledger")
    return soup


def both(test: Any) -> Any:
    return pytest.mark.parametrize("name", sorted(DUMPS))(test)


def record(name: str) -> dict[str, Any]:
    return payload(DUMPS[name][1])


def compiled(name: str) -> list[dict[str, Any]]:
    return [claim for claim in record(name)["claims"] if claim.get("computed")]


# ---------------------------------------------------------------- the copies


@pytest.mark.parametrize(("copy", "source"), sorted(COPIES.items()))
def test_the_samples_are_the_example_payloads_unedited(copy: str, source: str) -> None:
    assert (WEB / copy).read_bytes() == (EXAMPLES / source).read_bytes(), (
        f"src/web/{copy} differs from docs/examples/v14/{source}: run `make sample-v14`"
    )


@both
def test_the_page_says_where_the_sample_comes_from_and_that_no_model_answered(name: str) -> None:
    note = words(page(name).select_one("#run-head [data-sample-note]"))
    for phrase in ("docs/examples/v14", "make examples", "extractive engine", "no model was asked", "no cassette", "unedited", "make sample-v14"):
        assert phrase in note, phrase


# ---------------------------------------------------------------- the computed test on each claim


@both
def test_each_compiled_claim_shows_its_expression_outcome_and_counted_state(name: str) -> None:
    soup = page(name)
    claims = compiled(name)
    assert claims, "the example has compiled claims"
    for claim in claims:
        test = claim["computed"]
        block = soup.select_one(f'#claim-list [data-computed-test="{claim["id"]}"]')
        assert block is not None, claim["id"]
        assert words(block.select_one("[data-canonical]")) == test["canonical"]
        outcome = block.select_one(".ct-result [data-outcome]")
        assert outcome["data-outcome"] == test["outcome"]
        assert words(outcome) == f'{OUTCOME_GLYPH[test["outcome"]]}{test["outcome_label"]}'
        counted = block.select_one("[data-counted]")
        if test["counted_as"]:
            assert counted["data-counted"] == test["counted_as"]
            assert words(counted) == COUNTED[test["counted_as"]]
        else:
            assert counted["data-counted"] == "none" and words(counted) == "Not counted"
        bound = block.select_one("[data-bound]")
        assert (words(bound) if bound else "") == test["bound"]
        reason = block.select_one("[data-reason]")
        assert (words(reason).endswith(test["reason"]) if reason else test["reason"] == "")
        margin = words(block.select_one("[data-margin]"))
        assert margin == (test["margin_display"] or "none: not computed")
        assert [words(li) for li in block.select(".ct-arith li")] == test["arithmetic"]


@both
def test_each_operand_shows_its_value_and_every_fact_with_its_filing(name: str) -> None:
    soup = page(name)
    cik = record(name)["company"]["cik"]
    for claim in compiled(name):
        block = soup.select_one(f'#claim-list [data-computed-test="{claim["id"]}"]')
        rows = block.select(".ct-table tbody tr")
        operands = claim["computed"]["operands"]
        assert [row["data-operand"] for row in rows] == [op["term"] for op in operands]
        for row, operand in zip(rows, operands, strict=True):
            assert words(row.select_one("[data-operand-value]")).startswith(operand["display"])
            facts = row.select("li.ct-fact")
            assert [li["data-fact-accession"] for li in facts] == [ref["accession"] for ref in operand["inputs"]]
            for li, ref in zip(facts, operand["inputs"], strict=True):
                assert f'{ref["form"]} filed {date_label(ref["filed"])}' in words(li)
                plain = ref["accession"].replace("-", "")
                assert li.select_one("a")["href"] == f"https://www.sec.gov/Archives/edgar/data/{cik}/{plain}/{ref['accession']}-index.htm"


@both
def test_a_claim_that_did_not_compile_shows_its_note_quietly(name: str) -> None:
    soup = page(name)
    not_compiled = [claim for claim in record(name)["claims"] if not claim.get("computed")]
    assert not_compiled, "the example has a claim that does not compile"
    for claim in not_compiled:
        note = soup.select_one(f'#claim-list [data-compile-note="{claim["id"]}"]')
        assert note is not None and claim["compile_note"] in words(note)
        assert soup.select_one(f'#claim-list [data-computed-test="{claim["id"]}"]') is None


@both
def test_the_board_says_which_part_of_each_verdict_is_computed(name: str) -> None:
    soup = page(name)
    for claim in record(name)["claims"]:
        row = soup.select_one(f'#scorecard li[data-claim-id="{claim["id"]}"]')
        part = row.select_one("[data-board-computed]")
        if claim.get("computed"):
            assert part["data-board-computed"] == claim["computed"]["outcome"]
            assert words(part).startswith("Computed, no model:")
        else:
            assert part["data-board-computed"] == "none"
        # The findings' part stays the engine's, in its own words.
        assert row.select_one(".assessed") is not None


@both
def test_who_read_each_claim_is_the_records(name: str) -> None:
    soup = page(name)
    run = record(name)
    assert soup.select_one("[data-claim-readers]")["data-claim-readers"] == run["claim_readers"]
    for claim in run["claims"]:
        drawn = soup.select(f'#claim-list [data-readings="{claim["id"]}"] .readings li')
        assert [(li["data-reader"], li["data-canonical"]) for li in drawn] == [(r["reader"], r["canonical"]) for r in claim["readings"]]
        if claim.get("computed"):
            by = soup.select_one(f'#claim-list [data-readings="{claim["id"]}"] [data-read-by]')
            assert by["data-read-by"] == " ".join(claim["computed"]["read_by"])
    assert "Readings differ" not in words(soup.select_one("#claim-list"))


@both
def test_the_status_line_carries_the_computed_counts(name: str) -> None:
    soup = page(name)
    coverage = record(name)["coverage"]
    line = soup.select_one("#status-banner [data-computed-line]")
    assert line is not None
    for field in ("claims_compiled", "claims_total", "computed_holds", "computed_fails", "computed_cannot"):
        assert words(line.select_one(f'[data-coverage="{field}"]')) == f"{coverage[field]:,}", field


# ---------------------------------------------------------------- the thesis over time


@both
def test_the_thesis_over_time_sits_under_the_time_line(name: str) -> None:
    soup = page(name)
    ids = [node.get("id") for node in soup.select("#run-view > *") if node.get("id")]
    assert ids.index("tot-section") == ids.index("timeline-section") + 1
    assert soup.select_one("#tot-section[hidden]") is None


@both
def test_each_history_has_its_points_and_flips(name: str) -> None:
    soup = page(name)
    for claim in compiled(name):
        test = claim["computed"]
        lane = soup.select_one(f'#tot [data-tot-claim="{claim["id"]}"]')
        assert lane is not None, claim["id"]
        assert words(lane.select_one("[data-history-note]")) == test["history_note"]
        history = test["history"]
        assert lane["data-points"] == str(len(history))
        if not history:
            assert lane.select_one("svg") is None and "no-history" in lane["class"]
            continue
        rows = lane.select("tr[data-point]")
        assert [(r["data-point"], r["data-outcome"], r["data-flipped"]) for r in rows] == [
            (p["filed"], p["outcome"], str(p["flipped"]).lower()) for p in history
        ]
        assert [c["data-point"] for c in lane.select("svg circle.tot-pt")] == [p["filed"] for p in history]
        flips = [p for p in history if p["flipped"]]
        assert [c["data-flip"] for c in lane.select("svg circle.tot-flip")] == [p["filed"] for p in flips]
        listed = lane.select(".tot-flips li")
        assert [(li["data-flip"], li["data-flip-to"]) for li in listed] == [(p["filed"], p["outcome"]) for p in flips]
        for li, point in zip(listed, flips, strict=True):
            assert f'{point["form"]} filed {date_label(point["filed"])}' in words(li)


def test_the_example_history_flips_where_the_record_says() -> None:
    gross = next(c for c in compiled("computed") if c["id"] == "c1")["computed"]
    flips = [p["filed"] for p in gross["history"] if p["flipped"]]
    assert len(gross["history"]) == 20 and len(flips) == 4
    lane = page("computed").select_one('#tot [data-tot-claim="c1"]')
    assert [li["data-flip"] for li in lane.select(".tot-flips li")] == flips


# ---------------------------------------------------------------- as of a date


def test_a_run_as_of_a_past_date_says_so_unmistakably() -> None:
    soup = page("as-of")
    as_of = record("as-of")["as_of"]
    banner = soup.select_one("#asof-banner")
    assert banner is not None and not banner.has_attr("hidden")
    assert banner.select_one("[data-as-of-requested]")["data-as-of-requested"] == as_of["requested"]
    assert words(banner.select_one("time")) == date_label(as_of["requested"])
    assert words(banner.select_one("[data-as-of-note]")) == as_of["requested_note"]
    assert "as-of-run" in soup.select_one("body")["class"]
    assert soup.select_one("#cmd-asof [data-cmd-as-of-requested]")["data-cmd-as-of-requested"] == as_of["requested"]
    # The banner is the first thing in the note, before the company's name.
    assert soup.select_one("#run-view > *")["id"] == "asof-banner"
    # The time line ends at the date the run is as of, not at the day it ran.
    assert words(soup.select_one('[data-tl="run"] text')) == f'As of {date_label(as_of["requested"])}'
    for claim in compiled("as-of"):
        block = soup.select_one(f'[data-computed-test="{claim["id"]}"]')
        assert block.select_one("[data-test-as-of]")["data-test-as-of"] == claim["computed"]["as_of"]


def test_a_run_of_the_newest_filings_has_no_banner() -> None:
    soup = page("computed")
    assert record("computed")["as_of"]["requested"] is None
    assert soup.select_one("#asof-banner").has_attr("hidden")
    assert words(soup.select_one('[data-tl="run"] text')).startswith("Run ")
    assert "as-of-run" not in (soup.select_one("body").get("class") or [])


def test_the_as_of_banner_prints() -> None:
    css = (WEB / "styles.css").read_text(encoding="utf-8")
    printed = css[css.index("@media print") :]
    hidden = printed[: printed.index("{ display: none !important; }")]
    assert ".asof-banner" not in hidden and "#asof-banner" not in hidden
    assert ".asof-banner {" in printed


# ---------------------------------------------------------------- the restatement ledger


def test_the_ledger_has_a_row_for_every_restated_period() -> None:
    soup = ledger_page()
    ledger = payload("sample-restatements.json")
    rows = soup.select("[data-ledger] tbody tr")
    assert len(rows) == len(ledger["entries"]) == ledger["periods_restated"]
    assert [r["data-ledger-entry"] for r in rows] == [f'{e["key"]}:{e["start"] or ""}:{e["end"]}' for e in ledger["entries"]]
    for row, entry in zip(rows, ledger["entries"], strict=True):
        first = row.select(".ledger-first li")
        later = row.select(".ledger-later li")
        assert [li["data-ledger-value"] for li in first + later] == [v["accession"] for v in entry["values"]]
        assert words(first[0]).startswith(entry["values"][0]["display"])
        for li, value in zip(later, entry["values"][1:], strict=True):
            assert words(li).startswith(value["display"])
            change = words(li.select_one("[data-change]"))
            assert value["change_display"] in change and value["change_percent_display"] in change
            assert (li.select_one("[data-returns]") is not None) == value["returns_to_earlier"]
        assert words(row.select("td")[-1]) == str(entry["reports"])


def test_the_ledger_states_its_denominator_tolerance_and_source() -> None:
    soup = ledger_page()
    ledger = payload("sample-restatements.json")
    assert words(soup.select_one('[data-ledger-field="periods_restated"]')) == str(ledger["periods_restated"])
    assert words(soup.select_one('[data-ledger-field="periods_checked"]')) == str(ledger["periods_checked"])
    assert ledger["tolerance_note"] in words(soup.select_one("[data-ledger-tolerance]"))
    for note in ledger["notes"]:
        assert note in words(soup.select_one(".ledger-notes"))
    sample = words(soup.select_one("#ledger-head [data-sample-note]"))
    for phrase in ("docs/examples/v14/restatements.json", "make examples", "no model", "make sample-v14"):
        assert phrase in sample, phrase


# ---------------------------------------------------------------- what the examples do not show (uitests/v14.html)


@cache
def steps() -> dict[str, Tag]:
    dump = RESULTS / "dom-v14.html"
    require_fresh(dump, ROOT / "uitests" / "v14.html")
    soup = BeautifulSoup(dump.read_text(encoding="utf-8"), "html.parser")
    done = soup.select_one("#done")
    if done is None or done.get("data-done") != "true":
        pytest.fail(f"the version 14 harness did not finish: {words(done) if done else 'no #done'}")
    return {li["data-step"]: li for li in soup.select("#steps > li")}


def recorded(step: str, field: str) -> Any:
    return json.loads(steps()[step][f"data-{field}"])


def drawn(step: str) -> dict[str, dict[str, Any]]:
    return {claim["id"]: claim for claim in recorded(step, "claims")}


def test_the_harness_ran_every_step_and_made_no_unexpected_call() -> None:
    assert list(steps()) == ["sample", "readers", "and", "ledger-422", "ledger-200", "ledger-503", "run-422", "run-as-of", "inbox", "theses"]
    for step in steps():
        assert recorded(step, "unexpected") == [], step


def marks(claim: dict[str, Any]) -> list[tuple[str, str]]:
    return [(reader, mark) for reader, mark, _ in claim["marks"]]


def test_readings_that_differ_are_all_shown_and_not_counted() -> None:
    claims = drawn("readers")
    c1 = claims["c1"]
    assert c1["readers"] == ["grammar", "model", "model_2"] and len(set(c1["canonicals"])) == 3
    assert c1["differ"] and c1["counted"] == "differ" and c1["agreement"] == "not_agreed"
    assert c1["agreementLabel"] == "not counted: no two readers agree"
    assert marks(c1) == [("grammar", "same"), ("model", "other"), ("model_2", "refused")]
    assert "Readings differ: not counted" in c1["board"] and "Readings differ: not counted" in c1["flag"]
    assert c1["boardReaders"] == "" and c1["dissent"] == ""
    assert c1["note"].startswith("Note: Readings differ: not counted.")
    # The grammar's test of a claim it did not compile: no test, the model's reading beside it.
    c3 = claims["c3"]
    assert c3["readers"] == ["grammar", "model", "model_2"] and c3["canonicals"][0] == "none" and c3["differ"]
    assert marks(c3) == [("grammar", "refused"), ("model", "other"), ("model_2", "refused")]
    assert "Readings differ: not counted" in c3["compileNote"]
    assert "grammar, model and model_2" in steps()["readers"]["data-readers-line"]


def test_a_dissent_is_shown_and_the_test_still_counts() -> None:
    c2 = drawn("readers")["c2"]
    assert c2["agreement"] == "agreed_with_dissent" and c2["agreementLabel"] == "counted, with one dissenting reading"
    assert marks(c2) == [("grammar", "same"), ("model", "same"), ("model_2", "dissent")]
    assert c2["counted"] == "challenges" and not c2["differ"]
    assert c2["dissent"] == "≠ Dissent: Model 2 read yoy(revenue)[Q] > 100%"
    assert c2["boardReaders"] == "2 of 3 readers, one dissenting"


def test_readings_that_agree_count_and_say_how_many_readers_agreed() -> None:
    claims = drawn("readers")
    c4, c5 = claims["c4"], claims["c5"]
    assert marks(c4) == [("grammar", "same"), ("model", "same"), ("model_2", "same")]
    assert c4["agreement"] == "agreed" and c4["counted"] == "supports" and c4["boardReaders"] == "3 of 3 readers"
    # A refusal is not a dissent: two of three, counted, no dissent line.
    assert marks(c5) == [("grammar", "same"), ("model", "same"), ("model_2", "refused")]
    assert c5["agreement"] == "agreed" and c5["boardReaders"] == "2 of 3 readers" and c5["dissent"] == ""
    # Each mark says what the reader read, or why it read nothing, with who the reader is.
    reason = next(why for reader, _, why in c5["marks"] if reader == "model_2")
    assert reason == "Model 2 (claude-sonnet-5-5 (made in this harness: no model was asked)) read no test: the model reader: a year this tool does not place"
    # The rule in words, in the run head and in "How to read this".
    rule = steps()["readers"]["data-rule"]
    assert rule.startswith("Three readers (grammar, model and model_2)")
    assert steps()["readers"]["data-howto-rule"] == f"This run's rule: {rule}"
    # The sample itself has one reader: its mark, and nothing differs.
    for claim in drawn("sample").values():
        assert not claim["differ"] and claim["readers"] == ["grammar"]
        assert claim["agreement"] in ("one_reader", "none", "")


def test_a_test_of_two_parts_draws_every_part_and_how_they_combine() -> None:
    step = steps()["and"]
    test = json.loads(step["data-test"])
    parts = json.loads(step["data-parts"])
    assert [p["index"] for p in parts] == ["0", "1"]
    for drawn_part, part in zip(parts, test["parts"], strict=True):
        assert drawn_part["outcome"] == part["outcome"]
        assert drawn_part["bound"] == part["bound"]
        assert drawn_part["margin"] == part["margin_display"]
        assert drawn_part["arithmetic"] == part["arithmetic"]
        assert drawn_part["sides"].startswith(f'Compared: {part["left"]["term"]} = {part["left"]["display"]}')
    # The record's last line of arithmetic says how the parts came out together; the whole test's sides are not shown as the first part's.
    assert step["data-tally"] == f'Together: {test["arithmetic"][-1]}'
    assert "both hold" in step["data-combine"]
    assert step["data-sides-outside-parts"] == "0"
    assert json.loads(step["data-operands"]) == [op["term"] for op in test["operands"]]
    assert step["data-margin"] == "each part has its own"
    assert step["data-outcome"] == test["outcome"]
    # One history line for the whole test, and the table says whose sides each point gives.
    assert "One line for the whole test of 2 parts" in step["data-lane"]
    assert json.loads(step["data-lane-head"])[4:6] == ["First part's left", "First part's right"]


def test_the_ledger_lookup_sends_the_date_and_says_each_refusal() -> None:
    assert [c["key"] for c in recorded("ledger-422", "calls")] == ["GET /api/companies/NVDA/restatements?as_of=2008-06-30"]
    # The refusal mark (!), then the server's words, under the date field.
    assert steps()["ledger-422"]["data-as-of-error"] == "! " + "as_of must be on or after 2009-01-01: XBRL facts begin in 2009"
    assert [c["key"] for c in recorded("ledger-200", "calls")] == ["GET /api/companies/NVDA/restatements"]
    ledger = payload("sample-restatements.json")
    assert steps()["ledger-200"]["data-rows"] == str(len(ledger["entries"]))
    assert recorded("ledger-200", "views") == ["ledger-view"]
    assert "EDGAR could not give the company facts" in steps()["ledger-503"]["data-form-errors"]


def test_a_run_asked_for_as_of_a_date_sends_it_and_draws_the_banner() -> None:
    refused = recorded("run-422", "calls")
    assert [c["key"] for c in refused] == ["POST /api/runs"]
    assert json.loads(refused[0]["body"])["as_of"] == "2030-01-01"
    # The refusal mark (!), then the server's words, under the date field.
    assert steps()["run-422"]["data-as-of-error"] == "! " + "as_of is in the future: a run can only read what has been filed"
    sent = [c for c in recorded("run-as-of", "calls") if c["key"] == "POST /api/runs"]
    as_of_run = payload("sample-as-of.json")
    assert json.loads(sent[0]["body"])["as_of"] == as_of_run["inputs"]["as_of"]
    assert recorded("run-as-of", "views") == ["run-view"]
    step = steps()["run-as-of"]
    assert as_of_run["as_of"]["requested_note"] in step["data-banner"]
    assert step["data-cmd"] == f'Run as of {date_label(as_of_run["as_of"]["requested"])} ·'
    assert "as-of-run" in step["data-body-class"]


def test_an_inbox_item_shows_its_computed_changes_and_claims_line() -> None:
    computed = recorded("inbox", "computed")
    assert len(computed) == 1 and computed[0]["outcomes"] == ["fails", "holds"]
    assert "gross_margin[Q] > gross_margin[Q-4]" in computed[0]["text"]
    lines = dict(recorded("inbox", "claims-lines"))
    inbox = json.loads((ROOT / "docs" / "examples" / "v13" / "inbox.json").read_text(encoding="utf-8"))
    for item in inbox["items"]:
        if item["collapsed"]:
            continue
        assert lines[item["id"]] == ((item["moved"] or {}).get("claims_line") or "")
    assert steps()["inbox"]["data-folded"] == str(inbox["folded"])


def test_each_saved_thesis_carries_its_own_watch() -> None:
    assert [c["key"] for c in recorded("theses", "calls")] == ["GET /api/theses"]
    tags = dict(recorded("theses", "tags"))
    assert tags["th-unwatched"] == ""
    watched = next(k for k in tags if k != "th-unwatched")
    assert tags[watched] == "◉ On watch · Ask me first · 3 unread"
