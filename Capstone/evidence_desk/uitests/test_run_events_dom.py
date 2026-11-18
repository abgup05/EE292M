"""Browser-level checks of the live-run sample and of the time line.

`make uitest` renders /?sample=run-events, a bare run copied unedited from a live NVIDIA run of
18 Nov 2026 (results/run-39d0b17b5396.json, answered by the Anthropic API), and the two recorded
samples. These tests compare each dump with its JSON: where the sample comes from, the command
bar, the caution and the predated mark, the 8-K register, and every mark of the time line. The
page computes none of these: each is a record field, or wording from /api/meta (here taken from
app.core.policy, which /api/meta serves).
"""

from __future__ import annotations

import json
from functools import cache
from pathlib import Path
from typing import Any

import pytest
from bs4 import BeautifulSoup, Tag
from test_dom import require_fresh

from app.core.policy import EVENTS_HEADING

ROOT = Path(__file__).resolve().parents[1]
WEB = ROOT / "src" / "web"
RESULTS = ROOT / "results"
SAMPLE = WEB / "sample-run-events.json"
ORIGINAL = RESULTS / "run-39d0b17b5396.json"
DUMPS = {
    "run-events": (SAMPLE, "dom-run-events.html"),
    "run": (WEB / "sample-run.json", "dom-sample.html"),
    "run-tagged": (WEB / "sample-run-tagged.json", "dom-run-tagged.html"),
    "synthetic": (WEB / "sample-synthetic.json", "dom-synthetic.html"),
}
every_run = pytest.mark.parametrize("name", sorted(DUMPS))


@cache
def record(name: str) -> dict[str, Any]:
    """The run a sample holds: the bare run, or the `run` of a {note, meta, run} sample."""
    payload = json.loads(DUMPS[name][0].read_text(encoding="utf-8"))
    return payload if "run" not in payload else payload["run"]


@cache
def page(name: str) -> BeautifulSoup:
    dump = RESULTS / DUMPS[name][1]
    require_fresh(dump, DUMPS[name][0])
    soup = BeautifulSoup(dump.read_text(encoding="utf-8"), "html.parser")
    if soup.select_one("#run-view") is None or soup.select_one("#run-view[hidden]") is not None:
        pytest.fail(f"{dump.name}: the page did not render the run")
    return soup


def words(node: Tag | None) -> str:
    assert node is not None
    return " ".join(node.get_text().split())


# ---------------------------------------------------------------- the live-run sample


def test_the_sample_is_the_live_run_unedited() -> None:
    """The sample is a byte-for-byte copy of the run's record, when that record is on this machine."""
    if not ORIGINAL.is_file():
        pytest.skip("results/run-39d0b17b5396.json is not on this machine (results/ is not committed)")
    assert SAMPLE.read_bytes() == ORIGINAL.read_bytes()


def test_the_sample_is_the_live_nvidia_run_answered_by_the_api() -> None:
    run = record("run-events")
    assert run["id"] == "run-39d0b17b5396"
    assert run["company"]["ticker"] == "NVDA"
    assert run["started_at"].startswith("2026-11-18")
    assert "Anthropic API" in run["engine_detail"] and "Anthropic API" in run["checker_detail"]


def test_the_page_says_where_the_sample_comes_from() -> None:
    soup = page("run-events")
    note = words(soup.select_one("#run-head [data-sample-note]"))
    for phrase in ("18 November 2026", "Anthropic API", "results/run-39d0b17b5396.json", "unedited"):
        assert phrase in note, phrase
    assert "Anthropic API" in words(soup.select_one("#form-note"))
    assert soup.select_one("#sample-tag:not([hidden])") is not None


def test_every_claim_and_verdict_of_the_live_run_is_shown() -> None:
    soup, run = page("run-events"), record("run-events")
    assert [li["data-claim-id"] for li in soup.select("#scorecard > li")] == [c["id"] for c in run["claims"]]
    assert [d["data-docket"] for d in soup.select("#claim-list details.claim")] == [c["id"] for c in run["claims"]]
    for claim in run["claims"]:
        pill = soup.select_one(f'#scorecard > li[data-claim-id="{claim["id"]}"] .pill.verdict')
        assert pill is not None and f"v-{claim['verdict']}" in pill["class"]


def test_the_caution_and_the_predated_mark_are_the_records() -> None:
    soup, run = page("run-events"), record("run-events")
    cautioned = [c for c in run["claims"] if c.get("caution")]
    assert cautioned, "the live run carries a caution on its first claim"
    for claim in cautioned:
        docket = soup.select_one(f'#claim-list details.claim[data-docket="{claim["id"]}"]')
        assert docket is not None
        assert words(docket.select_one(f'[data-claim-caution="{claim["id"]}"]')) == f"▲ Caution: {claim['caution']}"
        assert "Caution" in words(docket.select_one("summary .docket-meta"))
    marks = [(f["id"], m) for f in run["findings"] for m in f.get("predated_by") or []]
    assert marks
    for finding_id, mark in marks:
        shown = soup.select_one(f'#claim-list article[data-finding-id="{finding_id}"] [data-predated-by="{mark["event_id"]}"]')
        assert shown is not None and mark["label"] in words(shown)


def test_the_register_lists_every_8k_of_the_live_run() -> None:
    soup, run = page("run-events"), record("run-events")
    assert words(soup.select_one("#events-title")) == EVENTS_HEADING
    shown = [li["id"] for li in soup.select("#events-section li.event")]
    assert shown == [f"event-{e['id']}" for e in run["timeline"]]
    assert words(soup.select_one("[data-event-counts]")) == run["as_of"]["counts"]["line"]


def test_the_command_bar_carries_the_runs_status_engines_and_as_of_line() -> None:
    soup, run = page("run-events"), record("run-events")
    bar = soup.select_one("header .cmdbar #cmd-run")
    assert bar is not None and not bar.has_attr("hidden")
    assert words(soup.select_one("#cmd-status")) == f"▲ {run['status'].capitalize()}"
    assert soup.select_one("#cmd-status .glyph.g-limit") is not None, "a partial run carries the limit mark"
    assert run["engine_detail"] in words(soup.select_one("[data-cmd-engine]"))
    assert run["checker_detail"] in words(soup.select_one("[data-cmd-checker]"))
    assert run["as_of"]["line"] in words(soup.select_one("[data-cmd-as-of]"))


def test_the_command_bar_is_hidden_on_the_first_screen_views() -> None:
    for dump in ("dom-changes.html", "dom-breakdowns.html"):
        soup = BeautifulSoup((RESULTS / dump).read_text(encoding="utf-8"), "html.parser")
        assert soup.select_one("#cmd-run[hidden]") is not None, dump


# ---------------------------------------------------------------- the time line


def periodic(run: dict[str, Any]) -> list[dict[str, Any]]:
    """The filings the time line draws above its axis: dated SEC filings that are not 8-Ks."""
    return [
        s for s in run["sources"]
        if s["kind"] == "sec_filing" and s.get("published_date") and not str(s.get("form") or "").upper().startswith("8-K")
    ]


def quoted_sources(run: dict[str, Any]) -> set[str]:
    return {e["source_id"] for e in run.get("evidence") or []}


@every_run
def test_the_time_line_draws_every_periodic_filing_the_run_read(name: str) -> None:
    soup, run = page(name), record(name)
    marks = soup.select('#timeline svg[data-timeline] [data-tl="filing"]')
    assert sorted(m["data-source-id"] for m in marks) == sorted(s["id"] for s in periodic(run))
    quoted = quoted_sources(run)
    for mark in marks:
        expected = "true" if mark["data-source-id"] in quoted else "false"
        assert mark["data-quoted"] == expected, mark["data-source-id"]
        source = next(s for s in run["sources"] if s["id"] == mark["data-source-id"])
        assert mark.name == "a" and mark["href"] == source["url"]


@every_run
def test_the_time_line_draws_exactly_the_runs_8ks(name: str) -> None:
    soup, run = page(name), record(name)
    marks = soup.select('#timeline svg[data-timeline] [data-tl="8k"]')
    events = run.get("timeline") or []
    assert sorted(m["data-event-id"] for m in marks) == sorted(e["id"] for e in events)
    quoted_accessions = {s.get("accession") for s in run["sources"] if s["id"] in quoted_sources(run)}
    for mark in marks:
        event = next(e for e in events if e["id"] == mark["data-event-id"])
        kind = "substantive" if event["substantive"] else "routine"
        assert mark["data-kind"] == kind
        assert mark.select_one(f".tl-8k.is-{kind}") is not None, "a substantive 8-K and a routine one are drawn apart"
        assert mark["data-quoted"] == ("true" if event["accession"] in quoted_accessions else "false")
        assert mark.name == "a" and mark["href"] == event["url"]
        assert event["filed_label"] in mark.select_one("title").get_text()


@every_run
def test_the_time_line_marks_the_run_and_shades_the_unread_gap_only_with_an_as_of(name: str) -> None:
    soup, run = page(name), record(name)
    assert len(soup.select('#timeline [data-tl="run"]')) == 1
    gaps = soup.select('#timeline [data-tl="gap"]')
    if run.get("as_of"):
        assert len(gaps) == 1
        label = soup.select_one("#timeline .tl-gap-label")
        days = run["as_of"]["days_since_newest"]
        assert label is not None and words(label).startswith(f"{days} day")
    else:
        assert gaps == []


def test_the_live_run_quotes_two_8ks_and_the_time_line_marks_both() -> None:
    """The live run quotes the 8-Ks of 12 Nov and 2 Jul 2026 (sources s5 and s6); their marks say so."""
    run = record("run-events")
    cited = {s["accession"] for s in run["sources"] if s.get("form") == "8-K" and s["id"] in quoted_sources(run)}
    assert len(cited) == 2
    marks = page("run-events").select('#timeline [data-tl="8k"][data-quoted="true"]')
    assert {m["data-event-id"] for m in marks} == {e["id"] for e in run["timeline"] if e["accession"] in cited}


def test_the_time_line_has_a_text_alternative_for_every_mark() -> None:
    for mark in page("run-events").select("#timeline .tl-mark"):
        assert mark.get("aria-label"), mark
        assert mark.select_one("title") is not None
