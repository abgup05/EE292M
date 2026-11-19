"""Browser-level checks of the analysis, the headline figures and the Method tab.

`make uitest` renders four records and dumps each DOM: the two live samples (/?sample=run-live,
NVIDIA, and /?sample=run-costco, Costco: both argued by claude-opus-5-5 through the Anthropic
API on 19 Nov 2026 and copied unedited from the runs' records), /?sample=analysis-shapes
(docs/examples/analysis/run-hand-built-argument.json: scripted, hand-built answers that show
every shape, no model) and /?sample=computed (no model: the computed analysis only). It also
loads uitests/analysis.html, which uses the page as a reader would and records what it did.

These tests compare what the page drew with the JSON. What they hold the page to:

- every sentence of the argument in the record is on the page, once, in the record's order, with
  the audit's verdict on it; one the audit did not verify is marked and says why;
- every id a sentence cites is a chip, and a chip opens the thing it names (a finding, an
  analytic, a computed test, a corollary, the odds, an 8-K, a figure) in the inspector;
- who wrote the argument is said in the record's own words (the model, and the API or a cassette);
- every analytic shows the record's question, value, reading and note; a provider that gave
  nothing is named with its reason;
- the headline figures are `Run.analysis.headline`, and the Figures tab puts the figures the
  record ties to the selection first;
- the Method tab's counts are `run.coverage`'s and its times `run.timings`';
- a run opens on the analysis, and a run with no model says so in the record's words.

The page computes none of this: each check is the record's value against the page's text.
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
EXAMPLES = ROOT / "docs" / "examples" / "analysis"
HARNESS = ROOT / "uitests" / "analysis.html"

DUMPS = {
    "run-live": ("dom-run-live.html", "sample-run-live.json"),
    "run-costco": ("dom-run-costco.html", "sample-run-costco.json"),
    "analysis-shapes": ("dom-analysis-shapes.html", "sample-analysis-shapes.json"),
    "computed": ("dom-computed.html", "sample-computed.json"),
}
ARGUED = ["run-live", "run-costco", "analysis-shapes"]
each_sample = pytest.mark.parametrize("name", sorted(DUMPS))
each_argued = pytest.mark.parametrize("name", ARGUED)
PROVIDERS = ["facts", "outside_view", "market_view"]


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


@cache
def steps() -> dict[str, Tag]:
    dump = RESULTS / "dom-analysis.html"
    require_fresh(dump, WEB / "sample-run-live.json")
    if HARNESS.stat().st_mtime > dump.stat().st_mtime:
        pytest.fail("dom-analysis.html is older than uitests/analysis.html: run `make uitest`")
    soup = BeautifulSoup(dump.read_text(encoding="utf-8"), "html.parser")
    error = soup.select_one('li[data-step="error"]')
    if error is not None:
        pytest.fail(f"uitests/analysis.html stopped: {error.get_text()[:600]}")
    if soup.select_one('#done[data-done="true"]') is None:
        pytest.fail("uitests/analysis.html did not finish (more virtual time needed?)")
    return {li["data-step"]: li for li in soup.select("li[data-step]")}


def step(name: str) -> Tag:
    assert name in steps(), f"the analysis check recorded no step {name!r}"
    return steps()[name]


def words(node: Tag | None) -> str:
    assert node is not None
    return " ".join(node.get_text().split())


def scope(name: str, claim_id: str = "") -> Tag:
    node = page(name).select_one(f'#analysis > .an-scope[data-an-scope="{claim_id}"]')
    assert node is not None, f"{name}: no analysis drawn for {claim_id or 'the whole thesis'}"
    return node


def thesis_sentences(analysis: dict[str, Any]) -> list[dict[str, Any]]:
    """The whole thesis's sentences in the order the page sets them."""
    thesis = analysis.get("thesis") or {}
    out = [*thesis.get("bottom_line", []), *thesis.get("weakest_why", []), *thesis.get("strongest_for", []), *thesis.get("strongest_against", [])]
    for scenario in thesis.get("scenarios", []):
        out.extend(scenario.get("conditions", []))
    return out


def claim_sentences(claim: dict[str, Any]) -> list[dict[str, Any]]:
    argument = (claim.get("analysis") or {}).get("argument") or {}
    return [*argument.get("assessment", []), *argument.get("case_for", []), *argument.get("case_against", []), *argument.get("decides", []), *argument.get("would_change", [])]


def all_sentences(run: dict[str, Any]) -> list[tuple[str, dict[str, Any]]]:
    out = [("", s) for s in thesis_sentences(run["analysis"])]
    for claim in run["claims"]:
        out.extend((claim["id"], s) for s in claim_sentences(claim))
    return out


def analytics(run: dict[str, Any]) -> dict[str, dict[str, Any]]:
    return {item["id"]: item for item in run["analysis"]["analytics"]}


def ref_of(run: dict[str, Any], analytic_id: str) -> str:
    return f"A{[item['id'] for item in run['analysis']['analytics']].index(analytic_id) + 1}"


# ---------------------------------------------------------------- the samples are the records


def test_the_analysis_samples_are_copied_unedited() -> None:
    assert (WEB / "sample-analysis-shapes.json").read_bytes() == (EXAMPLES / "run-hand-built-argument.json").read_bytes(), "run `make sample-analysis`"
    for sample, run_id in (("sample-run-live.json", "run-a3c830947e19"), ("sample-run-costco.json", "run-6560ff7f364f")):
        original = RESULTS / f"{run_id}.json"
        assert json.loads((WEB / sample).read_text(encoding="utf-8"))["id"] == run_id
        if original.is_file():  # results/ is not committed
            assert (WEB / sample).read_bytes() == original.read_bytes()


def test_the_first_two_samples_offered_are_the_two_live_runs() -> None:
    soup = BeautifulSoup((WEB / "index.html").read_text(encoding="utf-8"), "html.parser")
    links = soup.select("#sample-nav li a")
    assert [a["href"] for a in links[:2]] == ["?sample=run-live", "?sample=run-costco"]
    for link in links[:2]:
        assert "Anthropic API" in words(link.find_parent("li"))


@pytest.mark.parametrize(("name", "phrases"), [
    ("run-live", ("live run of 19 November 2026", "run-a3c830947e19", "Anthropic API", "claude-opus-5-5", "wrote the argument", "copied unedited from results/run-a3c830947e19.json")),
    ("run-costco", ("live run of 19 November 2026", "run-6560ff7f364f", "Costco", "Anthropic API", "claude-opus-5-5", "copied unedited from results/run-6560ff7f364f.json")),
    ("analysis-shapes", ("docs/examples/analysis/run-hand-built-argument.json", "hand-built", "no model", "make sample-analysis")),
])
def test_a_sample_says_where_its_answers_came_from(name: str, phrases: tuple[str, ...]) -> None:
    note = words(page(name).select_one("#run-head [data-sample-note]"))
    for phrase in phrases:
        assert phrase in note, phrase
    run = record(name)
    if name != "analysis-shapes":
        assert run["analysis"]["argument_detail"].endswith("via the Anthropic API")
        assert run["started_at"].startswith("2026-11-19")
    else:
        assert "scripted" in run["analysis"]["argument_detail"]


# ---------------------------------------------------------------- every sentence, with the audit's word on it


@each_argued
def test_every_sentence_of_the_argument_is_on_the_page_once_in_order(name: str) -> None:
    run = record(name)
    expected = all_sentences(run)
    drawn = page(name).select("#analysis [data-an-sentence]")
    assert [words(node.select_one(".an-text")) for node in drawn] == [" ".join(s["text"].split()) for _, s in expected]
    assert len(drawn) == run["coverage"]["analysis_sentences_written"] - run["coverage"]["analysis_sentences_cut"]
    # Each in the analysis of what it is about: the whole thesis, or its claim.
    for node, (claim_id, _) in zip(drawn, expected, strict=True):
        assert node.find_parent(class_="an-scope")["data-an-scope"] == claim_id


@each_argued
def test_a_sentence_shows_the_audits_verdict_and_an_unverified_one_says_why(name: str) -> None:
    run = record(name)
    expected = all_sentences(run)
    drawn = page(name).select("#analysis [data-an-sentence]")
    unverified = 0
    for node, (_, sentence) in zip(drawn, expected, strict=True):
        assert node["data-verified"] == ("true" if sentence["verified"] else "false"), sentence["text"]
        mark = node.select_one("[data-unverified]")
        if sentence["verified"]:
            assert mark is None and "is-unverified" not in node["class"]
            continue
        unverified += 1
        assert "is-unverified" in node["class"] and mark is not None, "an unverified sentence is shown and marked, never hidden"
        assert mark.select_one(".g-limit") is not None
        for problem in sentence["problems"]:
            assert problem in words(mark), problem
    assert unverified == run["coverage"]["analysis_sentences_unverified"] > 0, "each argued sample has sentences the audit did not verify"


@each_argued
def test_a_sentence_that_restates_a_threshold_says_so_and_is_not_marked_as_a_failure(name: str) -> None:
    run = record(name)
    restating = 0
    for node, (_, sentence) in zip(page(name).select("#analysis [data-an-sentence]"), all_sentences(run), strict=True):
        marks = node.select(".an-threshold")
        listed = sentence.get("thresholds") or []
        assert [(m["data-threshold"], m["data-threshold-of"]) for m in marks] == [(t["raw"], t["of"]) for t in listed], sentence["text"]
        assert ("has-thresholds" in node["class"]) == bool(listed)
        for mark, item in zip(marks, listed, strict=True):
            assert words(mark) == f"restates a threshold: {item['raw']}"
            # In words, in the mark's title: the number, whose threshold it is, and that it was not checked as a fact.
            assert mark["title"].startswith(f"Restates a threshold: {item['raw']} (") and mark["title"].endswith("). Not checked as a fact.")
            assert mark.select_one(".g-limit") is None and "an-unverified" not in mark["class"], "restating a threshold is not a failure"
        if listed:
            restating += 1
            assert sentence["verified"] and node["data-verified"] == "true"
    assert restating == run["coverage"]["analysis_sentences_restating"] > 0, "each argued sample has a sentence that restates a threshold"


def test_the_inspector_says_what_the_audit_does_in_the_records_own_words() -> None:
    run = record("run-live")
    rule = " ".join(run["analysis"]["audit_rule"].split())
    for name in ("default", "sentence-unverified", "sentence-verified", "sentence-restating"):
        assert step(name)["data-inspect-rule"] == rule, name
    # The page writes no rule of its own: what it says beside the mark is the state, and nothing about what was checked.
    assert step("sentence-verified")["data-inspect-audit-text"].removeprefix("ƒ").strip() in ("Verified by code.", "Verified by code, with a threshold restated.")
    source = (WEB / "app.js").read_text(encoding="utf-8")
    assert "every number it writes is carried by something it cites" not in source and "Code checked every sentence" not in source
    for name in ARGUED:
        assert words(scope(name).select_one('[data-an-block="made"] [data-audit-rule]')) == " ".join(record(name)["analysis"]["audit_rule"].split())
    s = step("sentence-restating")
    sentence = next(x for _, x in all_sentences(run) if " ".join(x["text"].split()) == s["data-sentence-text"])
    assert sentence["thresholds"] and (s["data-sentence-verified"], s["data-inspect-audit"]) == ("true", "verified-restating")
    lines = s["data-inspect-thresholds"].split("|")
    assert len(lines) == len(sentence["thresholds"])
    for line, item in zip(lines, sentence["thresholds"], strict=True):
        kind, _, rest = item["of"].partition(":")
        whose = f"the test of {rest}" if kind == "test" else f"corollary {rest.replace(':', '.')}" if kind == "cor" else item["of"]
        assert line == f"Restates a threshold: {item['raw']} ({whose}). Not checked as a fact."
    assert s["data-marks-drawn"].split("|") == [f"restates a threshold: {t['raw']}" for t in sentence["thresholds"]]
    assert s["data-mark-title"] == lines[0]
    # A quiet mark, distinct from the one for a sentence the audit did not verify: no limit glyph, no wavy rule, another colour.
    assert (s["data-mark-has-limit-glyph"], s["data-mark-underline"]) == ("false", "none")
    assert s["data-unverified-color"] and s["data-mark-color"] != s["data-unverified-color"]


def test_a_replayed_argument_says_which_recorded_answers_it_used_whole() -> None:
    """Drawn by the page's own code from docs/examples/analysis/run-model-argument.json (uitests/analysis.html says how)."""
    run = json.loads((EXAMPLES / "run-model-argument.json").read_text(encoding="utf-8"))
    detail, proposer = run["analysis"]["argument_detail"], run["analysis"]["corollaries_by"]
    assert detail.startswith("replayed from cassette ") and "recorded answers used" in detail
    s = step("replayed")
    assert detail in s["data-by"] and s["data-by-clipped"] == "false", "the line that says who wrote it is whole and inside its pane"
    assert detail in s["data-made"] and proposer in s["data-made"]
    assert (s["data-page-sideways"], s["data-centre-sideways"]) == ("0", "0")
    assert detail in step("replayed-stage")["data-stage-text"]


@each_argued
def test_every_cited_id_is_a_chip_that_names_what_it_opens(name: str) -> None:
    run = record(name)
    findings = {f["id"] for f in [*run["findings"], *run["unsupported_findings"]]}
    metrics = {m["id"] for m in run["metrics"]}
    events = {e["id"] for e in run["timeline"]}
    known = analytics(run)
    corollaries = {c["id"] for claim in run["claims"] for c in claim["analysis"]["corollaries"]}
    odds = {claim["analysis"]["persistence"]["id"] for claim in run["claims"] if claim["analysis"].get("persistence")}
    tests = {f"test:{claim['id']}" for claim in run["claims"] if claim.get("computed")}
    kinds: set[str] = set()
    for node, (_, sentence) in zip(page(name).select("#analysis [data-an-sentence]"), all_sentences(run), strict=True):
        chips = node.select(".an-cites [data-cite]")
        assert [chip["data-cite"] for chip in chips] == sentence["cites"], sentence["text"]
        for chip in chips:
            cited = chip["data-cite"]
            if cited in findings:
                want, label = f"finding:{cited}", cited
            elif cited in known:
                # An analytic's chip: its reference in the ledger, then the record's word for its kind.
                want, label = f"analytic:{cited}", f"{ref_of(run, cited)} {known[cited]['kind'].replace('_', ' ')}"
            elif cited in tests:
                want, label = f"test:{cited.removeprefix('test:')}", f"test {cited.removeprefix('test:')}"
            elif cited in corollaries:
                want, label = f"corollary:{cited}", None
            elif cited in odds:
                want, label = f"odds:{cited}", None
            elif cited in events:
                want, label = f"event:{cited}", None
            elif cited in metrics:
                want, label = f"figure:{cited}", None
            else:
                assert chip.name == "span" and "chip-missing" in chip["class"], f"{cited} is in the record nowhere: its chip must say so"
                continue
            assert chip.name == "button" and chip["data-pick"] == want, cited
            if label is not None:
                assert words(chip) == label
            kinds.add(want.split(":")[0])
    assert {"analytic", "test"} <= kinds, kinds
    if name != "analysis-shapes":
        assert "finding" in kinds, "a model's argument cites the findings as well as the figures"


@each_argued
def test_who_wrote_the_argument_is_said_in_the_records_words(name: str) -> None:
    run = record(name)
    detail = run["analysis"]["argument_detail"]
    by = scope(name).select_one('[data-an-block="bottom"] .an-by')
    assert by["data-by"] == "model" and detail in words(by) and by.select_one(".g-model") is not None
    for claim in run["claims"]:
        if claim["analysis"].get("argument"):
            assert detail in words(scope(name, claim["id"]).select_one('[data-an-block="assessment"] .an-by'))
    made = words(scope(name).select_one('[data-an-block="made"]'))
    assert detail in made and run["analysis"]["corollaries_by"] in made
    assert f"{run['analysis']['argument_claims_answered']} of {run['analysis']['argument_claims_asked']} claims argued" in made
    audit = scope(name).select_one("[data-an-audit]")
    for field in ("analysis_sentences_verified", "analysis_sentences_written", "analysis_sentences_restating", "analysis_sentences_unverified", "analysis_sentences_cut"):
        assert words(audit.select_one(f'[data-coverage="{field}"]')) == f"{run['coverage'][field]:,}"


# ---------------------------------------------------------------- the argument's parts


@each_argued
def test_the_thesis_leads_with_the_bottom_line_then_what_it_leans_on(name: str) -> None:
    run = record(name)
    thesis = run["analysis"]["thesis"]
    blocks = [node["data-an-block"] for node in scope(name).select("[data-an-block]")]
    assert blocks[0] == "bottom", "the bottom line is the first thing in the analysis"
    assert [b for b in blocks if b in ("bottom", "leans", "for", "against", "scenarios")] == ["bottom", "leans", "for", "against", "scenarios"]
    rows = scope(name).select("[data-lean-claim]")
    assert [row["data-lean-claim"] for row in rows] == thesis["leans_on"]
    claims = {claim["id"]: claim for claim in run["claims"]}
    for row in rows:
        claim = claims[row["data-lean-claim"]]
        assert row.select_one(".pill.verdict")["data-verdict"] == claim["verdict"]
        assert row.select_one("[data-lean]")["data-lean"] == claim["analysis"]["argument"]["lean"]
        assert (row.select_one("[data-weakest]") is not None) == (claim["id"] == thesis["weakest_link"])
        # The claims are listed once, in the rail: here a claim is its id, and its words are the link's title.
        assert claim["text"] not in words(row) and row.select_one("a[data-goto-claim]")["title"] == claim["text"]
    assert [node["data-scenario"] for node in scope(name).select("[data-scenario]")] == [s["name"] for s in thesis["scenarios"]]
    assert [words(li) for li in scope(name).select('[data-an-block="flags"] li')] == [f"▲ {flag}" for flag in run["analysis"]["flags"]]


@each_argued
def test_a_claim_shows_its_lean_beside_its_verdict_and_what_would_change_it(name: str) -> None:
    run = record(name)
    flagged = 0
    for claim in run["claims"]:
        argument = claim["analysis"]["argument"]
        part = scope(name, claim["id"])
        line = part.select_one("[data-lean-line]")
        assert line.select_one(".pill.verdict")["data-verdict"] == claim["verdict"]
        assert line.select_one("[data-lean]")["data-lean"] == argument["lean"]
        flag = part.select_one("[data-lean-flag]")
        if argument["lean_flag"]:
            flagged += 1
            assert argument["lean_flag"] in words(flag) and flag.select_one(".g-limit") is not None
        else:
            assert flag is None
        rows = part.select("tr[data-would-change]")
        assert len(rows) == len(argument["would_change"])
        for row, item in zip(rows, argument["would_change"], strict=True):
            cells = row.select("td")
            assert words(cells[1]) == (item["measure"] or "—")
            if item["comparison"] not in ("", "none"):
                assert words(cells[2]).startswith(f"{item['comparison']} ")
                assert f"{item['threshold']:,}".rstrip("0").rstrip(".") in words(cells[2]).replace("$", "").replace("%", "")
            else:
                assert words(cells[2]) == "—"
            assert words(cells[3]) == (item["event_category"] or "—")
    if name == "analysis-shapes":
        assert flagged > 0, "the hand-built example has a lean that contradicts its verdict"


# ---------------------------------------------------------------- what code computed


@each_sample
def test_every_analytic_is_a_question_a_value_and_a_reading(name: str) -> None:
    run = record(name)
    known = analytics(run)
    company = [item["id"] for item in run["analysis"]["analytics"] if item["scope"] == "company"]
    assert [row["data-analytic"] for row in scope(name).select("li[data-analytic]")] == sorted(company, key=lambda i: (PROVIDERS.index(known[i]["provider"]), list(known).index(i)))
    for claim in run["claims"]:
        part = scope(name, claim["id"])
        rows = part.select("li[data-analytic]")
        wanted = [i for i in claim["analysis"]["analytic_ids"] if i in known]
        assert [row["data-analytic"] for row in rows] == sorted(wanted, key=lambda i: PROVIDERS.index(known[i]["provider"])), claim["id"]
        for row in rows:
            item = known[row["data-analytic"]]
            assert row.find_parent(attrs={"data-provider": True})["data-provider"] == item["provider"]
            assert words(row.select_one(".an-ref")) == ref_of(run, item["id"])
            assert words(row.select_one(".an-question")) == (item["question"] or item["label"])
            assert words(row.select_one("[data-analytic-value]")) == (item["display"] or "n/a")
            reading = row.select_one("[data-analytic-reading]")
            assert (words(reading) if reading else "") == " ".join(item["reading"].split())
            note = row.select_one("[data-analytic-note]")
            assert (words(note) if note else "") == " ".join(item["note"].split()), "the note (the reference pack's date, or why there is no value) is shown"
            assert row["data-available"] == ("true" if item["available"] else "false")
        for group in part.select("[data-provider]"):
            assert group.select_one('.an-by[data-by="code"] .g-rule') is not None, "each group says code computed it"


@pytest.mark.parametrize("name", ["run-live", "run-costco"])
def test_the_outside_and_market_views_are_on_the_live_runs_with_the_packs_date(name: str) -> None:
    run = record(name)
    by_provider = {p: [i for i in run["analysis"]["analytics"] if i["provider"] == p] for p in PROVIDERS}
    assert all(by_provider.values())
    drawn = {row["data-analytic"]: row for row in page(name).select("#analysis li[data-analytic]")}
    for item in [*by_provider["outside_view"], *by_provider["market_view"]]:
        if item["available"]:
            assert "reference pack" in item["note"] and "reference pack" in words(drawn[item["id"]].select_one("[data-analytic-note]")), item["id"]


@each_argued
def test_a_claims_corollaries_say_expected_result_reader_and_status(name: str) -> None:
    run = record(name)
    statuses: set[str] = set()
    for claim in run["claims"]:
        part = scope(name, claim["id"])
        rows = part.select("tr[data-corollary]")
        assert [row["data-corollary"] for row in rows] == [c["id"] for c in claim["analysis"]["corollaries"]]
        for row, cor in zip(rows, claim["analysis"]["corollaries"], strict=True):
            cells = row.select("td")
            assert cor["sentence"] in words(cells[0])
            assert words(cells[1]) == {"holds": "to hold", "fails": "to fail"}.get(cor["expect"], f"to {cor['expect']}")
            assert cor["result_label"] in words(cells[2]) and row["data-result"] == cor["result"]
            if cor.get("computed"):
                assert cells[2].select_one("[data-outcome]")["data-outcome"] == cor["computed"]["outcome"]
                if cor["computed"].get("left"):
                    assert cor["computed"]["left"]["display"] in words(cells[2])
            assert words(cells[3]) == cor["read_by"]
            assert cells[4]["data-status"] == cor["status"] and len(words(cells[4])) > len(cor["status"]), "the status is in words"
            statuses.add(cor["status"])
        flag = part.select_one("[data-corollary-flag]")
        assert (words(flag).removeprefix("▲ ") if flag else "") == claim["analysis"]["corollary_flag"]
        if rows:
            by = part.select_one('[data-an-block="corollaries"] .an-by')
            assert run["analysis"]["corollaries_by"] in words(by) and by.select_one(".g-model") is not None and by.select_one(".g-rule") is not None
    assert "agreed" in statuses


@each_sample
def test_the_odds_never_appear_without_their_caveat(name: str) -> None:
    run = record(name)
    with_odds = 0
    for claim in run["claims"]:
        odds = claim["analysis"].get("persistence")
        block = scope(name, claim["id"]).select_one("[data-odds-id]")
        if not odds:
            assert block is None
            continue
        if odds["applicable"]:
            with_odds += 1
            assert words(block.select_one("[data-odds]")) == odds["display"]
            assert odds["note"] in words(block) and odds["caveat"] in words(block.select_one("[data-odds-caveat]"))
        else:
            assert block.select_one("[data-odds]") is None and words(block.select_one("[data-odds-none]")) == (odds["note"] or "No odds were computed for this claim.")
    assert with_odds > 0


# ---------------------------------------------------------------- headline figures


@each_sample
def test_the_headline_figures_are_the_records(name: str) -> None:
    run = record(name)
    headline = run["analysis"]["headline"]
    assert headline, "every analysis sample names headline figures"
    for root in ("#tape", '#analysis > .an-scope[data-an-scope=""] [data-an-block="headline"]'):
        rows = page(name).select(f"{root} [data-headline]")
        assert [row["data-headline"] for row in rows] == [item["id"] for item in headline], root
        for row, item in zip(rows, headline, strict=True):
            assert words(row.select_one(".hl-open")) == item["label"]
            assert words(row.select_one("[data-headline-value]")) == item["display"]
            assert words(row.select_one(".hl-claims")).split() == item["claim_ids"]
            if item["source"] == "metric":
                assert row["data-pick"] == f"figure:{item['id']}" and item["period_label"] in words(row)
            elif item["source"] == "computed_test":
                assert row["data-pick"] == f"test:{item['id'].removeprefix('test:')}"
    assert page(name).select_one("#tape")["data-source"] == "headline"
    assert not page(name).select("#tape .tape-cell"), "the fixed tiles are replaced, not shown beside the headline"
    assert words(page(name).select_one("#tape-title")) == "Headline figures"


def newest_figures(run: dict[str, Any]) -> set[str]:
    """The figures the tab lists, as it did before the analysis: the newest quarter's and the newest fiscal year's, and the tagged ones."""
    metrics = run["metrics"]
    ends = {kind: max((m["period_end"] for m in metrics if m["period"] == kind and not m["id"].startswith("tagged:")), default="") for kind in ("quarter", "annual")}
    return {m["id"] for m in metrics if m["id"].startswith("tagged:") or any(end and m["period"] in (kind, "instant") and m["period_end"] == end for kind, end in ends.items())}


def test_the_figures_tab_puts_the_figures_tied_to_the_selection_first() -> None:
    run = record("run-live")
    listed = newest_figures(run)
    claim = next(c for c in run["claims"] if c["id"] == "c3")
    tied = {i for item in claim["analysis"]["relevant"] for i in item["metric_ids"]}
    s = step("figures-claim")
    assert set(s["data-tied-drawn"].split("|")) == tied and tied, "the figures the record ties to c3"
    assert int(s["data-untied-count"]) == len(listed - tied)
    assert (s["data-untied-open"], s["data-untied-rows-drawn"]) == ("false", "0"), "the rest is behind its control"
    assert "not tied to this claim" in s["data-untied-label"] and str(len(listed - tied)) in s["data-untied-label"]
    assert int(s["data-rows-in-dom"]) == len(listed | tied), "every figure the tab listed before is still on the page"
    # The whole thesis: the figures of every measure some claim is tied to; the rest under the record's own note.
    untied = set(run["analysis"]["untied_metric_ids"])
    s = step("figures-thesis")
    assert set(s["data-tied-drawn"].split("|")) == listed - untied and listed - untied
    assert int(s["data-untied-count"]) == len(listed & untied)
    assert run["analysis"]["untied_note"] in s["data-untied-label"]
    assert int(step("figures-thesis-open")["data-untied-rows-drawn"]) == len(listed & untied)


def test_a_claim_with_no_measure_shows_the_records_note() -> None:
    run = record("analysis-shapes")
    claim = next(c for c in run["claims"] if c["id"] == "c1")
    assert not claim["analysis"]["relevant"] and claim["analysis"]["relevance_note"], "the hand-built example's c1 is tied to no measure"
    s = step("figures-no-measure")
    assert (s["data-none-drawn"], s["data-none-note"], s["data-tied-count"]) == ("true", claim["analysis"]["relevance_note"], "0")
    assert int(s["data-untied-count"]) == len(newest_figures(run)), "every figure the tab lists is still there, behind the control"


# ---------------------------------------------------------------- the method


@each_sample
def test_the_method_tabs_counts_are_the_runs_own(name: str) -> None:
    run = record(name)
    method = page(name).select_one("#method")
    counts = method.select("[data-coverage]")
    assert len(counts) >= 12
    for node in counts:
        assert words(node) == f"{run['coverage'][node['data-coverage']]:,}", node["data-coverage"]
    assert words(method.select_one("[data-method-events]")) == str(len(run["timeline"]))
    for node in method.select("[data-method-analytics]"):
        assert words(node) == str(sum(1 for item in run["analysis"]["analytics"] if item["provider"] == node["data-method-analytics"]))
    assert [words(n) for n in method.select(".mth-phase-name")] == ["Read", "Test", "Find", "Analyse"]


@each_sample
def test_each_stage_is_marked_code_or_model_as_the_run_was_made(name: str) -> None:
    run = record(name)
    nodes = {node["data-stage"]: node for node in page(name).select("#method .mth-node")}
    model_engine = run["engine"] != "extractive"
    for stage in ("planning", "assessing", "summary"):
        assert nodes[stage]["data-by"] == ("model" if model_engine else "code"), stage
        assert run["engine_detail"] in words(nodes[stage])
    for stage in ("company", "filings", "events", "numbers", "retrieving", "analytics: facts", "corollaries: computed", "Audit of the sentences"):
        assert nodes[stage]["data-by"] == "code", stage
    assert nodes["verifying"]["data-by"] == ("both" if run["checker"] not in ("", "none") else "code")
    assert nodes["computed tests and claim readers"]["data-by"] == ("both" if "model" in run["claim_readers"] else "code")
    for node in nodes.values():
        marks = (node.select_one(".mth-by .g-rule") is not None, node.select_one(".mth-by .g-model") is not None)
        assert marks == {"code": (True, False), "model": (False, True), "both": (True, True)}[node["data-by"]]
    argued = run["analysis"]["argument_step"] != "not_asked"
    for stage in ("argument: the claims", "argument: the thesis", "corollaries: proposed by the model"):
        assert nodes[stage]["data-by"] == "model"
        assert nodes[stage]["data-state"] == ("ran" if argued else "skipped")
        if argued:
            assert run["analysis"]["argument_detail" if stage.startswith("argument") else "corollaries_by"] in words(nodes[stage])
        else:
            assert "not asked on this run" in words(nodes[stage])
    for provider in PROVIDERS:
        assert nodes[f"analytics: {provider}"]["data-state"] == ("ran" if provider in run["analysis"]["providers"] else "skipped")


@each_sample
def test_the_stage_times_are_the_runs_timings(name: str) -> None:
    run = record(name)
    timings = {t["stage"]: t for t in run.get("timings") or []}
    method = page(name).select_one("#method")
    if not timings:
        assert method.select_one("[data-no-timings]") is not None and not method.select("[data-method-seconds]")
        return
    rows = method.select("tr[data-timing]")
    assert [row["data-timing"] for row in rows] == list(timings)
    for row in rows:
        seconds = timings[row["data-timing"]]["seconds"]
        # Seconds as the record gives them, to the millisecond; a time under a millisecond is not written as "0 s".
        assert words(row.select("td")[1]) == ("<0.001 s" if 0 < seconds < 0.001 else f"{seconds:,.3f}".rstrip("0").rstrip(".") + " s")
    for node in method.select(".mth-node"):
        time = node.select_one("[data-method-seconds]")
        if node["data-stage"] in timings:
            assert float(time["data-method-seconds"]) == timings[node["data-stage"]]["seconds"]
            assert ("in the background" in words(time)) == timings[node["data-stage"]]["background"]
        else:
            assert time is None, "no time is shown that the record does not hold"


# ---------------------------------------------------------------- the page, used


def test_a_run_opens_on_the_analysis_with_the_bottom_line_in_view() -> None:
    run = record("run-live")
    s = step("default")
    assert (s["data-tab"], s["data-tab-selected"], s["data-selected"]) == ("analysis", "analysis", "")
    assert s["data-tab-names"].split("|") == ["Analysis", "Overview", "Evidence", "Over time", "Events", "Figures", "Method", "Limits"]
    assert (s["data-panels-shown"], s["data-scopes-shown"]) == ("panel-analysis", "thesis")
    assert s["data-first-block"] == "bottom"
    first = run["analysis"]["thesis"]["bottom_line"][0]
    assert s["data-lead-text"] == " ".join(first["text"].split())
    assert 0 < int(s["data-lead-top"]) < int(s["data-lead-bottom"]) <= 900, "the first sentence of the bottom line is inside the window"
    assert run["analysis"]["argument_detail"] in s["data-by"], "who wrote it is beside it"
    # The inspector already reads what that first sentence rests on.
    assert s["data-inspecting"] == f"sentence:{s['data-lead-sentence-key']}" and s["data-inspect-sentence"] == s["data-lead-text"]
    assert s["data-inspect-rests"].split("|") == first["cites"]
    assert (s["data-page-scroll"], s["data-page-sideways"], s["data-centre-sideways"]) == ("0", "0", "0")
    assert s["data-scopes-inert"].split() == [c["id"] for c in run["claims"]], "every other analysis is inert"


def test_selecting_a_sentence_reads_the_audit_and_what_it_rests_on() -> None:
    s = step("sentence-unverified")
    assert s["data-inspect-kind"] == "Sentence" and s["data-inspect-sentence"] == s["data-sentence-text"]
    assert s["data-inspect-audit"] == "unverified" and "Not verified" in s["data-inspect-audit-text"]
    assert s["data-reason-visible"] == "true" and s["data-reason-drawn"].startswith("▲ Not verified: ")
    assert s["data-reason-drawn"].removeprefix("▲ Not verified: ").split("; ")[0] in s["data-inspect-audit-text"]
    assert s["data-inspect-rests"] == s["data-sentence-cites"]
    s = step("sentence-verified")
    lead = record("run-live")["analysis"]["thesis"]["bottom_line"][0]
    assert s["data-inspect-audit"] == ("verified-restating" if lead.get("thresholds") else "verified") and s["data-inspect-rests"] == s["data-sentence-cites"]


def test_a_chip_of_every_kind_opens_the_thing_it_names() -> None:
    run = record("run-live")
    kinds = step("chips-done")["data-kinds"].split()
    assert {"analytic", "corollary", "event", "figure", "finding", "test"} <= set(kinds), kinds
    known = analytics(run)
    for kind in kinds:
        s = step(f"chip-{kind}")
        cited = s["data-cite"]
        assert (s["data-chip-picked"], s["data-chips-picked-alike"]) == ("true", "true"), "the chip being read is marked, wherever it appears"
        if kind == "analytic":
            item = known[cited]
            assert s["data-inspecting"] == f"analytic:{cited}"
            assert (s["data-inspect-label"], s["data-inspect-value"]) == (item["label"], item["display"])
            assert s["data-inspect-formula"] == " ".join(item["formula"].split()) and int(s["data-inspect-inputs"]) == len(item["inputs"])
            assert s["data-inspect-kind"] == f"Analytic {ref_of(run, cited)}"
        elif kind == "finding":
            finding = next(f for f in [*run["findings"], *run["unsupported_findings"]] if f["id"] == cited)
            assert s["data-inspecting"] == f"finding:{cited}" and s["data-inspect-evidence"].split() == finding["evidence_ids"]
        elif kind == "test":
            claim = next(c for c in run["claims"] if f"test:{c['id']}" == cited)
            assert s["data-inspecting"] == f"test:{claim['id']}"
            assert s["data-inspect-operands"].split("|") == [o["term"] for o in claim["computed"]["operands"]]
        elif kind == "corollary":
            cor = next(c for claim in run["claims"] for c in claim["analysis"]["corollaries"] if c["id"] == cited)
            assert s["data-inspecting"] == f"corollary:{cited}" and s["data-inspect-sentence"] == cor["sentence"]
            assert s["data-inspect-operands"].split("|") == [o["term"] for o in cor["computed"]["operands"]]
        elif kind == "event":
            assert s["data-inspecting"] == f"event:{cited}" and s["data-inspect-event"] == cited
        elif kind == "figure":
            metric = next(m for m in run["metrics"] if m["id"] == cited)
            assert (s["data-inspect-label"], s["data-inspect-value"]) == (metric["label"], metric["display"])
        elif kind == "odds":
            assert s["data-inspecting"] == f"odds:{cited}"


def test_an_analytic_is_traceable_to_its_formula_and_the_filings_behind_it() -> None:
    run = record("run-live")
    s = step("pick-analytic")
    item = analytics(run)[s["data-analytic"]]
    assert s["data-inspecting"] == f"analytic:{item['id']}" and s["data-inspect-formula"] == " ".join(item["formula"].split())
    accessions = [ref["accession"] for ref in item["inputs"] if ref["accession"]]
    links = s["data-inspect-filing-links"].split()
    assert len(links) == len(accessions) > 0
    for link, accession in zip(links, accessions, strict=True):
        assert link.startswith(f"https://www.sec.gov/Archives/edgar/data/{run['company']['cik']}/") and accession in link
    s = step("pick-corollary")
    cor = next(c for claim in run["claims"] for c in claim["analysis"]["corollaries"] if c["id"] == s["data-corollary"])
    assert s["data-inspecting"] == f"corollary:{cor['id']}" and s["data-inspect-sentence"] == cor["sentence"]
    s = step("pick-odds")
    odds = next(c["analysis"]["persistence"] for c in run["claims"] if c["analysis"]["persistence"]["id"] == s["data-odds"])
    assert (s["data-inspect-value"], s["data-caveat-drawn"]) == (odds["display"], "true") and odds["method"] in s["data-inspect-note"]


def test_a_claims_analysis_is_its_own_and_the_frame_holds() -> None:
    run = record("run-live")
    claim = next(c for c in run["claims"] if c["id"] == "c3")
    s = step("claim")
    assert (s["data-selected"], s["data-tab"], s["data-scopes-shown"]) == ("c3", "analysis", "c3")
    # The lean sits beside the verdict, in the head of the centre pane.
    assert (s["data-head-verdict"], s["data-head-lean"], s["data-head-lean-drawn"]) == (claim["verdict"], claim["analysis"]["argument"]["lean"], "true")
    assert s["data-analytics-drawn"].split("|") == sorted(claim["analysis"]["analytic_ids"], key=lambda i: PROVIDERS.index(analytics(run)[i]["provider"]))
    assert s["data-corollaries-drawn"].split("|") == [c["id"] for c in claim["analysis"]["corollaries"]]
    for name in ("default", "claim", "method", "overview", "figures-claim", "laptop-terminal"):
        s = step(name)
        assert (s["data-page-scroll"], s["data-page-sideways"], s["data-centre-sideways"]) == ("0", "0", "0"), name
    assert step("laptop-terminal")["data-scopes-shown"] == "c4"
    assert step("method")["data-panels-shown"] == "panel-method" and int(step("method")["data-nodes-drawn"]) == 18
    assert step("method")["data-inspecting"] == "stage:company" and step("method")["data-inspect-kind"] == "Stage", "a stage is read at the side"
    assert int(step("method")["data-times-drawn"]) == len([t for t in run["timings"] if t["stage"] not in ("analysis (all of it)", "finishing")])
    s = step("overview")
    assert (s["data-tape-source"], s["data-tape-title"]) == ("headline", "Headline figures")
    assert s["data-headline-drawn"].split("|") == [item["id"] for item in run["analysis"]["headline"]]


def test_on_a_phone_the_analysis_is_one_column_and_a_chip_opens_a_sheet() -> None:
    s = step("phone")
    assert (s["data-tab"], s["data-page-sideways"], s["data-inspector-shown"]) == ("analysis", "0", "false")
    s = step("phone-chip")
    assert (s["data-inspector-shown"], s["data-inspector-position"], s["data-close-drawn"]) == ("true", "fixed", "true")
    assert s["data-inspecting"].split(":", 1)[1] in (s["data-cite"], s["data-cite"].removeprefix("test:")) and s["data-page-sideways"] == "0"
    assert step("phone-escape")["data-inspector-shown"] == "false"
    assert step("phone-method")["data-page-sideways"] == "0"


def test_a_run_with_no_model_says_so_and_still_leads_with_the_analysis() -> None:
    run = record("computed")
    s = step("no-model")
    assert (s["data-tab"], s["data-state-step"], s["data-sentences"]) == ("analysis", "not_asked", "0")
    assert run["analysis"]["argument_note"] in s["data-state-text"] and "no model wrote an argument" in s["data-state-text"]
    assert "▲" not in s["data-state-text"], "no model asked is how the run was made, not a failure"
    assert s["data-blocks-shown"].split()[0] == "headline" and s["data-inspecting"] != "", "the pane beside it is not empty"
    s = step("no-model-claim")
    assert "no model argued this claim" in s["data-state-text"] and int(s["data-analytics-drawn"]) > 0
    made = words(scope("computed").select_one('[data-an-block="made"]'))
    assert "No model was asked." in made and run["analysis"]["corollaries_note"] in made
    assert scope("computed").select_one("[data-providers-not-asked]")["data-providers-not-asked"].split() == [p for p in PROVIDERS if p not in run["analysis"]["providers"]]


def test_a_record_without_an_analysis_has_no_analysis_tab_and_opens_on_the_overview() -> None:
    s = step("no-analysis")
    assert s["data-tab-names"].split("|") == ["Overview", "Evidence", "Over time", "Events", "Figures", "Method", "Limits"]
    assert (s["data-tab"], s["data-tape-source"], s["data-analysis-children"]) == ("overview", "metrics", "0")


def test_an_argument_answered_in_part_says_what_was_and_was_not_answered() -> None:
    """Made by hand from the live sample (uitests/analysis.html says how): no recorded run is partial."""
    s = step("made-partial")
    assert s["data-state-text"].startswith("▲ The argument was answered in part: 4 of 5 claims argued; the request for the whole thesis was asked and failed.")
    assert "the request for the whole thesis timed out" in s["data-state-text"]
    assert (s["data-argued"], s["data-thesis-step"]) == ("4 of 5", "asked and failed")
    # A provider that gave nothing is named with its reason on the thesis, on each claim and in how the analysis was made.
    assert s["data-failed-provider"] == "▲ Not available on this run: SEC's frames did not answer within 20 seconds."
    assert "The outside view" in s["data-made-failed"] and "did not answer within 20 seconds" in s["data-made-failed"]
    assert s["data-sentences"] == "0", "the thesis has no argument, and none is drawn"
    s = step("made-partial-claim")
    assert s["data-unargued"].startswith("▲ This claim has no argument.") and "The request for this claim timed out" in s["data-unargued"]
    assert s["data-failed-provider"] == "▲ Not available on this run: SEC's frames did not answer within 20 seconds."
    assert s["data-sentences"] == "0"
    s = step("made-partial-method")
    assert (s["data-outside-state"], s["data-thesis-state"], s["data-claims-state"]) == ("failed", "failed", "ran")
    assert "gave nothing: SEC's frames did not answer within 20 seconds." in s["data-outside-text"]
    assert s["data-times-drawn"] == "0" and "no stage times" in s["data-no-timings"]
    s = step("made-failed")
    assert s["data-state-step"] == "failed" and s["data-state-text"].startswith("▲ The argument was asked for and failed: 0 of 5 claims argued")
    assert s["data-sentences"] == "0"
