"""Record the analysis model's answers through the API (``make record-analysis``).

Two runs, each with two requests ("propose", then "analyse"), so at most four requests:

1. the example thesis replayed from ``demo/cassettes/nvda-example`` (every other step from
   the cassette), its two answers recorded into that cassette;
2. the analysis example of ``tests/examples_analysis`` (the extractive engine on the recorded
   filings), its two answers recorded into ``demo/cassettes/analysis-example``.

Only a request a cassette lacks is sent, and never more than ``--max-calls`` in all: at the
cap the next request is refused, the run records the computed analysis and this says so.
It needs ``ANTHROPIC_API_KEY`` in ``.env``; it reads no other secret and prints none. After
it: ``make examples-analysis``, ``make golden-baseline`` (the replayed example now carries
an argument, so the tripwire's coverage stage moves) and read both diffs.
"""

from __future__ import annotations

import argparse
import sys
import tempfile
from collections.abc import Sequence
from pathlib import Path

from app.engines.analyser import configured_model
from app.engines.transport import AnthropicTransport, Transport
from tests import examples_analysis
from tests.replay_run import DEFAULT_CASSETTE, CappedTransport, analysis_lines, replay


def record(
    live: Transport,
    *,
    example_cassette: Path = DEFAULT_CASSETTE,
    analysis_cassette: Path = examples_analysis.MODEL_CASSETTE,
) -> list[str]:
    """Run both recordings with ``live`` answering what the cassettes lack; what happened."""
    lines: list[str] = []
    with tempfile.TemporaryDirectory() as scratch:
        run, pending = replay(example_cassette, Path(scratch), analysis_live=live)
    if pending:
        lines.append(
            f"{example_cassette.as_posix()}: {len(pending)} engine request(s) are pending, so "
            "its analysis was not recorded (docs/cassettes.md)"
        )
    else:
        lines += [f"{example_cassette.as_posix()}: {line}" for line in analysis_lines(run)]
    with tempfile.TemporaryDirectory() as scratch:
        run = examples_analysis.model_run(Path(scratch), analysis_cassette, live)
    lines += [f"{analysis_cassette.as_posix()}: {line}" for line in analysis_lines(run)]
    return lines


def main(argv: Sequence[str] | None = None) -> int:
    """Record what the two cassettes lack, within the cap."""
    parser = argparse.ArgumentParser(description=(__doc__ or "").splitlines()[0])
    parser.add_argument("--max-calls", type=int, required=True, help="the most requests sent")
    args = parser.parse_args(argv)
    if args.max_calls < 1:
        print("--max-calls must be at least 1; nothing was asked.")
        return 2
    live = CappedTransport(AnthropicTransport(model=configured_model()), args.max_calls)
    for line in record(live):
        print(line)
    print(
        f"record-analysis: {live.sent} request(s) sent to the API as {live.model} "
        f"(cap {live.max_calls})"
    )
    print("Next: make examples-analysis, make golden-baseline, and read both diffs.")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
