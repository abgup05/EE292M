"""Browser-level checks of the live three-reader sample and of the two-model example.

`make uitest` renders /?sample=run-live, a bare run copied unedited from a live NVIDIA run of
18 Nov 2026 (results/run-7fa4a528d428.json: claude-opus-5-5 reading the filings and
claude-haiku-5-5 checking meaning, both through the Anthropic API, and three claim readers: the
grammar, claude-haiku-5-5 and claude-sonnet-5-5), and /?sample=readers in the Terminal theme,
docs/examples/v14/run-readers.json (six claims of set C, the model readers' answers replayed from
a cassette recorded through the API). These tests compare what the page drew with the JSON: who
read each claim and how (from `read_by`, `dissent` and each reading), the record's agreement,
how many readers agreed on the board, every part of a test held in each of several periods, what
the verdict rule counted, and the history. The page compares no readings and computes no outcome.
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
ORIGINAL = RESULTS / "run-7fa4a528d428.json"
DUMPS = {"run-live": ("dom-run-live.html", "sample-run-live.json"), "readers": ("dom-readers.html", "sample-readers.json")}
COUNTED = {"supports": "Counted as support", "challenges": "Counted as a challenge"}
SHORT = {"grammar": "Grammar", "model": "Model 1", "model_2": "Model 2"}
each_sample = pytest.mark.parametrize("name", sorted(DUMPS))


@cache
def record(name: str) -> dict[str, Any]:
    return json.loads((WEB / DUMPS[name][1]).read_text(encoding="utf-8"))


@cache
def page(name: str) -> BeautifulSoup:
    dump_name, sample = DUMPS[name]
    dump = RESULTS / dump_name
    require_fresh(dump, WEB / sample)
    soup = BeautifulSoup(dump.read_text(encoding="utf-8"), "html.parser")
    if soup.select_one("#run-view") is None or soup.select_one("#run-view[hidden]") is not None:
        pytest.fail(f"{dump.name}: the page did not render the run")
    return soup


def words(node: Tag | None) -> str:
    assert node is not None
    return " ".join(node.get_text().split())


def docket(name: str, claim_id: str) -> Tag:
    node = page(name).select_one(f'#claim-list details.claim[data-docket="{claim_id}"]')
    assert node is not None, claim_id
    return node


def expected_mark(reading: dict[str, Any], test: dict[str, Any] | None) -> str:
    """The mark the record's own lists call for: refused, in `read_by`, in `dissent`, or another test."""
    if reading["canonical"] in ("", "none"):
        return "refused"
    if test and reading["reader"] in test["read_by"]:
        return "same"
    if test and any(other["reader"] == reading["reader"] for other in test["dissent"]):
        return "dissent"
    return "other"


# ---------------------------------------------------------------- where the live sample comes from


def test_the_live_sample_is_the_run_unedited() -> None:
    if not ORIGINAL.is_file():
        pytest.skip("results/run-7fa4a528d428.json is not on this machine (results/ is not committed)")
    assert (WEB / "sample-run-live.json").read_bytes() == ORIGINAL.read_bytes()


def test_the_live_sample_is_the_first_offered_on_the_first_screen() -> None:
    soup = BeautifulSoup((WEB / "index.html").read_text(encoding="utf-8"), "html.parser")
    first = soup.select_one("#sample-nav li a")
    assert first["id"] == "live-link" and first["href"] == "?sample=run-live"
    assert "Anthropic API" in words(first.find_parent("li"))


def test_the_live_sample_says_where_it_came_from_and_who_answered() -> None:
    note = words(page("run-live").select_one("#run-head [data-sample-note]"))
    for phrase in ("live run of 18 November 2026", "run-7fa4a528d428", "Anthropic API", "claude-opus-5-5", "claude-haiku-5-5", "claude-sonnet-5-5", "copied unedited from results/run-7fa4a528d428.json"):
        assert phrase in note, phrase
    run = record("run-live")
    assert run["engine_detail"].endswith("via the Anthropic API") and run["claim_reader_detail"].count("via the Anthropic API") == 2


def test_the_readers_example_says_its_answers_were_replayed() -> None:
    note = words(page("readers").select_one("#run-head [data-sample-note]"))
    for phrase in ("docs/examples/v14/run-readers.json", "replayed", "eval/cassettes/claim-readers", "Anthropic API", "extractive engine", "make sample-v14"):
        assert phrase in note, phrase


# ---------------------------------------------------------------- who read each claim


@each_sample
def test_the_head_and_how_to_read_this_carry_the_reading_rule(name: str) -> None:
    soup, run = page(name), record(name)
    head = soup.select_one("#run-head [data-claim-readers]")
    assert head["data-claim-readers"] == run["claim_readers"]
    assert words(head.select_one("[data-claim-reading-rule]")) == run["claim_reading_rule"]
    assert words(soup.select_one("#howto-reading-rule")) == f"This run's rule: {run['claim_reading_rule']}"


@each_sample
def test_each_reader_has_a_mark_on_each_claim_from_the_records_lists(name: str) -> None:
    for claim in record(name)["claims"]:
        test = claim.get("computed")
        drawn = docket(name, claim["id"]).select("[data-reader-mark]")
        assert [(m["data-reader-mark"], m["data-mark"]) for m in drawn] == [
            (r["reader"], expected_mark(r, test)) for r in claim["readings"]
        ], claim["id"]
        for mark, reading in zip(drawn, claim["readings"], strict=True):
            assert words(mark.select_one(".reader-short")) == SHORT[reading["reader"]]
            why = mark["data-why"]
            # The hover and focus text: what the reader read, or why it read nothing, also for a screen reader.
            assert (reading["reason"] if reading["canonical"] == "none" else reading["canonical"]) in why
            assert why in words(mark.select_one(".visually-hidden"))
            assert mark["tabindex"] == "0"


@each_sample
def test_each_computed_test_shows_the_records_agreement_and_counted_state(name: str) -> None:
    for claim in record(name)["claims"]:
        test = claim.get("computed")
        if not test:
            continue
        block = docket(name, claim["id"]).select_one("[data-computed-test]")
        row = block.select_one("[data-readers]")
        assert row["data-agreement"] == test["agreement"]
        assert words(row.select_one("[data-agreement-label]")) == test["agreement_label"]
        assert (row.select_one("[data-dissent]") is None) == (test["dissent"] == [])
        counted = block.select_one(".ct-result [data-counted]")
        assert counted["data-counted"] == (test["counted_as"] or "none")
        assert words(counted) == COUNTED.get(test["counted_as"], "Not counted")


@each_sample
def test_the_board_says_how_many_readers_agreed(name: str) -> None:
    soup = page(name)
    for claim in record(name)["claims"]:
        row = soup.select_one(f'#scorecard li[data-claim-id="{claim["id"]}"]')
        test = claim.get("computed")
        readers = row.select_one("[data-board-readers]")
        if not test:
            assert readers is None and row.select_one('[data-board-computed="none"]') is not None
            continue
        assert words(readers) == f'{len(test["read_by"])} of {len(claim["readings"])} readers'
        assert words(row.select_one("[data-board-computed]")).startswith("Computed, no model:")


@each_sample
def test_a_claim_no_reader_could_read_shows_each_readers_reason_quietly(name: str) -> None:
    unread = [c for c in record(name)["claims"] if not c.get("computed")]
    assert unread
    for claim in unread:
        note = docket(name, claim["id"]).select_one("[data-compile-note]")
        assert claim["compile_note"] in words(note)
        listed = note.select("[data-readings] .readings li")
        # With several readers the reasons are in the open, not behind a fold.
        assert note.select_one("details[data-readings]") is None
        assert [li["data-reader"] for li in listed] == [r["reader"] for r in claim["readings"]]
        for li, reading in zip(listed, claim["readings"], strict=True):
            assert reading["reason"] in words(li)


def test_the_grammar_refused_and_both_models_agreed_in_the_readers_example() -> None:
    run = record("readers")
    by_models = [c for c in run["claims"] if c.get("computed") and c["computed"]["read_by"] == ["model", "model_2"]]
    assert len(by_models) == 3
    soup = page("readers")
    for claim in by_models:
        marks = [(m["data-reader-mark"], m["data-mark"]) for m in docket("readers", claim["id"]).select("[data-reader-mark]")]
        assert marks == [("grammar", "refused"), ("model", "same"), ("model_2", "same")]
        row = soup.select_one(f'#scorecard li[data-claim-id="{claim["id"]}"]')
        assert words(row.select_one("[data-board-readers]")) == "2 of 3 readers"
    # Two writings of one test: the reading list shows the normal form the rule compared.
    c1 = next(c for c in run["claims"] if c["id"] == "c1")
    compared = [n["data-normal-form"] for n in docket("readers", "c1").select("[data-normal-form]")]
    assert compared == [r["normal_form"] for r in c1["readings"] if r["normal_form"] != r["canonical"]]


# ---------------------------------------------------------------- a test held in each of several periods


def each_claim() -> dict[str, Any]:
    return next(c for c in record("run-live")["claims"] if (c.get("computed") or {}).get("combines") == "each")


def test_the_each_test_draws_every_part_with_its_sides_arithmetic_and_outcome() -> None:
    claim = each_claim()
    test = claim["computed"]
    block = docket("run-live", claim["id"]).select_one("[data-computed-test]")
    assert words(block.select_one("[data-canonical]")) == test["canonical"]
    assert block.select_one('[data-combines="each"]') is not None
    drawn = block.select(".ct-part")
    assert len(drawn) == len(test["parts"]) == 4
    for li, part in zip(drawn, test["parts"], strict=True):
        assert li["data-outcome"] == part["outcome"]
        assert words(li.select_one("[data-part-bound]")) == part["bound"]
        assert words(li.select_one("[data-part-margin]")) == part["margin_display"]
        assert [words(x) for x in li.select(".ct-arith li")] == part["arithmetic"]
        sides = words(li.select_one("[data-sides]"))
        right = part["right"]["display"] if part["right"]["term"] == part["right"]["display"] else f'{part["right"]["term"]} = {part["right"]["display"]}'
        assert sides == f'Compared: {part["left"]["term"]} = {part["left"]["display"]} {part["comparison"]} {right}'
    assert words(block.select_one("[data-combine-tally]")) == f'Together: {test["arithmetic"][-1]}'
    # The whole test's left and right are the first part's: not drawn as the whole test's sides.
    assert [n for n in block.select("[data-sides]") if n.find_parent(class_="ct-part") is None] == []
    assert [r["data-operand"] for r in block.select(".ct-table tbody tr")] == [op["term"] for op in test["operands"]]
    assert words(block.select_one("[data-margin]")) == "each part has its own"


def test_the_each_test_has_one_history_line_and_says_whose_sides_each_point_gives() -> None:
    claim = each_claim()
    test = claim["computed"]
    lane = page("run-live").select_one(f'#tot [data-tot-claim="{claim["id"]}"]')
    assert lane["data-points"] == str(len(test["history"]))
    assert len(lane.select("svg path.tot-step")) == 1
    assert [c["data-point"] for c in lane.select("svg circle.tot-pt")] == [p["filed"] for p in test["history"]]
    assert test["parts"][0]["canonical"] in words(lane.select_one("[data-history-parts]"))
    heads = [words(th) for th in lane.select("thead th")]
    assert heads[4:6] == ["First part's left", "First part's right"]
    rows = lane.select("tr[data-point]")
    for row, point in zip(rows, test["history"], strict=True):
        cells = [words(td) for td in row.select("td")]
        assert cells[4:6] == [point["left_display"] or "—", point["right_display"] or "—"]
    flips = [p for p in test["history"] if p["flipped"]]
    listed = lane.select(".tot-flips li")
    assert [(li["data-flip"], li["data-flip-to"]) for li in listed] == [(p["filed"], p["outcome"]) for p in flips]
    for li, point in zip(listed, flips, strict=True):
        assert f'(first part {point["left_display"]} against {point["right_display"]})' in words(li)


@each_sample
def test_every_computed_claim_has_its_history_lane(name: str) -> None:
    soup = page(name)
    for claim in record(name)["claims"]:
        lane = soup.select_one(f'#tot [data-tot-claim="{claim["id"]}"]')
        if not claim.get("computed"):
            assert lane is None
            continue
        assert lane["data-points"] == str(len(claim["computed"]["history"]))
        assert words(lane.select_one("[data-history-note]")) == claim["computed"]["history_note"]
