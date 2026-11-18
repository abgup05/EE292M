"""How much a watcher writing the record slows a run: ``python -m tests.watch_contention``.

``make watch-contention`` runs the example thesis offline (recorded NVIDIA filings, the
extractive engine, a fresh record and cache each time) ``--pairs`` times alone and
``--pairs`` times while a second process does watcher cycles on the same files, in
alternating pairs (alone first in even pairs, second in odd ones). It prints each time,
the medians and the cycles the watcher did during each contended run. Offline, on one
machine: it says nothing about EDGAR's latency, which a live run is dominated by.
"""

from __future__ import annotations

import argparse
import multiprocessing
import statistics
import sys
import tempfile
import time
from pathlib import Path

from app.core.models import ThesisCreate, ThesisRequest
from app.core.watch_models import WatchPolicy
from app.engines.extractive import ExtractiveAnalyst
from app.services import theses, thesis_run
from app.services.examples import EXAMPLE_THESIS
from app.store import FilingCache, Store
from app.watch.service import start_watching
from app.watch.store import WatchStore
from tests.fakes import FakeFilings, FakePages
from tests.test_watch_contention import T0, _cycles


def one_run(directory: Path, contended: bool) -> tuple[float, int]:
    """Seconds the example run took, and the watcher cycles done meanwhile (0 when alone)."""
    record, cache = directory / "record.sqlite", directory / "filings.sqlite"
    store, files = Store(record), FilingCache(cache)
    source = FakeFilings.nvidia()
    thesis = theses.create_thesis(
        store,
        ThesisCreate(
            name="Watched",
            request=ThesisRequest(
                ticker="NVDA",
                decision="A watched thesis of NVIDIA",
                claims=["Buy because Jane Smith is gone."],
            ),
        ),
    )
    start_watching(store, WatchStore(store), source, thesis.id, WatchPolicy.ask, T0)
    context = multiprocessing.get_context("spawn")
    started, stop, out = context.Event(), context.Event(), context.Queue()
    contender = None
    if contended:
        contender = context.Process(
            target=_cycles, args=(str(record), str(cache), started, stop, out)
        )
        contender.start()
        started.wait(timeout=60)
    run = thesis_run.new_run(EXAMPLE_THESIS)
    store.save_run(run)
    begun = time.perf_counter()
    thesis_run.execute_run(
        run,
        store,
        filings=source,
        analyst=ExtractiveAnalyst(),
        fetch_page=FakePages({}),
        cache=files,
    )
    elapsed = time.perf_counter() - begun
    cycles = 0
    if contender is not None:
        stop.set()
        outcome, cycles, detail = out.get(timeout=120)
        contender.join(timeout=60)
        if outcome != "ok":
            raise SystemExit(f"FAIL: the watcher failed: {detail}")
    store.close()
    files.close()
    return elapsed, cycles


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--pairs", type=int, default=6)
    args = parser.parse_args(argv)
    alone: list[float] = []
    contended: list[float] = []
    cycles: list[int] = []
    for pair in range(args.pairs):
        order = (False, True) if pair % 2 == 0 else (True, False)
        for busy in order:
            with tempfile.TemporaryDirectory(prefix="contention-") as directory:
                seconds, done = one_run(Path(directory), busy)
            (contended if busy else alone).append(seconds)
            if busy:
                cycles.append(done)
            print(
                f"pair {pair + 1}: {'with a watcher' if busy else 'alone'}: "
                f"{seconds * 1000:.0f} ms" + (f", {done} watcher cycles meanwhile" if busy else "")
            )
    print(
        f"median of {args.pairs}: alone {statistics.median(alone) * 1000:.0f} ms "
        f"(range {min(alone) * 1000:.0f} to {max(alone) * 1000:.0f}); with a watcher "
        f"{statistics.median(contended) * 1000:.0f} ms (range {min(contended) * 1000:.0f} to "
        f"{max(contended) * 1000:.0f}); watcher cycles per contended run: median "
        f"{statistics.median(cycles):.0f}, {min(cycles)} to {max(cycles)}"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
