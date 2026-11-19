"""The outside view from the command line (``make outside-view T=NVDA CLAIM="..."``).

Live: SEC's frames and its company list by industry code, through the disposable cache
under ``data/cache/frames`` (a cold cache costs about a hundred requests, four a second
at most). Prints the base rates of the claim's test and the company's peer standing, and
writes the result as JSON to ``results/outside-<ticker>-<UTC>.json``.

Exit codes: 0 when the view was made, 1 when EDGAR could not give what it needs.
"""

from __future__ import annotations

import argparse
import sys
from collections.abc import Sequence
from datetime import UTC, date, datetime
from pathlib import Path

from ed_v14 import wiring
from ed_v14.core.models import as_of_problem
from ed_v14.core.ports import SourceError, UnknownTicker
from ed_v14.services.outside_view import DEFAULT_YEARS, describe, outside_view
from ed_v14.sources.frames import FramesSource

RESULTS = Path("results")


def main(argv: Sequence[str] | None = None) -> int:
    """Parse the arguments, make the view, print it and write it."""
    parser = argparse.ArgumentParser(prog="outside-view")
    parser.add_argument("ticker")
    parser.add_argument("--claim", default="")
    parser.add_argument("--as-of", type=date.fromisoformat, default=None)
    parser.add_argument("--min-revenue", type=float, default=None, help="USD, e.g. 5e10")
    parser.add_argument("--years", type=int, default=DEFAULT_YEARS)
    args = parser.parse_args(argv)
    today = datetime.now(UTC).date()
    if args.as_of is not None and (problem := as_of_problem(args.as_of, today)):
        print(f"outside-view: {problem}", file=sys.stderr)
        return 2
    with wiring.filings_from_env() as edgar:
        frames = FramesSource(edgar.get, wiring.frames_dir())
        try:
            company = edgar.company(args.ticker)
            view = outside_view(
                company,
                args.claim,
                edgar,
                frames,
                today=today,
                as_of=args.as_of,
                min_revenue=args.min_revenue,
                years=args.years,
            )
        except (SourceError, UnknownTicker) as exc:
            print(f"outside-view: {exc}", file=sys.stderr)
            return 1
    print("\n".join(describe(view)))
    RESULTS.mkdir(exist_ok=True)
    stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    out = RESULTS / f"outside-{company.ticker}-{stamp}.json"
    out.write_text(view.model_dump_json(indent=2), encoding="utf-8")
    print(f"outside-view: {frames.requests} request(s) to SEC; written to {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
