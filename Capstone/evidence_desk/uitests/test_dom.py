"""Browser-level checks of the page, against the JSON record the page was given.

`make uitest` renders /?sample=synthetic and /?sample in headless Chromium and
writes the resulting DOM to results/dom-synthetic.html and results/dom-sample.html;
these tests read those files and the sample records in src/web. They check what a
reader sees: verdict marks, counts and their denominators, highlighted quotes,
reported figures, model-written badges, links and the legend.
"""

from __future__ import annotations

import json
import re
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
PLACEHOLDERS = ("undefined", "NaN", "[object Object]", "null")
MODEL_ONLY_ENGINE = "extractive"


@cache
def record(name: str) -> dict[str, Any]:
    """The sample file the page loaded: {"note", "meta", "run"}."""
    return json.loads((WEB / PAGES[name][0]).read_text(encoding="utf-8"))


@cache
def page(name: str) -> BeautifulSoup:
    """The DOM the headless browser dumped after the page rendered that record."""
    path = RESULTS / PAGES[name][1]
    if not path.is_file() or path.stat().st_size == 0:
        pytest.fail(f"{path} is missing or empty: run `make uitest`, which renders it first")
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
    links = [a for a in page("run").select("a.ext") if text(a).startswith("Open in filing")]
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
    assert "input was rejected" in words


@both
def test_limit_and_model_glyphs_keep_one_meaning(name: str) -> None:
    for node in page(name).find_all(string=True):
        for glyph, owner in (("▲", "g-limit"), ("✎", "g-model")):
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
    ("support", "unchecked"): "Meaning: not checked by a second model",
    ("support", "passed"): "Meaning: checked by a second model",
    ("support", "failed"): "Meaning: failed the second-model check",
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
    from app.core.models import Run, Verdict

    for name in PAGES:
        Run.model_validate(record(name)["run"])
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
