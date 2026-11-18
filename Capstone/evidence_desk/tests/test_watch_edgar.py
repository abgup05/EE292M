"""What the watch asks of EDGAR: one index request per company per cycle, the watched forms."""

from __future__ import annotations

from app.core.watch_policy import WATCH_FORMS
from tests.test_edgar import (
    CURRENT_ROWS,
    NVDA,
    FakeClock,
    counting_index_client,
    submissions_with_items,
)


def test_recent_filings_are_the_watched_forms_newest_first_in_one_request() -> None:
    seen: list[str] = []
    client = counting_index_client(submissions_with_items(CURRENT_ROWS), seen, FakeClock())

    refs = client.recent_filings(NVDA, WATCH_FORMS)

    assert [(r.form, r.filed_date, r.items) for r in refs] == [
        ("8-K", "2026-11-12", ("5.02", "9.01")),
        ("8-K/A", "2026-09-03", ("8.01",)),
        ("10-Q", "2026-08-26", ()),
        ("8-K", "2026-08-26", ("2.02", "9.01")),
        ("8-K", "2026-03-06", ("5.02",)),
        ("10-K", "2026-02-25", ()),
        ("8-K", "2026-02-25", ("2.02",)),
        ("8-K", "2026-01-10", ("1.01",)),
    ]
    assert len(seen) == 1
