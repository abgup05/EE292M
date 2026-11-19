"""Write the outside and market examples to docs/examples/market (``make market-examples``).

Offline: SEC's frames, NVIDIA's company facts and three managers' 13F filings as
``make fixtures-market`` recorded them (``tests/fixtures/frames/manifest.json`` says what
and when), NVIDIA's 8-K index as ``make fixtures`` recorded it, and no request to anyone.
Four JSON files, each exactly what the API serves, and two of them again as the text the
command line prints:

- ``outside-view.json`` (``outside-view.txt``): ``GET /api/companies/NVDA/outside?claim=``
  :data:`CLAIM`;
- ``market-view.json`` (``market-view.txt``): ``GET /api/companies/NVDA/market?claim=``
  :data:`CLAIM`, with no price given, so the price is the quarter-end price SEC's 13F
  filings give;
- ``analytics.json``: ``GET /api/companies/NVDA/analytics?claim=`` :data:`CLAIM`, both
  views as a flat list in the one analytic shape;
- ``reactions.json``: ``POST /api/companies/NVDA/market/reactions`` with :func:`made_up_closes`.

Every number in the first three comes from SEC as recorded. **The closes of
``reactions.json`` are made up**: no source of daily prices may be committed
(``docs/market-view.md``), so they are a seeded random walk with one drop put in by hand
after the 8-K of :data:`DROP_AFTER`. That file shows the shape and the arithmetic of a
reaction, and says nothing about NVIDIA's stock.
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
from app.core.view_models import MarketView, OutsideView
from app.services import market_view, outside_view
from app.sources.frames import FramesSource
from app.sources.thirteenf import ThirteenFSource
from tests.fakes import FakeFilings, recorded_current_reports

OUT = Path("docs/examples/market")
FILES = ("outside-view.json", "market-view.json", "analytics.json", "reactions.json")
TEXTS = ("outside-view.txt", "market-view.txt")
FRAMES = Path("tests/fixtures/frames")
THIRTEENF = Path("tests/fixtures/thirteenf")
MARKET_FACTS = Path("tests/fixtures/edgar/companyfacts-market-CIK0001045810.json.gz")
TODAY = date(2026, 11, 18)
CLAIM = "Revenue grew more than 50% year over year in fiscal 2026"
REACTION_CLAIM = "The chief executive is leaving"
LAST_CLOSE = date(2026, 11, 17)
DROP_AFTER = "2026-07-02"
SEED = 292


def made_up_closes() -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """A stock and an index on weekdays from 2025-06-02 to :data:`LAST_CLOSE`, both made up.

    Daily returns are drawn from a seeded normal (stock 2%, index 1%, the stock moving with
    the index); the stock falls a further 10% on the first weekday after :data:`DROP_AFTER`.
    """
    draw = random.Random(SEED)
    stock, index = 100.0, 5000.0
    stocks: list[dict[str, Any]] = []
    indexes: list[dict[str, Any]] = []
    day = date(2025, 6, 2)
    drop_day = date.fromisoformat(DROP_AFTER) + timedelta(days=1)
    while day <= LAST_CLOSE:
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


def client(today: date = TODAY) -> TestClient:
    """The app over the recorded fixtures: SEC bodies from disk only, the clock at ``today``."""
    stamp = datetime(today.year, today.month, today.day, 12, tzinfo=UTC)
    app = create_app(
        filings=_filings(),
        frames=FramesSource(None, FRAMES),
        thirteenf=ThirteenFSource(None, THIRTEENF),
        wall_clock=lambda: stamp,
    )
    return TestClient(app)


def payloads() -> dict[str, Any]:
    """Each example file's payload, by file name."""
    http = client()
    outside = http.get("/api/companies/NVDA/outside", params={"claim": CLAIM})
    market = http.get("/api/companies/NVDA/market", params={"claim": CLAIM})
    analytics = http.get("/api/companies/NVDA/analytics", params={"claim": CLAIM})
    stocks, indexes = made_up_closes()
    reactions = http.post(
        "/api/companies/NVDA/market/reactions",
        json={
            "closes": stocks,
            "index": "supplied",
            "index_closes": indexes,
            "claim": REACTION_CLAIM,
            "days": 3,
        },
    )
    out: dict[str, Any] = {}
    for name, response in zip(FILES, (outside, market, analytics, reactions), strict=True):
        if response.status_code != 200:
            raise RuntimeError(f"{name}: HTTP {response.status_code} {response.text[:300]}")
        out[name] = response.json()
    return out


def texts(found: dict[str, Any]) -> dict[str, str]:
    """The two views as the command line prints them, from the payloads."""
    outside = OutsideView.model_validate(found["outside-view.json"])
    market = MarketView.model_validate(found["market-view.json"])
    return {
        "outside-view.txt": "\n".join(outside_view.describe(outside)) + "\n",
        "market-view.txt": "\n".join(market_view.describe(market)) + "\n",
    }


def write(out: Path = OUT) -> list[Path]:
    """Write the files under ``out``; the paths written."""
    out.mkdir(parents=True, exist_ok=True)
    written = []
    found = payloads()
    for name, payload in found.items():
        path = out / name
        path.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
        written.append(path)
    for name, text in texts(found).items():
        path = out / name
        path.write_text(text, encoding="utf-8")
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
