"""Cash and marketable securities reads a company's current securities under the tag it uses.

NVIDIA tagged ``MarketableSecuritiesCurrent`` to the quarter ended 2025-10-26 and
``DebtSecuritiesCurrent`` from 2026-01-25. The measure treats securities as optional, so with
the newer tag unread it silently fell to cash alone ($22.44B for $56.59B). Expected values
are read off the recorded facts (USD millions): cash 22,443 and debt securities 34,143 at
2026-07-26; cash 11,486 and marketable securities 49,122 at 2025-10-26.
"""

from __future__ import annotations

import gzip
import json
from datetime import date
from pathlib import Path

import pytest

from app.core.claim_eval import Measures, evaluate
from app.core.claimtest import ClaimTest, compile_claim
from app.core.facts import FactBook
from app.core.periods import fiscal_calendar

FACTS = Path("tests/fixtures/edgar/companyfacts-market-CIK0001045810.json.gz")


def _measures(as_of: date | None = None) -> Measures:
    payload = json.loads(gzip.decompress(FACTS.read_bytes()))
    return Measures(FactBook(payload, as_of=as_of), fiscal_calendar(payload, as_of=as_of))


def _at(measures: Measures, key: str, end: date) -> float | None:
    return measures.outcome(key, measures.slot("instant", end)).value


def test_the_newer_tag_is_read_for_the_newest_balance_sheet() -> None:
    measures = _measures()
    end = date(2026, 7, 26)
    assert _at(measures, "marketable_securities", end) == pytest.approx(34_143e6)
    assert _at(measures, "cash_and_securities", end) == pytest.approx((22_443 + 34_143) * 1e6)


def test_the_older_tag_still_gives_the_older_balance_sheet() -> None:
    measures = _measures()
    end = date(2025, 10, 26)
    assert _at(measures, "marketable_securities", end) == pytest.approx(49_122e6)
    assert _at(measures, "cash_and_securities", end) == pytest.approx((11_486 + 49_122) * 1e6)


def test_a_claim_about_cash_and_securities_is_computed_on_both() -> None:
    payload = json.loads(gzip.decompress(FACTS.read_bytes()))
    test = compile_claim("Cash and marketable securities exceeded $50 billion.")
    assert isinstance(test, ClaimTest)
    result = evaluate(test, FactBook(payload), calendar=fiscal_calendar(payload))
    assert result.outcome == "holds", result.arithmetic  # $56.59B; cash alone is $22.44B
