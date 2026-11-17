"""Where the offline run spends its time, and how long it takes.

``python -m tests.speed_run profile`` (``make profile``) runs
:func:`tests.golden_run.build_golden` once under :mod:`cProfile` (parse three
filings, chunk, index, retrieve, assess with the extractive engine, gate, build
the figures) and writes the 25 most expensive functions by cumulative time to
``results/profile-<UTC>.txt``, printing them too.

``python -m tests.speed_run bench`` (``make bench``) runs it ``--runs`` times
(default 5) and prints the median wall time in seconds, with every run, and the
record's sha256 so a speed change can be seen not to move the tripwire.
"""

from __future__ import annotations

import argparse
import cProfile
import io
import pstats
import statistics
import sys
import time
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path

from app.core.documents import Document
from app.core.models import Company
from app.engines.extractive import ExtractiveAnalyst
from app.retrieval.chunk import chunk_document
from app.retrieval.search import PassageIndex
from app.services.examples import EXAMPLE_THESIS
from app.services.ingest import filing_title
from app.services.numbers import load_numbers, select_figures
from app.sources.filing import parse_filing
from tests.golden_run import build_golden
from tests.replay_run import recorded_filings

RESULTS = Path("results")
TOP = 25
STAGE_REPEATS = 3


def _best(action: Callable[[], object], repeats: int = STAGE_REPEATS) -> tuple[float, object]:
    """The fastest of ``repeats`` timings of ``action``, in seconds, and its last result."""
    best = float("inf")
    result: object = None
    for _ in range(repeats):
        began = time.perf_counter()
        result = action()
        best = min(best, time.perf_counter() - began)
    return best, result


def stage_timings() -> dict[str, float]:
    """Unprofiled seconds per stage of the example run (best of three each), and the total.

    The stages are timed by calling the pipeline's own functions on the same
    inputs; ``other`` is what the whole run takes beyond them (assessment, the
    gate, the verdict rule, saving the record).
    """
    filings = recorded_filings()
    company: Company = filings.company(EXAMPLE_THESIS.ticker)
    refs = filings.refs

    def parse() -> list[Document]:
        return [
            parse_filing(
                str(filings.documents[ref.url]),
                url=ref.url,
                title=filing_title(company, ref),
                published_date=ref.filed_date,
            )
            for ref in refs
        ]

    timings: dict[str, float] = {}
    timings["parse 3 filings"], parsed = _best(parse)
    documents = list(parsed)  # type: ignore[call-overload]
    timings["chunk"], chunked = _best(
        lambda: [p for i, d in enumerate(documents) for p in chunk_document(f"s{i + 1}", d)]
    )
    passages = list(chunked)  # type: ignore[call-overload]
    timings["index (BM25)"], index = _best(lambda: PassageIndex(passages))
    queries = ExtractiveAnalyst().plan(EXAMPLE_THESIS, company)
    timings["retrieve 5 claims"], _ = _best(
        lambda: [
            index.search([claim, *claim_queries])  # type: ignore[attr-defined]
            for claim, claim_queries in zip(EXAMPLE_THESIS.claims, queries, strict=True)
        ]
    )
    timings["figures (XBRL)"], _ = _best(
        lambda: select_figures(load_numbers(company, filings).report)
    )
    timings["whole run"], _ = _best(build_golden)
    timings["other"] = timings["whole run"] - sum(
        seconds for stage, seconds in timings.items() if stage != "whole run"
    )
    return timings


def profile(out_dir: Path = RESULTS) -> Path:
    """Profile one :func:`build_golden` and write the top lines; return the file written."""
    profiler = cProfile.Profile()
    began = time.perf_counter()
    profiler.enable()
    record = build_golden()
    profiler.disable()
    wall = time.perf_counter() - began
    buffer = io.StringIO()
    buffer.write("Unprofiled, best of three, by stage:\n")
    for stage, seconds in stage_timings().items():
        buffer.write(f"  {stage:<20} {seconds * 1000:8.1f} ms\n")
    buffer.write("\n")
    stats = pstats.Stats(profiler, stream=buffer)
    stats.strip_dirs().sort_stats(pstats.SortKey.CUMULATIVE).print_stats(TOP)
    header = (
        f"build_golden() under cProfile, {datetime.now(UTC):%Y-%m-%d %H:%M:%S} UTC\n"
        f"wall time {wall:.3f} s (profiled; slower than unprofiled); "
        f"record sha256 {record['sha256']}\n"
    )
    out_dir.mkdir(parents=True, exist_ok=True)
    path = out_dir / f"profile-{datetime.now(UTC):%Y%m%dT%H%M%SZ}.txt"
    path.write_text(header + buffer.getvalue())
    print(header + buffer.getvalue())
    print(f"wrote {path}")
    return path


def bench(runs: int = 5) -> float:
    """The median wall time of ``runs`` calls of :func:`build_golden`, in seconds."""
    if runs < 1:
        raise ValueError("runs must be at least 1")
    timings: list[float] = []
    digests: set[str] = set()
    for _ in range(runs):
        began = time.perf_counter()
        digests.add(build_golden()["sha256"])
        timings.append(time.perf_counter() - began)
    median = statistics.median(timings)
    listed = ", ".join(f"{t:.3f}" for t in timings)
    print(f"build_golden: median {median:.3f} s over {runs} runs ({listed} s)")
    print(f"record sha256: {', '.join(sorted(digests))}")
    if len(digests) != 1:
        raise RuntimeError("the record differed between runs: the run is not deterministic")
    return median


def main(argv: list[str] | None = None) -> int:
    """``profile`` or ``bench [--runs N]``."""
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("profile", help="cProfile one run; top lines to results/profile-<UTC>.txt")
    bench_parser = sub.add_parser("bench", help="median wall time of several runs")
    bench_parser.add_argument("--runs", type=int, default=5)
    args = parser.parse_args(argv)
    if args.command == "profile":
        profile()
    else:
        bench(args.runs)
    return 0


if __name__ == "__main__":
    sys.exit(main())
