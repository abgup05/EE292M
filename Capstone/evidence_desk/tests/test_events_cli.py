"""``python -m app.events``: a company's 8-Ks since its annual report, printed and saved."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

from app.core.ports import SourceError
from app.events import clean, main
from tests.fakes import FakeFilings

NOW = datetime(2026, 11, 18, 9, 30, tzinfo=UTC)


def test_main_prints_the_timeline_and_writes_text_and_record(tmp_path: Path, capsys) -> None:
    code = main(["NVDA"], source=FakeFilings.nvidia_with_events(), now=NOW, out_dir=tmp_path)
    assert code == 0
    out = capsys.readouterr().out
    assert "8-Ks of NVIDIA CORP (NVDA, CIK 1045810) since its annual report of 2026-02-25" in out
    assert (
        "Evidence as of 12 Nov 2026 (8-K), 6 days before today. "
        "Newest periodic report: 10-Q filed 26 Aug 2026." in clean(out)
    )
    assert "2026-11-12  8-K  0001045810-26-000082  (substantive; read)" in out
    assert "Item 5.02. Departure of Directors or Certain Officers" in out
    assert "Roles named: President, Chief Executive Officer" in out
    assert "accepted the resignation of Jen-Hsun Huang" in clean(out)
    assert "2026-06-30  8-K" in out and "(routine; listed from the index only)" in out
    text = (tmp_path / "events-NVDA-20261118T093000Z.txt").read_text()
    assert text in out
    record = json.loads((tmp_path / "events-NVDA-20261118T093000Z.json").read_text())
    assert len(record["timeline"]) == 11 and record["as_of"]["counts"]["read"] == 7


def test_an_unknown_ticker_exits_2_and_an_unreadable_index_exits_1(tmp_path: Path) -> None:
    assert main(["ZZZZ"], source=FakeFilings.nvidia_with_events(), out_dir=tmp_path) == 2
    broken = FakeFilings.nvidia_with_events()
    broken.index_error = SourceError("the filing index of NVIDIA CORP is unavailable")
    assert main(["NVDA"], source=broken, out_dir=tmp_path) == 1
    assert list(tmp_path.iterdir()) == []


def test_filing_text_is_printed_on_one_line_without_control_characters() -> None:
    assert clean("Item\x1b[31m 5.02\n  resigned\t now") == "Item [31m 5.02 resigned now"
