"""The measures probe (``make measures-probe``) on NVIDIA's recorded facts and 10-K.

Each catalogue measure is computed for the newest fiscal year as a claim test computes it,
and each company's newest 10-K is read for a part's revenue and operating income.
"""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

import pytest

from app import measures_probe as probe
from app.core.measures import CATALOGUE
from tests.test_breakdowns import nvidia as nvidia_filings


@pytest.fixture(scope="module")
def nvidia() -> probe.CompanyMeasures:
    return probe.probe_company(nvidia_filings(), "NVDA")


def test_every_measure_is_probed_for_the_newest_fiscal_year(nvidia) -> None:
    assert nvidia.error is None
    assert set(nvidia.values) | set(nvidia.misses) == set(CATALOGUE)
    assert nvidia.fiscal_year.startswith("FY")
    assert nvidia.values["revenue"] == "$215.94B"
    assert nvidia.values["opex_ratio"].endswith("%")
    # The recorded company facts keep only the panel's concepts (facts-manifest.json), so
    # every measure the catalogue added misses here, with the claim test's reason; the
    # live probe is where they have values.
    assert "PaymentsForRepurchaseOfCommonStock" in nvidia.misses["share_repurchases"]
    assert "No total assets balance" in nvidia.misses["total_assets"]


def test_a_miss_carries_the_reason_a_claim_test_would_give(nvidia) -> None:
    for key, reason in nvidia.misses.items():
        assert reason.strip(), key


def test_the_newest_10k_parts_rows(nvidia) -> None:
    parts = nvidia.parts
    assert parts.form == "10-K" and parts.error is None
    assert parts.segment_revenue and parts.segment_both_years
    assert parts.segment_operating_income
    assert parts.product_revenue and parts.product_both_years


def test_the_table_counts_each_measure_over_the_companies_and_names_the_misses(
    nvidia, tmp_path: Path
) -> None:
    broken = probe.CompanyMeasures(ticker="ZZZZ", error="no such ticker")
    table = probe.build_table([nvidia, broken])

    assert "| share_repurchases |" in table
    assert "1 of 1" in table  # a failed company is not in the denominator
    assert "ZZZZ: no such ticker" in table
    missing = next(iter(nvidia.misses), None)
    if missing is not None:
        row = next(line for line in table.splitlines() if line.startswith(f"| {missing} |"))
        assert "0 of 1" in row and "NVDA" in row


def test_main_writes_the_table(tmp_path: Path, capsys) -> None:
    now = datetime(2026, 11, 18, 12, tzinfo=UTC)

    code = probe.main(["NVDA"], source=nvidia_filings(), now=now, out_dir=tmp_path)

    assert code == 0
    written = (tmp_path / "measures-20261118T120000Z.md").read_text()
    assert written.startswith("# Measures probe, 20261118T120000Z")
    assert "measures-probe: wrote" in capsys.readouterr().out
