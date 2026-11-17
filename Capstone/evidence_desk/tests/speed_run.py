"""Where the offline run spends its time, and what the header cut is worth.

``python -m tests.speed_run profile`` (``make profile``) runs
:func:`tests.golden_run.build_golden` (parse three recorded NVIDIA filings,
chunk, index, retrieve, assess with the extractive engine, gate, summarise,
build the figures, save) and writes to ``results/profile-<UTC>.txt``, printing
it too:

1. every stage timed inside the run itself, with its call count, best of three
   runs at concurrency 1 (so no two stages overlap); what no stage covers is
   reported as "unaccounted", not hidden in an "other";
2. ``save_run`` with version 3's connection pattern (one connection and one WAL
   pragma per call) against the current one (one connection per store);
3. the 25 most expensive functions by cumulative time under cProfile.

``python -m tests.speed_run bench`` (``make bench``) measures the inline-XBRL
header cut by interleaving: ``--runs`` pairs (default 12), each one run with
the cut and one without, alternately in one process. It reports each
variant's median for the parse stage and the whole run, and the paired
difference with its spread, and checks that both variants give the same
golden record. It writes ``results/bench-<UTC>.txt``.

This is the offline path only. A live run's time is EDGAR and, with a key, the
model; neither is in these numbers (``docs/speed.md``).
"""

from __future__ import annotations

import argparse
import contextlib
import cProfile
import functools
import io
import pstats
import sqlite3
import statistics
import sys
import threading
import time
from collections.abc import Callable, Iterator
from contextlib import ExitStack, closing, contextmanager
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from unittest import mock

from app import store as store_module
from app.core.models import Run
from app.engines.extractive import ExtractiveAnalyst
from app.retrieval.search import PassageIndex
from app.services import ingest, thesis_run
from app.sources import filing as filing_parser
from app.store import FilingCache, Store
from tests.golden_run import build_golden

RESULTS = Path("results")
TOP = 25
REPEATS = 3
DEFAULT_PAIRS = 12
MIN_PAIRS = 2

# Each stage, and the functions whose time is its time. Nothing listed calls another listed
# function, so the stages add up; "save_run: serialise" is part of "save_run" and shown apart.
STAGES: dict[str, list[tuple[Any, str]]] = {
    "parse filings": [(ingest, "parse_filing")],
    "chunk": [(thesis_run, "chunk_document")],
    "index (BM25)": [(thesis_run, "PassageIndex")],
    "retrieve": [(PassageIndex, "search")],
    "figures (XBRL)": [(thesis_run, "load_numbers"), (thesis_run, "select_figures")],
    "plan": [(ExtractiveAnalyst, "plan")],
    "assess": [(ExtractiveAnalyst, "assess")],
    "gate_claim": [(thesis_run, "gate_claim")],
    "summary": [(ExtractiveAnalyst, "summarize")],
    "save_run": [(Store, "save_run")],
    "filing cache": [
        (FilingCache, "put_text"),
        (FilingCache, "remember_filing"),
        (FilingCache, "lookup_filing"),
        (FilingCache, "source_texts"),
    ],
}
NESTED: dict[str, list[tuple[Any, str]]] = {
    "save_run: serialise": [(Run, "model_dump_json")],
}


@dataclass
class Tally:
    """Seconds spent in one stage and how many calls it took."""

    seconds: float = 0.0
    calls: int = 0


class Stopwatch:
    """Times named stages by wrapping the functions that make them up (thread-safe)."""

    def __init__(self) -> None:
        """Start with every stage at zero."""
        self.tallies: dict[str, Tally] = {}
        self._lock = threading.Lock()

    def wrap(self, stage: str, function: Callable[..., Any]) -> Callable[..., Any]:
        """``function``, adding the time of each call to ``stage``."""

        @functools.wraps(function)
        def timed(*args: Any, **kwargs: Any) -> Any:
            began = time.perf_counter()
            try:
                return function(*args, **kwargs)
            finally:
                elapsed = time.perf_counter() - began
                with self._lock:
                    tally = self.tallies.setdefault(stage, Tally())
                    tally.seconds += elapsed
                    tally.calls += 1

        return timed

    @contextmanager
    def timing(self, stages: dict[str, list[tuple[Any, str]]]) -> Iterator[Stopwatch]:
        """Patch every function of ``stages`` to be timed while the block runs."""
        with ExitStack() as patches:
            for stage, targets in stages.items():
                self.tallies.setdefault(stage, Tally())
                for owner, name in targets:
                    original = getattr(owner, name)
                    patches.enter_context(
                        mock.patch.object(owner, name, self.wrap(stage, original))
                    )
            yield self


@contextmanager
def version_3_connections() -> Iterator[None]:
    """Make each record write open its own connection and set WAL, as version 3 did.

    Every commit is synced (SQLite's default, ``synchronous=FULL``), as in version 3.
    """
    original = store_module._Database.transaction

    @contextmanager
    def per_call(
        database: store_module._Database, durable: bool = True
    ) -> Iterator[sqlite3.Connection]:
        if database.path == store_module.MEMORY:
            with original(database) as connection:
                yield connection
            return
        with (
            database._lock,
            closing(sqlite3.connect(database.path, timeout=30)) as connection,
            connection,
        ):
            connection.execute("PRAGMA journal_mode=WAL")
            yield connection

    with mock.patch.object(store_module._Database, "transaction", per_call):
        yield


@contextmanager
def every_commit_synced() -> Iterator[None]:
    """Keep one connection per store but sync every commit, progress saves included."""
    original = store_module._Database.transaction

    def synced(
        database: store_module._Database, durable: bool = True
    ) -> contextlib.AbstractContextManager[sqlite3.Connection]:
        return original(database, durable=True)

    with mock.patch.object(store_module._Database, "transaction", synced):
        yield


@dataclass
class Breakdown:
    """Best-of-N seconds and calls per stage, and the best whole run."""

    stages: dict[str, Tally]
    whole: float
    sha256: str

    @property
    def unaccounted(self) -> float:
        """Whole-run time no stage covers (store set-up, ingest and policy logic, the record)."""
        return self.whole - sum(
            tally.seconds for name, tally in self.stages.items() if name in STAGES
        )


def breakdown(repeats: int = REPEATS, concurrency: int = 1) -> Breakdown:
    """Time every stage inside :func:`build_golden`; the best of ``repeats`` runs per stage."""
    best: dict[str, Tally] = {}
    whole = float("inf")
    digests: set[str] = set()
    for _ in range(repeats):
        with Stopwatch().timing({**STAGES, **NESTED}) as watch:
            began = time.perf_counter()
            digests.add(build_golden(concurrency)["sha256"])
            whole = min(whole, time.perf_counter() - began)
        for stage, tally in watch.tallies.items():
            if stage not in best or tally.seconds < best[stage].seconds:
                best[stage] = tally
    if len(digests) != 1:
        raise RuntimeError("the record differed between runs: the run is not deterministic")
    return Breakdown(best, whole, digests.pop())


def _breakdown_lines(result: Breakdown) -> list[str]:
    lines = [f"  {'stage':<22} {'time':>9} {'share':>6} {'calls':>6}"]
    for stage, tally in sorted(result.stages.items(), key=lambda item: -item[1].seconds):
        if stage in NESTED:
            continue
        share = tally.seconds / result.whole
        lines.append(f"  {stage:<22} {tally.seconds * 1000:7.1f} ms {share:6.1%} {tally.calls:6d}")
        if stage == "save_run":
            nested = result.stages["save_run: serialise"]
            lines.append(
                f"    of which serialise   {nested.seconds * 1000:7.1f} ms "
                f"{nested.seconds / result.whole:6.1%} {nested.calls:6d}"
            )
    lines.append(
        f"  {'unaccounted':<22} {result.unaccounted * 1000:7.1f} ms "
        f"{result.unaccounted / result.whole:6.1%}"
    )
    lines.append(f"  {'whole run':<22} {result.whole * 1000:7.1f} ms")
    return lines


def profile(out_dir: Path = RESULTS) -> Path:
    """Write the stage breakdown, the save comparison and the cProfile lines; return the file."""
    now = datetime.now(UTC)
    current = breakdown()
    with version_3_connections():
        old = breakdown()
    with every_commit_synced():
        synced = breakdown()
    out = io.StringIO()
    out.write(f"Offline example run (build_golden), {now:%Y-%m-%d %H:%M:%S} UTC\n")
    out.write(f"record sha256 {current.sha256}\n\n")
    out.write("Every stage timed inside the run, best of three, concurrency 1, no profiler:\n")
    out.write("\n".join(_breakdown_lines(current)) + "\n\n")
    out.write("save_run under three ways of committing (best of three each):\n")
    for label, result in (
        ("v3: connection + WAL pragma per call, every commit synced", old),
        ("one connection, every commit synced", synced),
        ("now: one connection, progress saves not synced", current),
    ):
        tally = result.stages["save_run"]
        out.write(
            f"  {label:<58} {tally.seconds * 1000:6.1f} ms over {tally.calls} calls "
            f"({tally.seconds / tally.calls * 1000:.2f} ms each); whole run "
            f"{result.whole * 1000:.1f} ms\n"
        )
    if len({old.sha256, synced.sha256, current.sha256}) != 1:
        raise RuntimeError("the way of committing changed the record")
    out.write("  record sha256 identical under all three\n\n")

    profiler = cProfile.Profile()
    began = time.perf_counter()
    profiler.enable()
    build_golden()
    profiler.disable()
    wall = time.perf_counter() - began
    out.write(f"cProfile of one build_golden() (concurrency 3): {wall:.3f} s wall, ")
    out.write("slower than unprofiled\n")
    stats = pstats.Stats(profiler, stream=out)
    stats.strip_dirs().sort_stats(pstats.SortKey.CUMULATIVE).print_stats(TOP)
    out_dir.mkdir(parents=True, exist_ok=True)
    path = out_dir / f"profile-{now:%Y%m%dT%H%M%SZ}.txt"
    path.write_text(out.getvalue())
    print(out.getvalue())
    print(f"wrote {path}")
    return path


def _no_cut(html: str) -> tuple[str, str]:
    """Version 2's parse: the ``ix:header`` block is left in the HTML (the walk skips it)."""
    return html, ""


def _timed_run(cut: bool) -> tuple[float, float, str]:
    """One :func:`build_golden` with or without the header cut: (parse s, whole s, sha256)."""
    with ExitStack() as stack:
        if not cut:
            stack.enter_context(mock.patch.object(filing_parser, "_cut_ix_headers", _no_cut))
        watch = stack.enter_context(Stopwatch().timing({"parse filings": STAGES["parse filings"]}))
        began = time.perf_counter()
        digest = build_golden()["sha256"]
        whole = time.perf_counter() - began
    return watch.tallies["parse filings"].seconds, whole, digest


def _spread(values: list[float]) -> str:
    """Median, interquartile range and extremes, in milliseconds."""
    q1, median, q3 = statistics.quantiles(values, n=4, method="inclusive")
    return (
        f"median {median * 1000:+.1f} ms, IQR {q1 * 1000:+.1f} to {q3 * 1000:+.1f} ms, "
        f"range {min(values) * 1000:+.1f} to {max(values) * 1000:+.1f} ms"
    )


def bench(pairs: int = DEFAULT_PAIRS, out_dir: Path = RESULTS) -> dict[str, float]:
    """Interleave ``pairs`` runs with and without the header cut; report and return the medians."""
    if pairs < MIN_PAIRS:
        raise ValueError(f"pairs must be at least {MIN_PAIRS}")
    _timed_run(True), _timed_run(False)  # warm-up, discarded
    rows: list[tuple[float, float, float, float]] = []
    digests: set[str] = set()
    for _ in range(pairs):
        cut_parse, cut_whole, cut_digest = _timed_run(True)
        raw_parse, raw_whole, raw_digest = _timed_run(False)
        digests |= {cut_digest, raw_digest}
        rows.append((cut_parse, raw_parse, cut_whole, raw_whole))
    parse_saved = [raw - cut for cut, raw, _, _ in rows]
    whole_saved = [raw - cut for _, _, cut, raw in rows]
    medians = {
        "parse_cut": statistics.median(r[0] for r in rows),
        "parse_no_cut": statistics.median(r[1] for r in rows),
        "whole_cut": statistics.median(r[2] for r in rows),
        "whole_no_cut": statistics.median(r[3] for r in rows),
    }
    lines = [
        f"Header cut, interleaved: {pairs} pairs (cut, no cut, cut, no cut, ...), one process, "
        f"{datetime.now(UTC):%Y-%m-%d %H:%M:%S} UTC",
        f"  parse 3 filings: cut {medians['parse_cut'] * 1000:.1f} ms, "
        f"no cut {medians['parse_no_cut'] * 1000:.1f} ms (medians)",
        f"    saved per pair: {_spread(parse_saved)}; cut faster in "
        f"{sum(d > 0 for d in parse_saved)} of {pairs}",
        f"  whole run:       cut {medians['whole_cut'] * 1000:.1f} ms, "
        f"no cut {medians['whole_no_cut'] * 1000:.1f} ms (medians)",
        f"    saved per pair: {_spread(whole_saved)}; cut faster in "
        f"{sum(d > 0 for d in whole_saved)} of {pairs}",
        f"  record sha256: {', '.join(sorted(digests))}",
        "  pairs (ms): parse cut/no cut, whole cut/no cut",
    ]
    lines += [
        f"    {a * 1000:6.1f} {b * 1000:6.1f}   {c * 1000:6.1f} {d * 1000:6.1f}"
        for a, b, c, d in rows
    ]
    text = "\n".join(lines) + "\n"
    print(text)
    out_dir.mkdir(parents=True, exist_ok=True)
    path = out_dir / f"bench-{datetime.now(UTC):%Y%m%dT%H%M%SZ}.txt"
    path.write_text(text)
    print(f"wrote {path}")
    if len(digests) != 1:
        raise RuntimeError("the header cut changed the record, or the run is not deterministic")
    return medians


def main(argv: list[str] | None = None) -> int:
    """``profile`` or ``bench [--runs PAIRS]``."""
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("profile", help="stage breakdown and cProfile; results/profile-<UTC>.txt")
    bench_parser = sub.add_parser("bench", help="header cut against no cut, interleaved")
    bench_parser.add_argument("--runs", type=int, default=DEFAULT_PAIRS, help="pairs to run")
    args = parser.parse_args(argv)
    if args.command == "profile":
        profile()
    else:
        bench(args.runs)
    return 0


if __name__ == "__main__":
    sys.exit(main())
