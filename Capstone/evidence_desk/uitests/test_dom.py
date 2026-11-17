"""Browser-level checks of the page, against the JSON record the page was given.

`make uitest` renders /?sample=synthetic and /?sample in headless Chromium and
writes the resulting DOM to results/dom-synthetic.html and results/dom-sample.html;
these tests read those files and the sample records in src/web. They check what a
reader sees: verdict marks, counts and their denominators, highlighted quotes,
reported figures, model-written badges, links and the legend, and in the synthetic
sample the reader's review (its "review" key) and what moved between two runs of
a saved thesis (its "comparison" key).
"""

from __future__ import annotations

import copy
import json
import re
import unicodedata
from functools import cache
from pathlib import Path
from typing import Any

import pytest
from bs4 import BeautifulSoup, Tag

ROOT = Path(__file__).resolve().parents[1]
WEB = ROOT / "src" / "web"
RESULTS = ROOT / "results"

PAGES = {
    "synthetic": ("sample-synthetic.json", "dom-synthetic.html"),
    "run": ("sample-run.json", "dom-sample.html"),
}

# Pinned here, not read from app.js, so swapping two glyphs in the page fails.
VERDICT_GLYPHS = {
    "supported": "✓",
    "challenged": "✕",
    "mixed": "±",
    "unjudged": "?",
    "not_addressed": "∅",
}
STANCE_GLYPHS = {"supports": "✓", "challenges": "✕", "context": "•"}
# The reader's own decision: glyphs no verdict or stance uses.
DECISION_GLYPHS = {"accepted": "▣", "rejected": "☒", "undecided": "☐"}
# A second model's reading of a finding's evidence: violet like ✎, but its own glyphs.
MEANING_GLYPHS = {"passed": "◎", "partly": "◐"}
MEANING_WORDS = {
    "passed": "Meaning: a second model agrees",
    "partly": "Meaning: a second model agrees only in part",
    "failed": "Meaning: a second model disagrees",
    "unchecked": "Meaning: not checked",
}
MEANING_COUNTS = ("findings_checked", "findings_partly", "findings_failed_meaning")
PLACEHOLDERS = ("undefined", "NaN", "[object Object]", "null")
MODEL_ONLY_ENGINE = "extractive"


@cache
def record(name: str) -> dict[str, Any]:
    """The sample file the page loaded: {"note", "meta", "run"}, and optionally "review", "comparison"."""
    return json.loads((WEB / PAGES[name][0]).read_text(encoding="utf-8"))


def require_fresh(dump: Path, sample: Path) -> None:
    """Fail unless ``dump`` exists and was rendered after the page and its sample last changed.

    A dump left over from an earlier `make uitest` would let these tests pass against a page
    that no longer exists (review 5, finding 11).
    """
    if not dump.is_file() or dump.stat().st_size == 0:
        pytest.fail(f"{dump} is missing or empty: run `make uitest`, which renders it first")
    sources = [WEB / "index.html", WEB / "app.js", WEB / "styles.css", sample]
    stale = [source.name for source in sources if source.stat().st_mtime > dump.stat().st_mtime]
    if stale:
        pytest.fail(
            f"{dump.name} is older than {', '.join(stale)}: run `make uitest`, which renders it again"
        )


@cache
def page(name: str) -> BeautifulSoup:
    """The DOM the headless browser dumped after the page rendered that record."""
    path = RESULTS / PAGES[name][1]
    require_fresh(path, WEB / PAGES[name][0])
    soup = BeautifulSoup(path.read_text(encoding="utf-8"), "html.parser")
    if soup.select_one("#run-view[hidden]") is not None or soup.select_one("#run-view") is None:
        pytest.fail(f"{path.name}: the page did not render a run (is the sample file served?)")
    return soup


def text(node: Tag) -> str:
    return node.get_text()


def classes(node: Tag) -> list[str]:
    return list(node.get("class") or [])


def outside_legend(nodes: list[Tag]) -> list[Tag]:
    return [node for node in nodes if node.find_parent(id="legend") is None]


def model_claim(claims: dict[str, dict[str, Any]], claim_id: str) -> bool:
    assessed_by = claims.get(claim_id, {}).get("assessed_by", "")
    return assessed_by not in ("", MODEL_ONLY_ENGINE)


def shown_findings(run: dict[str, Any]) -> list[dict[str, Any]]:
    """Verified findings listed under a claim, then every withheld finding."""
    listed = {fid for claim in run.get("claims", []) for fid in claim.get("finding_ids", [])}
    verified = [f for f in run.get("findings", []) if f.get("verified", True) and f["id"] in listed]
    return verified + list(run.get("unsupported_findings", []))


def support_of(finding: dict[str, Any]) -> str:
    """The meaning check's outcome; an older record without one reads as not checked."""
    return (finding.get("checks") or {}).get("support") or "unchecked"


def meaning_checked(run: dict[str, Any]) -> bool:
    return (run.get("checker") or "none") != "none"


both = pytest.mark.parametrize("name", list(PAGES))


@both
def test_scorecard_pills_carry_label_glyph_and_class(name: str) -> None:
    run, meta = record(name)["run"], record(name)["meta"]
    rows = page(name).select("#scorecard > li[data-claim-id]")
    assert [row["data-claim-id"] for row in rows] == [claim["id"] for claim in run["claims"]]
    summaries = page(name).select("#claim-list details.claim > summary")
    assert len(summaries) == len(run["claims"])
    for claim, row, summary in zip(run["claims"], rows, summaries, strict=True):
        verdict = claim["verdict"]
        for pill in (row.select_one(".pill.verdict"), summary.select_one(".pill.verdict")):
            assert pill is not None, f"{claim['id']}: no verdict pill"
            label = text(pill.select_one(".pill-label"))
            glyph = text(pill.select_one(".glyph"))
            verdict_classes = [c for c in classes(pill) if c.startswith("v-")]
            assert label == meta["verdict_labels"][verdict], f"{claim['id']}: label {label!r}"
            assert glyph == VERDICT_GLYPHS[verdict], f"{claim['id']}: {verdict} shows {glyph!r}"
            assert verdict_classes == [f"v-{verdict}"], f"{claim['id']}: classes {verdict_classes}"


def test_synthetic_sample_shows_every_verdict() -> None:
    pills = page("synthetic").select("#scorecard .pill.verdict")
    assert {pill["data-verdict"] for pill in pills} == set(VERDICT_GLYPHS)


def css_rules() -> list[tuple[list[str], str]]:
    css = (WEB / "styles.css").read_text(encoding="utf-8")
    css = re.sub(r"/\*.*?\*/", "", css, flags=re.S)
    rules = []
    for selectors, body in re.findall(r"([^{}]+)\{([^{}]*)\}", css):
        rules.append(([s.strip() for s in selectors.split(",")], body))
    return rules


def rule_body(selector: str) -> str:
    bodies = [body for selectors, body in css_rules() if selector in selectors]
    assert bodies, f"styles.css has no rule for {selector}"
    return " ".join(bodies)


def test_verdict_classes_use_their_own_colours() -> None:
    supported, challenged, mixed = (rule_body(f".v-{v}") for v in ("supported", "challenged", "mixed"))
    assert "--support" in supported and "--challenge" not in supported
    assert "--challenge" in challenged and "--support" not in challenged
    assert "--support" in mixed and "--challenge" in mixed
    assert "dashed" in rule_body(".v-unjudged")
    assert "dashed" not in rule_body(".v-not_addressed")
    root = rule_body(":root")
    colour = {key: value for key, value in re.findall(r"(--[\w-]+):\s*([^;]+);", root)}
    assert colour["--challenge"] != colour["--reject"], "challenged must not use the validation red"
    assert len({colour[k] for k in ("--challenge", "--reject", "--limit", "--model")}) == 4


@both
def test_every_count_equals_its_coverage_field(name: str) -> None:
    run = record(name)["run"]
    coverage = run["coverage"]
    soup = page(name)
    shown = soup.select("[data-coverage]")
    assert shown, "no coverage count is tagged"
    for node in shown:
        field = node["data-coverage"]
        assert field in coverage, f"the page shows {field}, which the record lacks"
        assert text(node) == f"{coverage[field]:,}", f"{field}: shows {text(node)!r}"

    banner = soup.select_one("#status-banner")
    in_banner = {node["data-coverage"] for node in banner.select("[data-coverage]")}
    required = {
        "sources_read", "sources_requested", "passages_indexed", "claims_with_evidence",
        "claims_total", "findings_verified", "findings_withheld", "excerpts_verified",
        "quotes_offered", "quotes_rejected",
    }
    if coverage.get("findings_proposed"):
        required.add("findings_proposed")
    if coverage.get("engine_fallbacks"):
        required.add("engine_fallbacks")
    assert required <= in_banner, f"banner lacks {sorted(required - in_banner)}"
    assert "claims with verified excerpts or figures" in text(banner)

    for claim, row in zip(run["claims"], soup.select("#scorecard > li[data-claim-id]"), strict=True):
        considered = row.select_one('[data-claim-field="passages_considered"]')
        denominator = row.select_one('[data-coverage="passages_indexed"]')
        assert considered is not None and denominator is not None, f"{claim['id']}: no denominator"
        assert text(considered) == f"{claim['passages_considered']:,}"
        assert " of " in text(row.select_one(".score-counts"))


@both
def test_every_excerpt_is_highlighted(name: str) -> None:
    marks = {text(mark) for mark in page(name).select("blockquote.excerpt mark")}
    for item in record(name)["run"]["evidence"]:
        assert item["excerpt"] in marks, f"{item['id']} is not shown inside a <mark>"


def newest_ids(metrics: list[dict[str, Any]]) -> set[str]:
    ids = set()
    for kind in ("quarter", "annual"):
        ends = [m["period_end"] for m in metrics if m["period"] == kind]
        if not ends:
            continue
        end = max(ends)
        ids |= {m["id"] for m in metrics if m["period"] in (kind, "instant") and m["period_end"] == end}
    return ids


@both
def test_every_figure_shows_exactly_its_display(name: str) -> None:
    run = record(name)["run"]
    metrics = {m["id"]: m for m in run.get("metrics", [])}
    soup = page(name)
    rows = soup.select("#figures [data-metric-id]")
    assert {row["data-metric-id"] for row in rows} == newest_ids(list(metrics.values()))
    for row in rows:
        metric = metrics[row["data-metric-id"]]
        assert text(row.select_one("summary .fig-value")) == metric["display"]
        assert text(row.select_one("summary .fig-label")).startswith(metric["label"])
    for node in soup.select("[data-cited-metric]"):
        assert text(node.select_one(".fig-value")) == metrics[node["data-cited-metric"]]["display"]
    series = {s["key"]: s for s in run.get("series", []) if s["period"] == "quarter"}
    for cell in soup.select("#figures td[data-series]"):
        points = {p["period_end"]: p for p in series[cell["data-series"]]["points"]}
        assert text(cell) == points[cell["data-period-end"]]["display"]


def test_synthetic_cites_figures_and_draws_charts() -> None:
    soup = page("synthetic")
    assert soup.select("[data-cited-metric]"), "no finding shows its cited figures"
    assert len(soup.select("#figures svg.chart")) == 3
    for svg in soup.select("#figures svg.chart"):
        assert svg.select_one("title") is not None
    assert soup.select("#figures .gap-label"), "a missing point must be drawn as a labelled gap"


@both
def test_model_badges_sit_exactly_on_model_written_fields(name: str) -> None:
    run = record(name)["run"]
    claims = {claim["id"]: claim for claim in run["claims"]}
    expected = set()
    if (run.get("brief") or {}).get("summary_origin") == "model":
        expected.add("summary")
    for claim in claims.values():
        if model_claim(claims, claim["id"]) and claim.get("rationale"):
            expected.add(f"claim:{claim['id']}:commentary")
    for finding in shown_findings(run):
        if model_claim(claims, finding["claim_id"]):
            expected.add(f"finding:{finding['id']}:statement")
            if finding.get("rationale"):
                expected.add(f"finding:{finding['id']}:reason")

    soup = page(name)
    badged = set()
    for badge in outside_legend(soup.select(".badge-model")):
        owner = badge.find_parent(attrs={"data-mw": True})
        assert owner is not None, "a model badge outside any model-writable field"
        badged.add(owner["data-mw"])
    assert badged == expected
    violet = {node["data-mw"] for node in soup.select("[data-mw]") if "is-model" in classes(node)}
    assert violet == expected


def test_real_sample_links_open_sec_filings() -> None:
    run = record("run")["run"]
    # Every evidence link, whatever its words say it opens (see test_each_evidence_link_says_what_it_opens).
    links = page("run").select("figure.evidence a.ext")
    assert len(links) == len(run["evidence"])
    for link in links:
        assert link["href"].startswith("https://www.sec.gov/"), link["href"]


@both
def test_no_placeholder_text(name: str) -> None:
    soup = page(name)
    for node in soup.find_all(string=True):
        if node.parent and node.parent.name in ("script", "style"):
            continue
        for bad in PLACEHOLDERS:
            assert bad not in node, f"text {node.strip()[:80]!r} contains {bad!r}"
    for tag in soup.find_all(attrs={"title": True}):
        for bad in PLACEHOLDERS:
            assert bad not in tag["title"], f"title {tag['title'][:80]!r} contains {bad!r}"


@both
def test_legend_is_present(name: str) -> None:
    legend = page(name).select_one("#legend")
    assert legend is not None
    words = text(legend)
    for glyph in ("✓", "✕", "±", "?", "∅", "•", "▲", "✎", "!"):
        assert glyph in words, f"legend lacks {glyph}"
    assert "limits this record" in words
    assert "not checked for meaning" in words
    assert "refused your input" in words


@both
def test_limit_and_model_glyphs_keep_one_meaning(name: str) -> None:
    for node in page(name).find_all(string=True):
        for glyph, owner in (("▲", "g-limit"), ("✎", "g-model"), ("◎", "g-meaning"), ("◐", "g-meaning")):
            if glyph in node:
                assert owner in classes(node.parent), f"{glyph} outside .{owner}: {node.parent}"


@both
def test_engine_and_errors_are_shown(name: str) -> None:
    run = record(name)["run"]
    soup = page(name)
    assert text(soup.select_one("#run-head .engine-used")) == run["engine"]
    if run.get("engine_detail"):
        assert run["engine_detail"] in text(soup.select_one("#run-head .engine-detail"))
    for claim, row in zip(run["claims"], soup.select("#scorecard > li"), strict=True):
        if claim.get("assessed_by"):
            assert claim["assessed_by"] in text(row.select_one(".assessed"))
    errors = run["errors"]
    shown = [li for li in soup.select("#errors > li") if "muted" not in classes(li)]
    assert [text(li).strip("▲ ") for li in shown] == errors[:3]
    disclosure = soup.select_one("#errors-all")
    if len(errors) > 3:
        assert disclosure is not None and not disclosure.has_attr("open")
        assert text(disclosure.select_one("summary")) == f"All {len(errors)} errors"
        assert len(disclosure.select("li")) == len(errors)
    else:
        assert disclosure is None


CHECK_WORDS = {
    ("quotes", "passed"): "Quote: found in the filing",
    ("quotes", "none"): "No quote cited",
    ("numbers", "passed"): "Numbers: all matched",
    ("numbers", "none"): "No number to check",
    ("numbers", "failed"): "A number did not match",
    ("support", "unchecked"): "Meaning: not checked",
    ("support", "passed"): "Meaning: a second model agrees",
    ("support", "partly"): "Meaning: a second model agrees only in part",
    ("support", "failed"): "Meaning: a second model disagrees",
}


@both
def test_findings_show_their_checks_and_withheld_reasons(name: str) -> None:
    run = record(name)["run"]
    soup = page(name)
    for finding in shown_findings(run):
        article = soup.select_one(f'article[data-finding-id="{finding["id"]}"]')
        assert article is not None, f"{finding['id']} is not rendered"
        words = text(article)
        for field in ("quotes", "numbers", "support"):
            value = (finding.get("checks") or {}).get(field)
            if value is not None:
                assert CHECK_WORDS[(field, value)] in words, f"{finding['id']}: {field}={value}"
        if not finding.get("verified", True):
            assert article.find_parent(id="withheld") is not None
            assert (finding.get("withheld_reason") or "no quote was found") in words


def test_samples_validate_against_the_run_model() -> None:
    from app.core.models import Review, Run, RunComparison, Verdict

    for name in PAGES:
        Run.model_validate(record(name)["run"])
    synthetic = record("synthetic")
    review = Review.model_validate(synthetic["review"])
    comparison = RunComparison.model_validate(synthetic["comparison"])
    assert review.run_id == synthetic["run"]["id"] == comparison.later_run_id
    assert synthetic["run"]["thesis_id"] == comparison.thesis_id
    assert {d.value.value for d in review.decisions} == {"accepted", "rejected"}
    assert any(c.undecided for c in review.claims), "the sample needs an undecided finding"
    assert any(c.reviewed_verdict and c.reviewed_verdict != c.engine_verdict for c in review.claims)
    assert any(c.reviewed_verdict is None for c in review.claims)
    assert any(d.note for d in review.decisions) and any(not d.note for d in review.decisions)
    changes = comparison.claims
    assert sum(c.moved for c in changes) == comparison.verdicts_moved >= 2
    assert any(not c.moved and c.before is not None for c in changes)
    assert any(c.before is None for c in changes), "a claim present in the later run only"
    assert comparison.sources_added and comparison.note
    meta = synthetic["meta"]
    assert set(meta["decision_labels"]) == set(DECISION_GLYPHS) and meta["review_note"]
    run = record("synthetic")["run"]
    claims = run["claims"]
    findings = run["findings"]
    withheld = run["unsupported_findings"]
    assert {c["verdict"] for c in claims} == {v.value for v in Verdict}
    assert {f["stance"] for f in findings + withheld} == {"supports", "challenges", "context"}
    assert {c["assessed_by"] for c in claims} >= {"claude", "extractive"}
    assert run["brief"]["summary_origin"] == "model"
    assert any(len(f["evidence_ids"]) >= 2 for f in findings)
    assert any(not f["evidence_ids"] and f["metric_ids"] for f in findings)
    assert any(f["checks"]["numbers"] == "passed" for f in findings)
    assert any(f["checks"]["numbers"] == "failed" and f["withheld_reason"] for f in withheld)
    assert any(not f["evidence_ids"] and f["withheld_reason"] for f in withheld)
    assert {s["kind"] for s in run["sources"]} >= {"sec_xbrl", "sec_filing"}
    assert any(s["extraction_status"] == "failed" for s in run["sources"])
    metrics = run["metrics"]
    assert len(metrics) >= 12 and {m["period"] for m in metrics} >= {"quarter", "annual"}
    assert any(m["formula"] and m["inputs"] for m in metrics)
    assert len(run["series"]) >= 3
    assert any(p["value"] is None for s in run["series"] for p in s["points"])
    assert run["coverage"]["engine_fallbacks"] > 0
    assert len(run["errors"]) > 3
    # The meaning check: every outcome appears, each judged one carries its reason, and the
    # three coverage counts agree with the findings.
    supports = [support_of(f) for f in findings + withheld]
    assert set(supports) == {"passed", "partly", "failed", "unchecked"}
    assert supports.count("partly") == 1 and supports.count("failed") == 1
    assert all(f["checks"]["support_detail"] for f in findings + withheld if support_of(f) != "unchecked")
    assert all(support_of(f) != "failed" for f in findings), "a finding that failed the meaning check is withheld"
    assert all(f["withheld_reason"].startswith("a second model judged") for f in withheld if support_of(f) == "failed")
    assert run["checker"] not in ("", "none") and run["checker_detail"] and meta["checker"]["name"]
    coverage = run["coverage"]
    assert coverage["findings_checked"] == sum(s != "unchecked" for s in supports)
    assert coverage["findings_partly"] == supports.count("partly")
    assert coverage["findings_failed_meaning"] == supports.count("failed")


# ---------------------------------------------------------------- review and what moved


def review_of(name: str) -> dict[str, Any]:
    return record(name)["review"]


def test_scorecard_shows_the_verdict_after_review() -> None:
    meta, review = record("synthetic")["meta"], review_of("synthetic")
    by_claim = {entry["claim_id"]: entry for entry in review["claims"]}
    rows = page("synthetic").select("#scorecard > li[data-claim-id]")
    assert [row["data-claim-id"] for row in rows] == list(by_claim)
    for row in rows:
        entry = by_claim[row["data-claim-id"]]
        engine, reviewed = row.select_one(".slot-engine"), row.select_one(".slot-reviewed")
        assert engine is not None and text(engine.select_one(".slot-label")) == "Engine"
        assert reviewed is not None, f"{entry['claim_id']}: no reviewed verdict"
        assert text(reviewed.select_one(".slot-label")) == "After your review"
        verdict = entry["reviewed_verdict"]
        undecided = reviewed.select_one('[data-review-field="undecided"]')
        if verdict is None:
            assert reviewed.select_one(".pill.verdict") is None
            pending = reviewed.select_one(".pill.review-pending")
            assert pending is not None and text(pending) == "not reviewed yet", entry["claim_id"]
            continue
        pill = reviewed.select_one(".pill.verdict")
        assert pill is not None, f"{entry['claim_id']}: no reviewed pill"
        assert text(pill.select_one(".pill-label")) == meta["verdict_labels"][verdict]
        assert text(pill.select_one(".glyph")) == VERDICT_GLYPHS[verdict], entry["claim_id"]
        assert [c for c in classes(pill) if c.startswith("v-")] == [f"v-{verdict}"]
        for field in ("accepted", "rejected"):
            shown = reviewed.select_one(f'[data-review-field="{field}"]')
            assert shown is not None and text(shown) == f"{entry[field]:,}", f"{entry['claim_id']}: {field}"
        if entry["undecided"]:
            assert undecided is not None and text(undecided) == f"{entry['undecided']:,}"
            assert "undecided" in classes(undecided.parent), "n undecided must be in the provisional style"
        else:
            assert undecided is None, f"{entry['claim_id']}: shows undecided findings it does not have"
    assert "dashed" in rule_body(".undecided") and "dashed" in rule_body(".pill.review-pending")


def test_review_line_shows_decided_of_total() -> None:
    meta, review = record("synthetic")["meta"], review_of("synthetic")
    line = page("synthetic").select_one("#review-line")
    assert line is not None and not line.has_attr("hidden")
    decided = line.select_one('[data-review-field="decided"]')
    total = line.select_one('[data-review-field="findings_total"]')
    assert decided is not None and text(decided) == f"{review['decided']:,}"
    assert total is not None and text(total) == f"{review['findings_total']:,}"
    words = " ".join(text(line).split())
    assert f"You have decided {review['decided']:,} of {review['findings_total']:,} findings" in words
    assert meta["review_note"] in words
    assert "sample: decisions are not saved" in words
    # The sample review is incomplete, and the sample never links to a brief.
    assert not review["complete"] and line.select_one('a[href*="reviewed=true"]') is None


def test_each_finding_shows_the_decision_from_the_review() -> None:
    synthetic = record("synthetic")
    meta, run = synthetic["meta"], synthetic["run"]
    decisions = {d["finding_id"]: d for d in review_of("synthetic")["decisions"]}
    soup = page("synthetic")
    listed = {fid for claim in run["claims"] for fid in claim["finding_ids"]}
    verified = [f for f in run["findings"] if f.get("verified", True) and f["id"] in listed]
    assert verified
    for finding in verified:
        fid = finding["id"]
        article = soup.select_one(f'#claim-list article[data-finding-id="{fid}"]')
        slot = article.select_one(".review-slot") if article else None
        assert slot is not None and not slot.has_attr("hidden"), f"{finding['id']}: no review controls"
        decision = decisions.get(finding["id"])
        value = decision["value"] if decision else "undecided"
        mark = slot.select_one(".decision-mark")
        assert mark is not None and mark["data-decision"] == value, finding["id"]
        assert text(mark.select_one(".decision-label")) == meta["decision_labels"][value], finding["id"]
        assert text(mark.select_one(".glyph")) == DECISION_GLYPHS[value], finding["id"]
        note = slot.select_one("input.decision-note")
        assert note is not None and note.get("value", "") == (decision["note"] if decision else ""), finding["id"]
        for button in slot.select("button.decide"):
            assert button["aria-pressed"] == ("true" if button["data-value"] == value else "false")
        for control in slot.select("button, input"):
            assert control.has_attr("disabled"), f"{finding['id']}: a control is live in sample mode"
        assert "sample: decisions are not saved" in text(slot)
    for article in soup.select("#withheld article"):
        assert article.select_one(".review-slot") is None, "a withheld finding has review controls"


def test_decision_marks_are_their_own() -> None:
    soup = page("synthetic")
    decision = set(DECISION_GLYPHS.values())
    assert not decision & (set(VERDICT_GLYPHS.values()) | set(STANCE_GLYPHS.values()))
    marks = soup.select(".decision-mark")
    assert {mark["data-decision"] for mark in outside_legend(marks)} == set(DECISION_GLYPHS)
    for mark in marks:
        assert not {"pill", "verdict", "stance"} & set(classes(mark)), classes(mark)
        assert text(mark.select_one(".glyph")) in decision
    for pill in soup.select(".pill"):
        glyph = pill.select_one(".glyph")
        assert glyph is None or text(glyph) not in decision, "a verdict or stance shows a decision glyph"
    for node in soup.find_all(string=True):
        if any(glyph in node for glyph in decision):
            assert node.find_parent(class_="decision-mark") is not None, f"decision glyph outside a mark: {node.parent}"
    body = rule_body(".decision-mark")
    assert "--ink" in body
    for colour in ("--support", "--challenge", "--reject", "--limit", "--model", "--accent"):
        assert colour not in body, f".decision-mark uses {colour}"
    assert "dashed" in rule_body(".decision-mark.d-undecided")


def test_what_moved_shows_each_claim() -> None:
    synthetic = record("synthetic")
    meta, run, comparison = synthetic["meta"], synthetic["run"], synthetic["comparison"]
    soup = page("synthetic")
    section = soup.select_one("#changes-section")
    assert section is not None and not section.has_attr("hidden")
    words = " ".join(text(section).split())
    assert comparison["note"] in words
    assert words.index(comparison["note"]) < words.index("Earlier run"), "the note comes first"
    for field in ("verdicts_moved", "claims_total"):
        assert text(section.select_one(f'[data-cmp="{field}"]')) == f"{comparison[field]:,}"
    rows = section.select("tbody tr[data-change]")
    assert len(rows) == len(comparison["claims"])
    for change, row in zip(comparison["claims"], rows, strict=True):
        assert text(row.select_one(".cmp-claim")) == change["claim"]
        for side in ("before", "after"):
            cell = row.select_one(f".cmp-{side}")
            verdict = change[side]
            main = [p for p in cell.select(".pill.verdict") if p.find_parent(class_="cmp-reviewed") is None]
            if verdict is None:
                assert not main and "not in the earlier run" in text(cell)
            else:
                assert len(main) == 1, f"{change['claim']}: {side}"
                assert text(main[0].select_one(".pill-label")) == meta["verdict_labels"][verdict]
                assert text(main[0].select_one(".glyph")) == VERDICT_GLYPHS[verdict]
            reviewed = change[f"reviewed_{side}"]
            shown = cell.select_one(".cmp-reviewed")
            assert (shown["data-reviewed-verdict"] if shown else None) == reviewed
        expected = "new in the later run" if change["before"] is None else "moved" if change["moved"] else "unchanged"
        assert text(row.select_one(".move-word")) == expected, change["claim"]
        for field in ("excerpts_added", "excerpts_dropped"):
            assert text(row.select_one(f'[data-cmp-field="{field}"]')) == f"{change[field]:,}"
        assert "added" in text(row.select_one(".cmp-excerpts")) and "dropped" in text(row.select_one(".cmp-excerpts"))
    added = text(section.select_one(".changes-filings.added"))
    dropped = text(section.select_one(".changes-filings.dropped"))
    for title in comparison["sources_added"]:
        assert title in added
    for title in comparison["sources_dropped"]:
        assert title in dropped
    belongs = soup.select_one("#run-head .run-thesis")
    assert belongs is not None and run["thesis_id"] in text(belongs)
    assert belongs.select_one('a[href="#changes-section"]') is not None


def test_real_sample_hides_review_it_does_not_have() -> None:
    assert "review" not in record("run") and "comparison" not in record("run")
    soup = page("run")
    assert soup.select_one("#review-line").has_attr("hidden")
    assert soup.select_one("#changes-section").has_attr("hidden")
    assert not soup.select("#scorecard .has-review, #scorecard .slot-reviewed")
    assert all(slot.has_attr("hidden") and not slot.contents for slot in soup.select(".review-slot"))


@both
def test_legend_includes_the_decision_marks(name: str) -> None:
    legend = page(name).select_one("#legend")
    shown = {text(mark.select_one(".glyph")) for mark in legend.select(".decision-mark")}
    assert shown == set(DECISION_GLYPHS.values())
    assert "Your decision" in text(legend)


# ---------------------------------------------------------------- the meaning check


def disclosures(node: Tag) -> list[Tag]:
    """The <details> around a node inside its finding (a claim's own disclosure is not one)."""
    return [d for d in node.find_parents("details") if "claim" not in classes(d)]


@both
def test_each_finding_shows_its_meaning_check(name: str) -> None:
    run = record(name)["run"]
    soup = page(name)
    for finding in shown_findings(run):
        if not finding.get("checks"):
            continue
        fid, support = finding["id"], support_of(finding)
        article = soup.select_one(f'article[data-finding-id="{fid}"]')
        item = article.select_one(".checks li[data-support]")
        assert item is not None, f"{fid}: no meaning line"
        assert item["data-support"] == support, f"{fid}: shows {item['data-support']}, the record says {support}"
        assert text(item.select_one(".meaning-words")) == MEANING_WORDS[support], fid
        glyph = item.select_one(".g-meaning")
        if support in MEANING_GLYPHS:
            assert glyph is not None and text(glyph) == MEANING_GLYPHS[support], f"{fid}: {support} mark"
        else:
            assert glyph is None, f"{fid}: a {support} finding carries the meaning mark"
        detail = finding["checks"].get("support_detail") or ""
        shown = article.select_one("[data-support-detail]")
        if support == "passed" and detail:
            assert shown is not None and text(shown).endswith(detail), f"{fid}: reason missing"
            closed = disclosures(shown)
            assert closed and not closed[0].has_attr("open"), f"{fid}: a passed reason sits in a closed disclosure"
        elif support == "partly":
            assert shown is not None and text(shown).endswith(detail), f"{fid}: the partly reason is not shown"
            assert not disclosures(shown), f"{fid}: the partly reason is hidden in a disclosure"
        else:
            assert shown is None, f"{fid}: a {support} finding shows a meaning reason"


@both
def test_meaning_withheld_findings_have_their_own_heading(name: str) -> None:
    withheld = record(name)["run"].get("unsupported_findings", [])
    by_meaning = {f["id"]: f for f in withheld if support_of(f) == "failed"}
    by_checks = {f["id"] for f in withheld} - set(by_meaning)
    soup = page(name)
    group = soup.select_one('#withheld [data-withheld-group="meaning"]')
    if not by_meaning:
        assert group is None and soup.select_one("#withheld .withheld-subtitle") is None
        return
    assert group is not None, "no group for findings withheld by the meaning check"
    assert text(group.select_one(".withheld-subtitle")).strip() == "Withheld by the meaning check"
    assert {a["data-finding-id"] for a in group.select("article[data-finding-id]")} == set(by_meaning)
    for fid, finding in by_meaning.items():
        reason = group.select_one(f'article[data-finding-id="{fid}"] [data-withheld-reason]')
        assert reason is not None and text(reason) == finding["withheld_reason"], f"{fid}: the checker's reason"
    if by_checks:
        other = soup.select_one('#withheld [data-withheld-group="checks"]')
        assert other is not None
        assert text(other.select_one(".withheld-subtitle")).strip() == "Withheld for a quote or a number"
        assert {a["data-finding-id"] for a in other.select("article[data-finding-id]")} == by_checks


@both
def test_header_names_the_checker(name: str) -> None:
    sample = record(name)
    run, meta = sample["run"], sample["meta"]
    soup = page(name)
    line = soup.select_one("#run-head .run-checker")
    assert line is not None, "the run header does not say who checked meaning"
    # A replayed checker's note shows a short first line (a <summary>); the whole note follows it.
    line = copy.copy(line)
    for short in line.select(".prov-first"):
        short.decompose()
    words = " ".join(text(line).split())
    if meaning_checked(run):
        assert words == f"Meaning checked by: {run.get('checker_detail') or run['checker']}"
    else:
        assert words == "Meaning not checked"
    configured = meta.get("checker")
    if configured:
        assert (configured.get("detail") or configured["name"]) in text(soup.select_one("#engine-line"))


@both
def test_banner_counts_the_meaning_check(name: str) -> None:
    coverage = record(name)["run"]["coverage"]
    banner = page(name).select_one("#status-banner")
    nodes = {field: banner.select_one(f'[data-coverage="{field}"]') for field in MEANING_COUNTS}
    if not coverage.get("findings_checked"):
        assert not any(nodes.values()), "the banner counts a meaning check the record lacks"
        return
    for field, node in nodes.items():
        assert node is not None and text(node) == f"{coverage[field]:,}", field
    checked, partly, failed = (coverage[field] for field in MEANING_COUNTS)
    words = " ".join(text(nodes["findings_checked"].parent).split())
    noun = "finding" if checked == 1 else "findings"
    assert words == f"{checked:,} {noun} checked for meaning, {partly:,} agreed only in part, {failed:,} withheld"


@both
def test_note_under_the_verdicts_follows_the_record(name: str) -> None:
    run = record(name)["run"]
    words = " ".join(text(page(name).select_one("#distinction")).split())
    if meaning_checked(run):
        assert "a second model, which was not shown the first one's reasoning, read each finding's evidence" in words
        assert "still a model's reading" in words and "accept or reject" in words
    else:
        assert "is the engine's reading of it" in words and "second model" not in words


@both
def test_legend_includes_the_meaning_marks(name: str) -> None:
    legend = page(name).select_one("#legend")
    shown = {text(glyph) for glyph in legend.select(".meaning-mark .g-meaning")}
    assert shown == set(MEANING_GLYPHS.values())
    assert "second model" in text(legend)
    for selector in (".meaning-mark", ".checker-reason"):
        body = rule_body(selector)
        assert "--model" in body and "double" in body, f"{selector} is not in the violet family's double rule"
        assert "--limit" not in body, f"{selector} borrows the limit colour"
    assert "--model" in rule_body(".g-meaning")


# ---------------------------------------------------------------- what the record backs: counted stance,
# what a link opens, where the evidence came from, and the counts behind the banner

# Pinned here, not read from app.js: the words beside an evidence link say what it opens.
LINK_WORDS = {
    "passage": "Open in filing, at this passage",
    "first-line": "Open in filing, at the first line of this passage",
    "document": "Open the filing (this link does not locate the passage)",
}
PAGE_LINK_WORDS = {
    "passage": "Open the page, at this passage",
    "first-line": "Open the page, at the first line of this passage",
    "document": "Open the page (this link does not locate the passage)",
}
BANNER_EXTRAS = {
    "findings_without_quote": ("rests on reported figures only", "rest on reported figures only"),
    "reasons_withheld": ("reason withheld by the number check", "reasons withheld by the number check"),
}


def demoted(finding: dict[str, Any]) -> bool:
    """The verdict rule counted this finding as a stance other than the engine's."""
    counted = finding.get("counted_as")
    return counted is not None and counted != finding["stance"]


def banner(name: str) -> Tag:
    node = page(name).select_one("#status-banner")
    assert node is not None, "no status banner"
    return node


@both
def test_counted_as_line_sits_exactly_on_demoted_findings(name: str) -> None:
    run = record(name)["run"]
    soup = page(name)
    for finding in shown_findings(run):
        fid = finding["id"]
        article = soup.select_one(f'article[data-finding-id="{fid}"]')
        assert article is not None, f"{fid} is not rendered"
        lines = article.select(".counted-as")
        if not demoted(finding):
            assert not lines, f"{fid}: a counted-as line on a finding the rule counted as its own stance"
            continue
        assert len(lines) == 1, f"{fid}: {len(lines)} counted-as lines"
        line, counted = lines[0], finding["counted_as"]
        assert " ".join(text(line).split()).startswith("Counted toward the verdict as:"), fid
        pill = line.select_one(".pill.stance")
        assert pill is not None and f"s-{counted}" in classes(pill), f"{fid}: not the {counted} mark"
        assert text(pill.select_one(".glyph")) == STANCE_GLYPHS[counted], fid
        note = line.select_one("[data-count-note]")
        assert note is not None and text(note) == finding["count_note"], f"{fid}: the note is not the record's"


@both
def test_each_evidence_link_says_what_it_opens(name: str) -> None:
    run = record(name)["run"]
    sources = {source["id"]: source for source in run["sources"]}
    soup = page(name)
    for item in run["evidence"]:
        figure = soup.select_one(f'figure.evidence[data-evidence-id="{item["id"]}"]')
        assert figure is not None, f"{item['id']} is not rendered"
        link = figure.select_one("a.ext")
        assert link is not None, f"{item['id']}: no link"
        on_page = sources.get(item["source_id"], {}).get("kind") == "public_html"
        kind = item.get("link_kind") or ""
        if kind:
            expected = (PAGE_LINK_WORDS if on_page else LINK_WORDS)[kind]
        else:
            expected = "Open the page" if on_page else "Open in filing"
        assert str(link.contents[0]) == expected, f"{item['id']} ({kind or 'no kind'}): {link.contents[0]!r}"


@both
def test_foot_note_is_the_runs_own_provenance(name: str) -> None:
    sample = record(name)
    own = (sample["run"].get("brief") or {}).get("provenance_note")
    expected = own or sample["meta"].get("provenance_note", "")
    assert text(page(name).select_one("#provenance")) == expected


@both
def test_banner_found_count_is_quotes_found(name: str) -> None:
    coverage = record(name)["run"]["coverage"]
    lines = [li for li in banner(name).select(".coverage-facts > li") if "found word for word" in text(li)]
    assert len(lines) == 1, "no single 'found word for word' line"
    first = lines[0].select_one("[data-coverage]")
    field = "quotes_found" if "quotes_found" in coverage else "excerpts_verified"
    assert first is not None and first["data-coverage"] == field, f"the found count is not {field}"
    assert text(first) == f"{coverage[field]:,}"


@both
def test_banner_says_how_many_filings_were_asked_for(name: str) -> None:
    coverage = record(name)["run"]["coverage"]
    node = banner(name).select_one('[data-coverage="filings_asked"]')
    asked = coverage.get("filings_asked")
    if not asked or asked == coverage["sources_requested"]:
        assert node is None, "the banner adds filings asked for where they equal the sources requested"
        return
    assert node is not None and text(node) == f"{asked:,}"
    line = node.find_parent("li")
    assert line.select_one('[data-coverage="sources_requested"]') is not None, "not beside the sources count"
    noun = "filing" if asked == 1 else "filings"
    assert " ".join(text(line).split()).endswith(f"({asked:,} {noun} asked for)")


@both
@pytest.mark.parametrize("field", list(BANNER_EXTRAS))
def test_banner_counts_figure_only_findings_and_withheld_reasons(name: str, field: str) -> None:
    count = record(name)["run"]["coverage"].get(field) or 0
    node = banner(name).select_one(f'[data-coverage="{field}"]')
    if count <= 0:
        assert node is None, f"the banner shows {field}, which is zero or absent"
        return
    assert node is not None and text(node) == f"{count:,}", field
    one, many = BANNER_EXTRAS[field]
    assert (one if count == 1 else many) in " ".join(text(node.parent).split()), field


def test_synthetic_sample_records_what_the_rule_counted() -> None:
    sample = record("synthetic")
    run = sample["run"]
    findings, withheld, coverage = run["findings"], run["unsupported_findings"], run["coverage"]
    for finding in findings:
        own = finding["evidence_ids"] or support_of(finding) == "passed"
        expected = finding["stance"] if own else "context"
        assert finding["counted_as"] == expected, finding["id"]
        assert bool(finding["count_note"]) == (expected != finding["stance"]), finding["id"]
    assert sum(demoted(f) for f in findings) == 1, "the sample needs one demoted finding"
    assert all(f["counted_as"] is None for f in withheld)
    assert {e["link_kind"] for e in run["evidence"]} == set(LINK_WORDS)
    assert coverage["quotes_found"] + coverage["quotes_rejected"] == coverage["quotes_offered"]
    assert coverage["excerpts_verified"] == sum(len(f["evidence_ids"]) for f in findings)
    assert coverage["findings_without_quote"] == sum(not f["evidence_ids"] for f in findings) >= 1
    reasons = [f for f in findings if f["rationale"].startswith("[Reason withheld:")]
    assert coverage["reasons_withheld"] == len(reasons) == 1
    assert any(line.startswith("in the reason:") for line in reasons[0]["checks"]["numbers_detail"])
    read = [s for s in run["sources"] if s["extraction_status"] == "extracted"]
    filings_read = sum(s["kind"] == "sec_filing" for s in read)
    assert coverage["filings_asked"] == run["inputs"]["filings"]
    assert coverage["filings_asked"] not in (filings_read, coverage["sources_requested"])
    assert any(s["kind"] == "public_html" for s in read), "the provenance note names a page that was read"
    note = run["brief"]["provenance_note"]
    assert "page you added" in note and note != sample["meta"]["provenance_note"]


# ---------------------------------------------------------------- review 5: the first screen and the marks

TAKEAWAY_PHRASES = (
    "Every verdict opens to the exact filing passages or reported figures it rests on",
    "quotes are checked word for word",
    "a model's reading, checked by a second model and then by you",
)
SAMPLE_HREFS = {"sample-link": "?sample", "changes-link": "?sample=changes"}


def static_page() -> BeautifulSoup:
    """index.html as served, before any script runs: the first screen's markup."""
    return BeautifulSoup((WEB / "index.html").read_text(encoding="utf-8"), "html.parser")


def test_first_screen_states_the_takeaway_beside_both_samples() -> None:
    """Interface finding 1. Only the markup is checked here: how prominent it looks is
    checked by looking at docs/screenshots/first-screen.png, which no dump covers."""
    soup = static_page()
    takeaway = soup.select_one("header.masthead #takeaway")
    assert takeaway is not None, "the masthead states no takeaway"
    said = " ".join(text(takeaway).split())
    for phrase in TAKEAWAY_PHRASES:
        assert phrase in said, f"the takeaway lacks {phrase!r}"
    row = takeaway.parent
    for link_id, href in SAMPLE_HREFS.items():
        link = soup.select_one(f"#{link_id}")
        assert link is not None and link["href"] == href, link_id
        assert row in link.parents, f"#{link_id} is not beside the takeaway"
        assert link.find_parent(id="empty-state") is None, f"#{link_id} is still in the empty state"


@both
def test_rendered_page_keeps_the_takeaway(name: str) -> None:
    takeaway = page(name).select_one("header.masthead #takeaway")
    assert takeaway is not None and not takeaway.has_attr("hidden")
    assert TAKEAWAY_PHRASES[0] in " ".join(text(takeaway).split())


def test_sample_masthead_says_first_that_the_answers_are_recorded() -> None:
    """Finding 1, sample mode: a short first line says the answers are recorded and who
    answered; the rest of the note is behind a disclosure and still in the DOM."""
    run, meta = record("run")["run"], record("run")["meta"]
    detail = run["engine_detail"]
    assert detail.startswith("replayed from cassette "), "the recorded sample must be replayed"
    line = page("run").select_one("#engine-line")
    fold = line.select_one("details.engine-more")
    assert fold is not None and line.contents[0] is fold, "the engine line is not folded"
    first = " ".join(text(fold.select_one("summary")).split())
    assert first.startswith("Recorded answers: replayed from cassette ")
    assert detail.split("; ")[0] in first, "the first line drops who answered"
    full = " ".join(text(fold.select_one(".prov-full")).split())
    assert len(first) < len(full) // 2, "the first line is not much shorter than the note"
    assert f"Configured meaning check: {meta['checker']['detail']}." in full


@both
def test_refused_names_the_input_mark_and_rejected_only_a_decision(name: str) -> None:
    """Finding 2: "Rejected" is the reader's decision only; refused input is "Refused"."""
    soup = page(name)
    mark = soup.select_one("#legend .mark-reject")
    assert mark is not None and "Refused" in text(mark) and "Rejected" not in text(mark)
    decision_places = ("decision-mark", "review-tally")
    for node in soup.find_all(string=re.compile(r"\brejected\b", re.I)):
        if node.parent.name in ("script", "style"):
            continue
        inside = [p for p in node.parents if set(classes(p)) & set(decision_places)]
        entry = node.find_parent("div")
        inside += [entry] if entry is not None and entry.find_parent(id="legend") and entry.select_one(".decision-mark") else []
        assert inside, f"'rejected' outside a decision: {node.strip()[:80]!r}"


@both
def test_legend_names_the_three_dashed_cases(name: str) -> None:
    """Finding 3: a dashed border means "not final", in exactly three cases."""
    legend = page(name).select_one("#legend")
    entry = legend.select_one('[data-legend="dashed"]')
    assert entry is not None, "the legend has no entry for the dashed border"
    said = " ".join(text(entry).split())
    for phrase in ("Not final", "three", "no engine judged", "Undecided", "run still in progress"):
        assert phrase in said, f"the dashed entry lacks {phrase!r}"
    assert "dashed" in rule_body(".legend-dashed")
    assert "not judged or provisional" not in text(legend)
    # The three, in the stylesheet: an unjudged verdict, a decision to make, a running run.
    assert "dashed" in rule_body(".v-unjudged")
    assert "dashed" in rule_body(".decision-mark.d-undecided")
    assert "dashed" in rule_body(".banner.st-running")


def looks_like_a_decision(glyph: str) -> bool:
    """A square or a box, filled or not, reads as the reader's ▣ ☒ ☐."""
    named = unicodedata.name(glyph, "")
    return glyph in DECISION_GLYPHS.values() or any(w in named for w in ("SQUARE", "BALLOT"))


@both
def test_complete_status_cannot_be_read_as_a_decision(name: str) -> None:
    """Finding 5: no status glyph is a dark square, and a dark filled tag is only a decision."""
    soup = page(name)
    entry = soup.select_one('#legend [data-legend="status"]')
    assert entry is not None, "the legend does not show the status marks"
    complete = text(entry.select_one(".st-complete .glyph")).strip()
    assert not looks_like_a_decision(complete), f"complete is {complete!r}"
    shown = [(word, word.select_one(".glyph")) for word in soup.select(".status-word")]
    banner = soup.select_one("#status-banner")
    shown.append((banner, banner.select_one(".banner-head > .glyph")))
    for holder, node in shown:
        glyph = text(node).strip()
        assert not looks_like_a_decision(glyph), f"a status shows {glyph!r}"
        if "st-complete" in classes(holder):
            assert glyph == complete, f"complete shows {glyph!r}, the legend {complete!r}"
    assert any("st-complete" in classes(holder) for holder, _ in shown) or name == "synthetic"
    assert "dark filled tag is always your own decision" in " ".join(text(soup.select_one("#legend")).split())
    for selector in (".status-word", ".g-status"):
        assert "background" not in rule_body(selector), f"{selector} is drawn as a filled tag"
