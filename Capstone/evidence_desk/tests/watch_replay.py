"""A year of a company's filings fed to the watch one at a time: ``python -m tests.watch_replay``.

``make watch-replay`` is a measurement, live against EDGAR and with no model. It takes
the company's 10-K, 10-Q, 8-K and 8-K/A filings of the twelve months before today, in
the order they were filed, and makes each "appear" in turn to a real watcher (the real
cycle, job, triage and inbox code, over the real EDGAR client), for the thesis written in
the labels file. The watch's policy is ``ask``, so no run is made: what is measured is
triage alone. Each inbox item is compared with the label written for that filing before
the replay was run: does the filing bear on a claim, and on which.

``--list`` prints the filings of the window (form, date, items and, for an 8-K, the
opening sentences of each item) and triages nothing: that is what the labels were
written from. Results go to ``results/watch-replay-<UTC>.md`` and ``.json``.
"""

from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Sequence
from dataclasses import dataclass, field
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from typing import Any

from app import wiring
from app.core import watch_policy as wording
from app.core.documents import FetchedFiling, FilingRef
from app.core.events import item_sections, opening_sentences
from app.core.models import Company, ThesisCreate, ThesisRequest
from app.core.ports import SourceError
from app.core.watch_models import InboxItem, WatchPolicy
from app.engines.extractive import ExtractiveAnalyst
from app.services import theses
from app.sources.current_report import parse_current_report
from app.sources.edgar import EdgarClient
from app.store import FilingCache, Store
from app.watch.service import Watcher, WatchSettings, run_executor, start_watching
from app.watch.store import WatchStatus, WatchStore

LABELS = Path("eval/watch-replay-nvda.json")
RESULTS = Path("results")


@dataclass
class Revealing:
    """The live EDGAR client, with the filing index cut off at the filings revealed so far."""

    client: EdgarClient
    hidden: set[str] = field(default_factory=set)

    def company(self, ticker: str) -> Company:
        return self.client.company(ticker)

    def recent_filings(self, company: Company, forms: Sequence[str]) -> list[FilingRef]:
        refs = self.client.recent_filings(company, forms)
        return [ref for ref in refs if ref.accession not in self.hidden]

    def filings_of_form(self, company: Company, form: str, limit: int) -> list[FilingRef]:
        refs = self.client.filings_of_form(company, form, limit + len(self.hidden))
        return [ref for ref in refs if ref.accession not in self.hidden][:limit]

    def fetch(self, ref: FilingRef) -> FetchedFiling:
        return self.client.fetch(ref)

    # A run is never made (policy ask); these complete the FilingSource the watcher holds.
    def periodic_filings(self, company: Company, limit: int) -> list[FilingRef]:
        raise SourceError("the replay makes no run")

    def current_reports(self, company: Company, filed_after: str) -> list[FilingRef]:
        raise SourceError("the replay makes no run")

    def company_facts(self, company: Company) -> dict[str, Any]:
        raise SourceError("the replay makes no run")


def window(client: EdgarClient, company: Company, since: str) -> list[FilingRef]:
    """The watched forms filed after ``since``, oldest first."""
    refs = client.recent_filings(company, wording.WATCH_FORMS)
    return sorted(
        (ref for ref in refs if ref.filed_date > since),
        key=lambda ref: (ref.filed_date, ref.accession),
    )


def list_window(client: EdgarClient, refs: list[FilingRef]) -> None:
    """Print each filing of the window as the labels were written from it."""
    for ref in refs:
        print(f"{ref.filed_date} {ref.form} {ref.accession} items={','.join(ref.items) or '-'}")
        if not ref.form.startswith("8-K"):
            continue
        try:
            fetched = client.fetch(ref)
            document = parse_current_report(
                fetched.html, url=ref.url, title=ref.form, published_date=ref.filed_date
            )
        except SourceError as exc:
            print(f"    could not be read: {exc}")
            continue
        for number, section in item_sections(document).items():
            opening = " ".join(opening_sentences(section.text))[:400]
            print(f"    Item {number}: {opening}")


def _claims(item: InboxItem) -> list[str]:
    return [claim.claim_id for claim in item.triage.claims if claim.bears]


def replay(client: EdgarClient, company: Company, labels: dict[str, Any], since: str) -> int:
    refs = window(client, company, since)
    by_accession = {label["accession"]: label for label in labels["labels"]}
    source = Revealing(client, hidden={ref.accession for ref in refs})
    store, cache = Store(":memory:"), FilingCache()
    thesis = theses.create_thesis(
        store,
        ThesisCreate(
            name=labels["thesis"]["name"],
            request=ThesisRequest(
                ticker=company.ticker,
                decision=labels["thesis"]["decision"],
                claims=labels["thesis"]["claims"],
            ),
        ),
    )
    clock = [datetime.fromisoformat(since).replace(tzinfo=UTC)]
    watches = WatchStore(store)
    watcher = Watcher(
        store=store,
        watches=watches,
        status=WatchStatus(cache),
        filings=source,  # type: ignore[arg-type]
        cache=cache,
        execute=run_executor(store, source, ExtractiveAnalyst(), cache),  # type: ignore[arg-type]
        settings=WatchSettings(interval_seconds=wording.MIN_INTERVAL_SECONDS),
        now=lambda: clock[0],
        worker="replay",
    )
    start_watching(store, watches, source, thesis.id, WatchPolicy.ask, clock[0])  # type: ignore[arg-type]

    rows: list[dict[str, Any]] = []
    for ref in refs:
        source.hidden.discard(ref.accession)
        clock[0] = max(clock[0], datetime.fromisoformat(ref.filed_date).replace(tzinfo=UTC))
        clock[0] += timedelta(hours=1)
        report = watcher.cycle()
        page = watches.list_items(limit=wording.MAX_PAGE_SIZE, offset=0)
        item = next((i for i in page.items if i.filing.accession == ref.accession), None)
        label = by_accession.get(ref.accession)
        row: dict[str, Any] = {
            "filed": ref.filed_date,
            "form": ref.form,
            "accession": ref.accession,
            "items": list(ref.items),
            "jobs_queued": report.jobs_queued,
            "flagged": item.triage.bears if item else None,
            "flagged_claims": _claims(item) if item else [],
            "rules": [rule.value for rule in item.triage.rules] if item else [],
            "summary": item.triage.summary if item else "no inbox item",
            "notes": item.triage.notes if item else [],
            "paragraphs": {claim.claim_id: len(claim.paragraphs) for claim in item.triage.claims}
            if item
            else {},
            "label": label["bears"] if label else None,
            "label_claims": label["claims"] if label else [],
            "why": label["why"] if label else "",
        }
        rows.append(row)

    labelled = [row for row in rows if row["label"] is not None]
    agreed = [row for row in labelled if row["flagged"] == row["label"]]
    flagged = [row for row in rows if row["flagged"]]
    claims_agreed = [
        row
        for row in agreed
        if row["flagged"] is False or set(row["flagged_claims"]) >= set(row["label_claims"])
    ]
    lines = [
        f"# Watch replay: {company.name}, filings after {since}",
        "",
        f"Run {datetime.now(UTC):%Y-%m-%d %H:%M} UTC, live EDGAR, no model (triage only; "
        "policy ask). Labels: "
        f"`{LABELS}`, written {labels['written']} before this replay.",
        "",
        f"- Filings fed one at a time: {len(rows)}; jobs queued: "
        f"{sum(r['jobs_queued'] for r in rows)}",
        f"- Flagged by triage as bearing on a claim: {len(flagged)} of {len(rows)}",
        f"- Labelled: {len(labelled)} of {len(rows)}; triage agreed with the label on "
        f"{len(agreed)} of {len(labelled)}",
        f"- Of those agreements, triage also flagged every claim the label names on "
        f"{len(claims_agreed)} of {len(agreed)}",
        "",
        "| Filed | Form | Items | Triage | Claims flagged | Label | Claims labelled | Agree |",
        "| --- | --- | --- | --- | --- | --- | --- | --- |",
    ]
    for row in rows:
        agree = "" if row["label"] is None else ("yes" if row["flagged"] == row["label"] else "NO")
        lines.append(
            f"| {row['filed']} | {row['form']} | {','.join(row['items']) or '-'} | "
            f"{'bears' if row['flagged'] else 'nothing'} | {','.join(row['flagged_claims'])} | "
            f"{'unlabelled' if row['label'] is None else ('bears' if row['label'] else 'nothing')}"
            f" | {','.join(row['label_claims'])} | {agree} |"
        )
    lines += ["", "## Disagreements", ""]
    for row in labelled:
        if row["flagged"] != row["label"]:
            lines.append(
                f"- {row['filed']} {row['form']} {','.join(row['items'])}: triage says "
                f"{'bears' if row['flagged'] else 'nothing'} ({row['summary']}); label says "
                f"{'bears' if row['label'] else 'nothing'}: {row['why']}"
            )
    text = "\n".join(lines) + "\n"
    print(text)
    RESULTS.mkdir(exist_ok=True)
    stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    (RESULTS / f"watch-replay-{stamp}.md").write_text(text)
    (RESULTS / f"watch-replay-{stamp}.json").write_text(json.dumps(rows, indent=2) + "\n")
    print(f"wrote results/watch-replay-{stamp}.md and .json")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--list", action="store_true", help="print the window and triage nothing")
    parser.add_argument("--labels", type=Path, default=LABELS)
    parser.add_argument("--ticker", default="NVDA")
    parser.add_argument("--since", default=None, help="YYYY-MM-DD; default a year before today")
    args = parser.parse_args(argv)
    since = args.since or (date.today() - timedelta(days=365)).isoformat()
    client = wiring.filings_from_env()
    company = client.company(args.ticker)
    refs = window(client, company, since)
    if args.list:
        list_window(client, refs)
        return 0
    labels = json.loads(args.labels.read_text())
    return replay(client, company, labels, labels.get("since", since))


if __name__ == "__main__":
    sys.exit(main())
