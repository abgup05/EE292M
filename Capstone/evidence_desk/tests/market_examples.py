"""Write the outside and market examples to docs/examples/market (``make market-examples``).

Offline: SEC's frames and NVIDIA's company facts as ``make fixtures-market`` recorded them
(``tests/fixtures/frames/manifest.json`` says what and when), NVIDIA's 8-K index as
``make fixtures`` recorded it, and no request to anyone. Three files, each exactly what
the API serves:

- ``outside-view.json``: ``GET /api/companies/NVDA/outside?claim=`` :data:`OUTSIDE_CLAIM`;
- ``market-view.json``: ``GET /api/companies/NVDA/market?price=`` :data:`PRICE` ``&price_date=``
  :data:`PRICE_DAY` ``&claim=`` :data:`MARKET_CLAIM`;
- ``reactions.json``: ``POST /api/companies/NVDA/market/reactions`` with :func:`made_up_closes`.

**The price and the closes are made up.** No source of stock prices that may be
committed was found (``docs/market-view.md``), so the price is a round number and the
closes a seeded random walk with one drop put in by hand after the 8-K of
:data:`DROP_AFTER`. They show the shapes and the arithmetic, and say nothing about NVIDIA's
stock. The SEC numbers are real, as recorded.
"""

from __future__ import annotations

import gzip
import json
import random
import sys
from collections.abc import Sequence
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from typing import Any

from fastapi.testclient import TestClient

from app.api import create_app
from app.sources.frames import FramesSource
from tests.fakes import FakeFilings, recorded_current_reports

OUT = Path("docs/examples/market")
FILES = ("outside-view.json", "market-view.json", "reactions.json")
FRAMES = Path("tests/fixtures/frames")
MARKET_FACTS = Path("tests/fixtures/edgar/companyfacts-market-CIK0001045810.json.gz")
TODAY = date(2026, 11, 18)
OUTSIDE_CLAIM = "Revenue grew more than 50% year over year in fiscal 2026"
MARKET_CLAIM = "The chief executive is leaving"
PRICE = 150.0
PRICE_DAY = date(2026, 11, 17)
DROP_AFTER = "2026-07-02"
SEED = 292


def made_up_closes() -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """A stock and an index on weekdays from 2025-06-02 to :data:`PRICE_DAY`, both made up.

    Daily returns are drawn from a seeded normal (stock 2%, index 1%, the stock moving with
    the index); the stock falls a further 10% on the first weekday after :data:`DROP_AFTER`.
    """
    draw = random.Random(SEED)
    stock, index = 100.0, 5000.0
    stocks: list[dict[str, Any]] = []
    indexes: list[dict[str, Any]] = []
    day = date(2025, 6, 2)
    drop_day = date.fromisoformat(DROP_AFTER) + timedelta(days=1)
    while day <= PRICE_DAY:
        if day.weekday() < 5:
            market = draw.gauss(0.0, 0.01)
            own = market + draw.gauss(0.0, 0.017)
            if day == drop_day:
                own -= 0.10
            stock *= 1 + own
            index *= 1 + market
            stocks.append({"date": day.isoformat(), "close": round(stock, 4)})
            indexes.append({"date": day.isoformat(), "close": round(index, 4)})
        day += timedelta(days=1)
    return stocks, indexes


def _filings() -> FakeFilings:
    filings = FakeFilings.nvidia()
    filings.facts = json.loads(gzip.decompress(MARKET_FACTS.read_bytes()))
    filings.current = recorded_current_reports()
    return filings


def client() -> TestClient:
    """The app over the recorded fixtures: frames from disk only, the clock at :data:`TODAY`."""
    stamp = datetime(TODAY.year, TODAY.month, TODAY.day, 12, tzinfo=UTC)
    app = create_app(
        filings=_filings(), frames=FramesSource(None, FRAMES), wall_clock=lambda: stamp
    )
    return TestClient(app)


def payloads() -> dict[str, Any]:
    """Each example file's payload, by file name."""
    http = client()
    outside = http.get("/api/companies/NVDA/outside", params={"claim": OUTSIDE_CLAIM})
    market = http.get(
        "/api/companies/NVDA/market",
        params={"price": PRICE, "price_date": PRICE_DAY.isoformat(), "claim": MARKET_CLAIM},
    )
    stocks, indexes = made_up_closes()
    reactions = http.post(
        "/api/companies/NVDA/market/reactions",
        json={
            "closes": stocks,
            "index": "supplied",
            "index_closes": indexes,
            "claim": MARKET_CLAIM,
            "days": 3,
        },
    )
    out: dict[str, Any] = {}
    for name, response in zip(FILES, (outside, market, reactions), strict=True):
        if response.status_code != 200:
            raise RuntimeError(f"{name}: HTTP {response.status_code} {response.text[:300]}")
        out[name] = response.json()
    return out


def write(out: Path = OUT) -> list[Path]:
    """Write the three files under ``out``; the paths written."""
    out.mkdir(parents=True, exist_ok=True)
    written = []
    for name, payload in payloads().items():
        path = out / name
        path.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
        written.append(path)
    return written


def main(argv: Sequence[str] | None = None) -> int:
    """Write the examples and say where."""
    del argv
    for path in write():
        print(f"market-examples: wrote {path}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
