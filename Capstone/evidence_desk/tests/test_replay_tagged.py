"""Two recordings of the example made on the same day: without and with the tagged figures.

``demo/cassettes/nvda-example-plain`` and ``demo/cassettes/nvda-example-tagged`` hold a
stand-in's answers to the engine's prompts for the example thesis on the recorded NVIDIA
filings, the second with ``ThesisRequest.tagged_figures`` on (see each cassette's README
and ``docs/tagged-figures.md``). As in ``test_replay.py``, a replay builds every prompt
afresh: a changed prompt, passage or figure no longer finds its answer and the test fails.

The expected verdicts and counts below were read once from the first complete replay
of each recording on 17 November 2026. They are a baseline, not an answer key: they
say what the gate, the number check and the verdict rule make of these recorded answers.
"""

from __future__ import annotations

import shutil
from pathlib import Path

import pytest

from app.core.models import Run
from app.core.tagged_figures import TAGGED_PREFIX
from app.store import FilingCache
from tests.golden_run import replay_record
from tests.replay_run import replay

CASSETTES = Path(__file__).parent.parent / "demo" / "cassettes"
PLAIN, TAGGED = "nvda-example-plain", "nvda-example-tagged"
STALE = (
    "the prompts no longer match the cassette: re-record it (docs/cassettes.md) "
    "and review the new answers"
)
# Per claim: verdict, verified findings, withheld findings.
EXPECTED: dict[str, list[tuple[str, str, int, int]]] = {
    PLAIN: [
        ("c1", "supported", 3, 0),
        ("c2", "supported", 4, 0),
        ("c3", "supported", 4, 0),
        ("c4", "mixed", 4, 0),
        ("c5", "mixed", 3, 0),
    ],
    TAGGED: [
        ("c1", "supported", 4, 0),
        ("c2", "supported", 3, 1),
        ("c3", "supported", 4, 0),
        ("c4", "mixed", 4, 0),
        ("c5", "supported", 3, 0),
    ],
}

Replayed = tuple[Run, list[str], Path]


@pytest.fixture(scope="module", params=[PLAIN, TAGGED])
def replayed(
    request: pytest.FixtureRequest, tmp_path_factory: pytest.TempPathFactory
) -> tuple[str, Replayed]:
    """One replay of a copy of each cassette, shared by the checks below."""
    name: str = request.param
    scratch = tmp_path_factory.mktemp(name)
    copy = scratch / "cassette"
    shutil.copytree(CASSETTES / name, copy)
    run, pending = replay(copy, scratch, tagged_figures=name == TAGGED)
    return name, (run, pending, scratch)


@pytest.fixture(scope="module")
def tagged(tmp_path_factory: pytest.TempPathFactory) -> Run:
    scratch = tmp_path_factory.mktemp("tagged-only")
    copy = scratch / "cassette"
    shutil.copytree(CASSETTES / TAGGED, copy)
    run, pending = replay(copy, scratch, tagged_figures=True)
    assert not pending, STALE
    return run


def test_every_model_request_is_answered(replayed: tuple[str, Replayed]) -> None:
    name, (run, pending, _) = replayed
    assert not pending, f"{name}: {len(pending)} request(s) pending: {STALE}"
    assert run.engine == "claude" and run.coverage.engine_fallbacks == 0, run.errors


def test_every_excerpt_is_an_exact_slice_of_its_filing(replayed: tuple[str, Replayed]) -> None:
    _, (run, _, scratch) = replayed
    stored = FilingCache(scratch / "cache.sqlite").source_texts(run)
    assert run.evidence
    for item in run.evidence:
        text = stored[item.source_id]
        assert text[item.start : item.start + len(item.excerpt)] == item.excerpt, item.id


def test_each_claim_has_its_recorded_verdict_and_counts(replayed: tuple[str, Replayed]) -> None:
    name, (run, pending, _) = replayed
    assert not pending, STALE
    got = [
        (claim["id"], claim["verdict"], claim["findings"], claim["withheld"])
        for claim in replay_record(run)["claims"]
    ]
    assert got == EXPECTED[name], (
        f"{name}: the gate, the number check or the verdict rule now reads the same recorded "
        "answers differently; if that is intended, change EXPECTED and say which stage moved"
    )


def test_without_the_option_no_tagged_figure_is_offered_or_recorded(
    replayed: tuple[str, Replayed],
) -> None:
    name, (run, _, _) = replayed
    tagged_metrics = [m for m in run.metrics if m.id.startswith(TAGGED_PREFIX)]
    if name == PLAIN:
        assert run.coverage.tagged_figures_offered == 0 and not tagged_metrics
        assert run.status.value == "complete"
    else:
        assert run.coverage.tagged_figures_offered == len(tagged_metrics) == 40


# What the tagged recording shows, pinned so that a change in any stage is seen ----------------


def test_findings_cite_tagged_figures_that_were_offered_and_their_numbers_pass(
    tagged: Run,
) -> None:
    offered = {m.id: m for m in tagged.metrics if m.id.startswith(TAGGED_PREFIX)}
    citing = [f for f in tagged.findings if any(i.startswith(TAGGED_PREFIX) for i in f.metric_ids)]
    assert len(citing) == 5
    for finding in citing:
        assert finding.verified and finding.checks.numbers in ("passed", "none")
        for metric_id in finding.metric_ids:
            if metric_id.startswith(TAGGED_PREFIX):
                assert metric_id in offered, metric_id
    cited = {i for f in citing for i in f.metric_ids if i.startswith(TAGGED_PREFIX)}
    # The three claims the example is about each get a figure the company facts cannot give.
    assert "tagged:revenue_by_product:nvda:DataCenterMember:annual:2026-01-25" in cited
    assert (
        "tagged:revenue_by_geography:nvda:ChinaIncludingHongKongMember:change:annual:2026-01-25"
        in cited
    )
    assert any(i.startswith("tagged:revenue_concentration_by_customer:") for i in cited)
    assert offered["tagged:revenue_by_product:nvda:DataCenterMember:annual:2026-01-25"].value == (
        193_737e6
    )


def test_a_number_from_nowhere_is_still_withheld_with_tagged_figures_on(tagged: Run) -> None:
    """The stand-in wrote 23% beside a tagged figure that says 16%; nothing it cited holds 23%."""
    [withheld] = tagged.unsupported_findings
    assert withheld.claim_id == "c2" and "23%" in withheld.withheld_reason
    assert withheld.checks.numbers == "failed"
    assert tagged.status.value == "partial"
    assert tagged.coverage.numbers_unmatched == 1


def test_a_statement_about_fiscal_year_end_is_no_longer_withheld_for_its_year(tagged: Run) -> None:
    """In the first replay this true finding was withheld because "2026" was read as a number."""
    [finding] = [f for f in tagged.findings if "fiscal year-end 2026" in f.statement]
    assert finding.verified and finding.checks.numbers == "passed"
    assert len(finding.metric_ids) == 3 and not finding.evidence_ids


def test_figure_only_findings_are_counted_and_this_is_known(tagged: Run) -> None:
    """With tagged figures on, more findings rest on figures alone; two of them count as support.

    Nothing mechanical checks that a figure bears on a claim: the second model's reading is
    all that stands between a cited figure and a verdict (docs/tagged-figures.md, limits).
    """
    figure_only = [f for f in tagged.findings if not f.evidence_ids]
    assert sorted(f.counted_as or "" for f in figure_only) == ["context", "supports", "supports"]
    assert all(f.checks.support == "passed" for f in figure_only)
