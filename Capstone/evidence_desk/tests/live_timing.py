"""Where a LIVE run without a key spends its time, stage by stage, measured inside the run.

``python -m tests.live_timing`` (``make time-live``) runs the example thesis on filings
fetched from SEC EDGAR with the deterministic engine, under four conditions, ``--runs``
times each (default 5), taking the conditions in turn so that a drift of the network
or the machine falls on all four:

- **cold**: an empty filing cache, so the three filings are fetched and parsed;
- **warm**: a cache that already holds them, so only the filing list and the company
  facts are fetched;
- each of the two **with the tagged figures** asked for (``ThesisRequest.tagged_figures``),
  which fetches the newest annual and quarterly report again for their tags.

Every stage is timed by wrapping the functions that make it up, as ``tests/speed_run.py``
does for the offline run. "EDGAR requests" is every HTTP request the client made,
with the waiting its rate limit imposes. Nothing listed calls another listed function,
so the stages add up, and what no stage covers is reported as "unaccounted".

It writes ``results/live-timing-<UTC>.txt`` and prints it. Review 6 asked for this:
until then the time EDGAR takes had been inferred by subtracting an offline profile
from one live run. What this still does not measure is a model: the path with a key
has never been timed, because the API has refused every call from this project.
"""

from __future__ import annotations

import argparse
import statistics
import sys
import tempfile
import time
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from app import __version__
from app.engines.extractive import ExtractiveAnalyst
from app.services import numbers as numbers_service
from app.services import tagged_figures as tagged_service
from app.services import thesis_run
from app.services.examples import EXAMPLE_THESIS
from app.services.thesis_run import execute_run, new_run
from app.sources.edgar import EdgarClient
from app.store import FilingCache, Store
from tests.speed_run import STAGES, Stopwatch, Tally

RESULTS = Path("results")
DEFAULT_RUNS = 5
MIN_RUNS = 2
# The offline stages, with the figures split so that the request for the facts is not
# counted twice, plus the two that only a live run has.
LIVE_STAGES: dict[str, list[tuple[Any, str]]] = {
    **{name: targets for name, targets in STAGES.items() if name != "figures (XBRL)"},
    "EDGAR requests": [(EdgarClient, "get")],
    "figures: build": [
        (numbers_service, "FactBook"),
        (numbers_service, "build_report"),
        (thesis_run, "select_figures"),
    ],
    "tagged figures: read": [
        (tagged_service, "read_tagged_facts"),
        (tagged_service, "build_report"),
        (tagged_service, "tagged_units"),
        (tagged_service, "select_tagged"),
    ],
}
CONDITIONS: tuple[tuple[str, bool, bool], ...] = (
    # name, warm cache, tagged figures
    ("cold cache", False, False),
    ("warm cache", True, False),
    ("cold cache, tagged figures", False, True),
    ("warm cache, tagged figures", True, True),
)


@dataclass
class Sample:
    """One live run: its whole time, each stage's tally, and what it read."""

    whole: float
    stages: dict[str, Tally]
    status: str
    sources_read: int
    tagged_offered: int


def one_run(cache_path: Path, scratch: Path, *, tagged: bool) -> Sample:
    """One run of the example thesis against live EDGAR, timed stage by stage."""
    thesis = EXAMPLE_THESIS.model_copy(deep=True, update={"tagged_figures": tagged})
    store = Store(scratch / f"record-{time.monotonic_ns()}.sqlite")
    cache = FilingCache(cache_path)
    try:
        with EdgarClient.from_env() as client, Stopwatch().timing(LIVE_STAGES) as watch:
            began = time.perf_counter()
            run = execute_run(
                new_run(thesis), store, filings=client, analyst=ExtractiveAnalyst(), cache=cache
            )
            whole = time.perf_counter() - began
    finally:
        cache.close()
    return Sample(
        whole=whole,
        stages=dict(watch.tallies),
        status=run.status.value,
        sources_read=run.coverage.sources_read,
        tagged_offered=run.coverage.tagged_figures_offered,
    )


def _spread(values: list[float]) -> str:
    return f"{min(values) * 1000:6.0f} to {max(values) * 1000:6.0f} ms"


def report_lines(name: str, samples: list[Sample]) -> list[str]:
    """The median of each stage over ``samples``, its share of the median whole run, its calls."""
    wholes = [sample.whole for sample in samples]
    whole = statistics.median(wholes)
    first = samples[0]
    lines = [
        "",
        f"{name}: {len(samples)} runs, whole run median {whole * 1000:.0f} ms "
        f"(range {_spread(wholes).strip()}); status {first.status}, {first.sources_read} sources "
        f"read, {first.tagged_offered} tagged figures offered",
        f"  {'stage':<26} {'median':>9} {'share':>6} {'calls':>6}   range",
    ]
    medians: dict[str, float] = {}
    for stage in LIVE_STAGES:
        seconds = [sample.stages[stage].seconds for sample in samples if stage in sample.stages]
        if not seconds or max(seconds) == 0.0:
            continue
        medians[stage] = statistics.median(seconds)
    for stage, median in sorted(medians.items(), key=lambda item: -item[1]):
        seconds = [sample.stages[stage].seconds for sample in samples]
        calls = statistics.median(sample.stages[stage].calls for sample in samples)
        lines.append(
            f"  {stage:<26} {median * 1000:6.1f} ms {median / whole:6.1%} {calls:6.0f}   "
            f"{_spread(seconds)}"
        )
    unaccounted = whole - sum(medians.values())
    lines.append(f"  {'unaccounted':<26} {unaccounted * 1000:6.1f} ms {unaccounted / whole:6.1%}")
    return lines


def measure(runs: int) -> dict[str, list[Sample]]:
    """``runs`` samples of each condition, the conditions taken in turn."""
    samples: dict[str, list[Sample]] = {name: [] for name, _, _ in CONDITIONS}
    with tempfile.TemporaryDirectory() as directory:
        scratch = Path(directory)
        warm = scratch / "warm-cache.sqlite"
        one_run(warm, scratch, tagged=False)  # fills the warm cache; not a sample
        for number in range(runs):
            for name, is_warm, tagged in CONDITIONS:
                cache_path = warm if is_warm else scratch / f"cold-{number}-{int(tagged)}.sqlite"
                samples[name].append(one_run(cache_path, scratch, tagged=tagged))
    return samples


def main(argv: list[str] | None = None) -> int:
    """Measure, print and write the report; exit 1 if any run did not read its filings."""
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--runs", type=int, default=DEFAULT_RUNS, help="samples per condition")
    args = parser.parse_args(argv)
    if args.runs < MIN_RUNS:
        parser.error(f"--runs must be at least {MIN_RUNS}")
    began = datetime.now(UTC)
    samples = measure(args.runs)
    lines = [
        f"Live run of the example thesis without a key, version {__version__}, "
        f"{began.strftime('%Y-%m-%dT%H:%M:%SZ')}",
        "Filings and company facts from SEC EDGAR; the deterministic engine; one process.",
        "Each stage is timed inside the run. EDGAR requests include the client's rate-limit waits.",
    ]
    for name, _, _ in CONDITIONS:
        lines += report_lines(name, samples[name])
    text = "\n".join(lines) + "\n"
    RESULTS.mkdir(parents=True, exist_ok=True)
    path = RESULTS / f"live-timing-{began.strftime('%Y%m%dT%H%M%SZ')}.txt"
    path.write_text(text)
    print(text)
    print(f"wrote {path}")
    read_all = all(sample.sources_read >= 3 for group in samples.values() for sample in group)
    return 0 if read_all else 1


if __name__ == "__main__":
    sys.exit(main())
