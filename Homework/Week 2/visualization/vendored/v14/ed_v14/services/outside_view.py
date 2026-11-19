"""The outside view of one company and one claim: base rates and peer standing, from SEC frames.

One job: read the company's industry code, compile the claim (:mod:`app.core.claimtest`),
read the frames the test and the peer measures need (:class:`app.sources.frames.FramesSource`,
through the disposable cache), build a :class:`~app.core.frames.Panel`, and hand it to
:mod:`app.core.base_rates` and :mod:`app.core.peers`. Two reference classes:

- **size**: every filer whose revenue in the test's base year was at least the floor
  (by default the largest of $1, $2 or $5 times a power of ten at or under half the
  company's newest revenue in the frames, so a $130B company is compared with filers of
  $50B and more);
- **industry**: the filers SEC lists today under the company's SIC code, with revenue of
  at least :data:`INDUSTRY_FLOOR` (so that shells and start-ups with no sales do not
  set the rates).

A claim that does not compile, or whose test cannot be read on annual frames, gets no
base rate and a ``compile_note`` saying why; the peer standing is computed anyway.
"""

from __future__ import annotations

import math
from collections.abc import Iterable
from datetime import date

from ed_v14.core.base_rates import AnnualTerm, AnnualTest, RefClass, annual_test, base_rate
from ed_v14.core.claimtest import ClaimTest, compile_claim
from ed_v14.core.facts import GROUPS
from ed_v14.core.frames import (
    MEASURES,
    Panel,
    ParsedFrame,
    admitted_years,
    cutoff,
    groups_for,
    parse_frame,
    resolve_group,
)
from ed_v14.core.measures import CATALOGUE
from ed_v14.core.metrics import usd_text
from ed_v14.core.models import Company
from ed_v14.core.peers import PEER_MEASURES, latest_year, peer_standing
from ed_v14.core.ports import FilingSource, SourceError
from ed_v14.core.view_models import OutsideView
from ed_v14.services.view_analytics import peer_measures
from ed_v14.sources.frames import FramesSource

DEFAULT_YEARS = 15
MAX_YEARS = 16
INDUSTRY_FLOOR = 100e6
MIN_FLOOR = 100e6


def size_floor(revenue: float) -> float:
    """The largest of 1, 2 or 5 times a power of ten that is at most half of ``revenue``.

    At least :data:`MIN_FLOOR`. $130.5B gives $50B; $8B gives $2B.
    """
    half = revenue / 2
    if half <= MIN_FLOOR:
        return MIN_FLOOR
    power = 10 ** math.floor(math.log10(half))
    return max(step * power for step in (1, 2, 5) if step * power <= half)


def load_panel(
    source: FramesSource, wanted: Iterable[tuple[str, int]], last_end: date
) -> tuple[Panel, int, dict[str, int]]:
    """A panel of every (group, year) in ``wanted``; also the frames read and the rows dropped."""
    panel = Panel()
    frames_read = 0
    dropped: dict[str, int] = {}
    for group, year in sorted(set(wanted), key=lambda gy: (gy[1], gy[0])):
        parsed: dict[str, ParsedFrame] = {}
        for concept in GROUPS[group].concepts:
            payload = source.frame(concept, f"CY{year}")
            if payload is None:
                continue
            frames_read += 1
            frame = parse_frame(payload, concept, f"CY{year}")
            parsed[concept] = frame
            for reason, count in frame.dropped.items():
                dropped[reason] = dropped.get(reason, 0) + count
        values, counts = resolve_group(group, year, parsed, last_end)
        panel.add(group, year, values, counts)
    return panel, frames_read, dropped


def test_measures(test: AnnualTest) -> set[str]:
    """Every measure an annual test reads."""
    return {p.left.measure for p in test.parts} | {
        p.right.measure for p in test.parts if isinstance(p.right, AnnualTerm)
    }


def coverage() -> tuple[list[str], list[str]]:
    """The catalogue measures a frame panel builds, and those it does not."""
    covered = sorted(m.catalogue for m in MEASURES.values() if m.catalogue in CATALOGUE)
    return covered, sorted(k for k in CATALOGUE if k not in covered)


def _packed_wording(frames: FramesSource, sic: str, count: int) -> str:
    """How the industry's members are described when they were read from the reference pack
    (:class:`app.sources.reference.PackFrames`); "" when they are SEC's list of today."""
    wording = getattr(frames, "members_wording", None)
    return wording(sic, count) if callable(wording) and getattr(frames, "covers", False) else ""


def outside_view(
    company: Company,
    claim: str,
    filings: FilingSource,
    frames: FramesSource,
    *,
    today: date,
    as_of: date | None = None,
    min_revenue: float | None = None,
    years: int = DEFAULT_YEARS,
    sic: str | None = None,
    sic_description: str = "",
) -> OutsideView:
    """Base rates of the claim's test and the company's peer standing, from SEC frames.

    ``sic`` skips the request for the company's industry code (the fixtures pass it).
    Raises :class:`SourceError` when EDGAR cannot give a frame.
    """
    if not 1 <= years <= MAX_YEARS:
        raise ValueError(f"years must be 1 to {MAX_YEARS}, got {years!r}")
    notes: list[str] = []
    if sic is None:
        try:
            profile = filings.company_profile(company)
            sic, sic_description = profile.sic, profile.sic_description
        except SourceError as exc:
            sic = ""
            notes.append(f"The industry code could not be read ({exc}); no industry class.")
    admitted = admitted_years(as_of, today)
    last_end = cutoff(as_of, today)
    read_years = admitted[-years:]
    view = OutsideView(
        company=company,
        claim=claim,
        sic=sic or "",
        sic_description=sic_description,
        as_of=(as_of or today).isoformat(),
    )
    view.covered_measures, view.not_covered_measures = coverage()
    test: AnnualTest | None = None
    if claim.strip():
        compiled = compile_claim(claim)
        if isinstance(compiled, ClaimTest):
            view.test = compiled.canonical
            read = annual_test(compiled)
            if isinstance(read, str):
                view.compile_note = f"The test {compiled.canonical} is not read on frames: {read}."
            else:
                test = read
                view.test_measures = sorted(test_measures(test))
        else:
            view.compile_note = f"The claim does not compile to a test: {compiled.reason}"
    wanted: list[tuple[str, int]] = []
    if test is not None:
        first = read_years[0] - test.class_reach
        span = [y for y in range(first, read_years[-1] + 1) if y >= admitted[0]]
        wanted += [(g, y) for g in groups_for(test_measures(test) | {"revenue"}) for y in span]
    peer_keys = ["revenue" if k == "revenue_growth" else k for k in PEER_MEASURES]
    wanted += [(g, y) for g in groups_for(peer_keys) for y in admitted[-3:]]
    panel, view.frames_read, dropped = load_panel(frames, wanted, last_end)
    view.years_read = panel.years
    members = {cik for cik, _ in frames.sic_members(sic)} if sic else set()
    if sic and not members:
        notes.append(f"SEC lists no filer under SIC {sic}; no industry class.")
    own_year = latest_year(panel, company.cik, panel.years)
    own_revenue = panel.get("revenue", company.cik, own_year) if own_year else None
    floor = (
        min_revenue
        if min_revenue is not None
        else (size_floor(own_revenue.value) if own_revenue else 1e9)
    )
    stamp = view.as_of
    classes: list[tuple[str, RefClass]] = [
        (
            "size",
            RefClass(
                name=f"filers with revenue of at least {usd_text(floor)}",
                floor=floor,
                definition=(
                    f"every filer in SEC's annual frames whose revenue in the test's base year "
                    f"was at least {usd_text(floor)}"
                    + (
                        ""
                        if min_revenue is not None
                        else " (half the company's newest revenue, "
                        "rounded down to 1, 2 or 5 times a power of ten)"
                    )
                ),
            ),
        )
    ]
    if members:
        industry = RefClass(
            name=f"SIC {sic} filers with revenue of at least {usd_text(INDUSTRY_FLOOR)}",
            floor=INDUSTRY_FLOOR,
            members=members,
            sic=sic or "",
            definition=(
                (
                    _packed_wording(frames, sic, len(members))
                    or f"the {len(members):,} filers SEC lists today under SIC {sic}"
                    f"{f' ({sic_description})' if sic_description else ''} that have filed a 10-K"
                )
                + ", "
                f"with revenue of at least {usd_text(INDUSTRY_FLOOR)} in the test's base year "
                "(for a ranking, in the year ranked)"
            ),
        )
        classes.append(("industry", industry))
    if test is not None:
        for key, ref in classes:
            view.base_rates.append(
                base_rate(
                    panel,
                    test,
                    ref,
                    read_years,
                    company_cik=company.cik,
                    claim_test=view.test,
                    as_of=stamp,
                    result_id=f"base_rate:{company.ticker}:{key}:{test.text()}:{stamp}",
                )
            )
    if members and own_year is not None:
        industry_ref = classes[-1][1]
        view.peers = [
            peer_standing(
                panel,
                key,
                company.cik,
                own_year,
                industry_ref,
                as_of=stamp,
                result_id=f"peer:{company.ticker}:{key}:{own_year}:{stamp}",
            )
            for key in PEER_MEASURES
        ]
    elif own_year is None:
        notes.append("The company has no revenue row in the frames read; no peer standing.")
    notes.append(
        f"Frames admitted: periods ending by {last_end.isoformat()} "
        + (
            "(a year before the as-of date: frames carry no filing date)."
            if as_of
            else "(120 days before today: an annual report is due within 60 to 90 days)."
        )
        + " A frame holds the latest value SEC has, so a later restatement is included."
    )
    breaks: dict[str, int] = {}
    for group, _, _, _, _, count in panel.resolution:
        breaks[group] = breaks.get(group, 0) + count
    if any(breaks.values()):
        notes.append(
            "Left out for a scale break (two concepts of one filer and year differing by a "
            "factor near a thousand): "
            + "; ".join(f"{count} filer-year(s) of {g}" for g, count in breaks.items() if count)
            + "."
        )
    if dropped:
        notes.append(
            "Rows dropped: "
            + "; ".join(f"{count:,} {reason}" for reason, count in sorted(dropped.items()))
            + "."
        )
    if frames.not_read:
        notes.append(f"Not on disk, not read: {len(frames.not_read)} frame(s) or list(s).")
    view.notes = notes
    return view


def describe(view: OutsideView) -> list[str]:
    """The view as lines of text for the command line."""
    lines = [
        f"Outside view: {view.company.name} ({view.company.ticker}), SIC {view.sic or 'none'} "
        f"{view.sic_description}, as of {view.as_of}",
        f"Claim: {view.claim or '(none)'}",
        f"Test: {view.test or '(none)'}" + (f" — {view.compile_note}" if view.compile_note else ""),
        f"Frames read: {view.frames_read}; years in the panel: "
        f"{view.years_read[0] if view.years_read else '-'} to "
        f"{view.years_read[-1] if view.years_read else '-'}",
        "",
    ]
    for rate in view.base_rates:
        lines.append(f"[{rate.id}]")
        lines.append(f"  {rate.label}: {rate.display}")
        lines.append(f"  {rate.reading or rate.reason}")
        if rate.formula:
            lines.append(f"  formula: {rate.formula}")
        for year in rate.years:
            lines.append(
                f"    {year.year}: held {year.held} of {year.computable} computable "
                f"({year.in_class} in class)"
            )
        for case in rate.cases:
            lines.append(
                f"    nearest: {case.name} {case.year} (to {case.period_end}) {case.display}, "
                f"revenue {case.revenue_display}; a year later {case.next_year or 'not computable'}"
            )
        for case in rate.own:
            lines.append(f"    own: {case.year} {case.display}")
        lines.extend(f"  - {a}" for a in rate.assumptions)
        lines.append("")
    shown = peer_measures(view.test_measures)
    for peer in view.peers:
        if peer.measure not in shown:
            continue
        lines.append(f"[{peer.id}] {peer.reading}")
        if peer.now and peer.now.rank is not None:
            near = ", ".join(
                f"{n.rank}. {n.name} {n.display}" for n in (*peer.now.above, *peer.now.below)
            )
            lines.append(f"    next to it: {near}")
    more = [peer.measure for peer in view.peers if peer.measure not in shown]
    if more:
        lines.append(f"Standings not shown here (in the JSON): {', '.join(more)}")
    lines.append("")
    lines.extend(f"Note: {note}" for note in view.notes)
    lines.append(f"Catalogue measures covered by frames: {', '.join(view.covered_measures)}")
    lines.append(f"Not covered: {', '.join(view.not_covered_measures)}")
    return lines
