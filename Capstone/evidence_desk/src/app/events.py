"""A company's 8-Ks since its newest annual report, as text (``make events T=NVDA``).

``python -m app.events TICKER`` lists every 8-K and 8-K/A the company filed after
its newest 10-K, from EDGAR's index, and reads the ones a run would read
(:mod:`app.services.events`): every 8-K after the newest periodic report, and
those of a substantive category, newest first, up to the cap. For each it prints
the filing date, the items with their SEC titles and categories, the opening
sentences of each item read, and for Item 5.02 the officer roles it names. It
writes ``results/events-<ticker>-<UTC time>.txt`` and, as the record, ``.json``.
No model is involved. Exit codes: 0 done, 1 EDGAR could not list the company's
filings, 2 unknown ticker.
"""

from __future__ import annotations

import argparse
import re
import sys
import textwrap
from datetime import UTC, datetime
from pathlib import Path

from app.core import policy
from app.core.event_models import Event, EventStatus
from app.core.models import CompanyEvents
from app.core.ports import FilingSource, SourceError, UnknownTicker
from app.services.events import company_events
from app.sources.edgar import EdgarClient
from app.store import FilingCache

RESULTS_DIR = Path("results")
_UNSAFE_NAME = re.compile(r"[^A-Za-z0-9-]")
_CONTROL = re.compile(r"[\x00-\x08\x0b-\x1f\x7f]")
WIDTH = 100


def clean(text: str) -> str:
    """Filing text on one line, with control characters removed (it is data, not markup)."""
    return " ".join(_CONTROL.sub(" ", text).split())


def _wrapped(text: str, indent: str) -> list[str]:
    return textwrap.wrap(
        clean(text), WIDTH, initial_indent=indent, subsequent_indent=indent + "  "
    ) or [indent]


def _event_lines(event: Event) -> list[str]:
    kind = policy.EVENT_KIND_LABELS["substantive" if event.substantive else "routine"]
    head = f"{event.filed_date}  {event.form}  {event.accession}  ({kind}; {_status(event)})"
    lines = [head, f"    {event.url}"]
    if event.event_date and event.event_date != event.filed_date:
        lines.append(f"    Event date: {event.event_date}")
    if not event.items:
        lines.append("    The index lists no item for this filing.")
    for item in event.items:
        known = "" if item.known else " (not in SEC's table of items)"
        lines.append(f"    Item {item.number}. {clean(item.title)} [{item.category}]{known}")
        if event.status == EventStatus.read and not item.found:
            lines.append("        No section headed with this item was found in the document.")
        if item.roles:
            lines.append(f"        Roles named: {', '.join(item.roles)}")
        for sentence in item.opening:
            lines += _wrapped(f'"{sentence}"', "        ")
    return lines


def _status(event: Event) -> str:
    words = policy.EVENT_STATUS_LABELS[event.status.value]
    return f"{words}: {clean(event.reason)}" if event.reason else words


def render_text(record: CompanyEvents) -> str:
    """The timeline as plain text: the as-of line, the counts, then each 8-K newest first."""
    company, as_of = record.company, record.as_of
    lines = [
        f"8-Ks of {clean(company.name)} ({company.ticker}, CIK {company.cik}) "
        f"since its annual report of {as_of.annual_filed or 'unknown date'}",
        "",
        *_wrapped(as_of.line, ""),
        *_wrapped(as_of.counts.line, ""),
    ]
    lines += ["", *_wrapped(policy.EVENTS_NOTE, ""), ""]
    if not record.timeline and not as_of.index_error:
        lines.append(policy.EVENTS_NONE.format(annual=as_of.annual_filed or "unknown date"))
    for event in record.timeline:
        lines += [*_event_lines(event), ""]
    return "\n".join(lines).rstrip("\n") + "\n"


def main(
    argv: list[str] | None = None,
    *,
    source: FilingSource | None = None,
    now: datetime | None = None,
    out_dir: Path = RESULTS_DIR,
) -> int:
    """List and read the 8-Ks of the company named on the command line; print and save them."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("ticker", help="the company's ticker, such as NVDA")
    args = parser.parse_args(argv)
    moment = (now or datetime.now(UTC)).astimezone(UTC)
    try:
        if source is None:
            with EdgarClient.from_env() as client:
                record = _record(args.ticker, client, moment)
        else:
            record = _record(args.ticker, source, moment)
    except UnknownTicker as exc:
        print(f"ticker: {exc}", file=sys.stderr)
        return 2
    except SourceError as exc:
        print(f"SEC EDGAR: {exc}", file=sys.stderr)
        return 1
    text = render_text(record)
    ticker = _UNSAFE_NAME.sub("", record.company.ticker.upper())
    stem = out_dir / f"events-{ticker}-{moment.strftime('%Y%m%dT%H%M%SZ')}"
    out_dir.mkdir(parents=True, exist_ok=True)
    stem.with_name(stem.name + ".txt").write_text(text)
    stem.with_name(stem.name + ".json").write_text(record.model_dump_json(indent=2) + "\n")
    print(text)
    print(f"events: wrote {stem}.txt and .json")
    return 0


def _record(ticker: str, filings: FilingSource, moment: datetime) -> CompanyEvents:
    company = filings.company(ticker)
    timeline, as_of = company_events(company, filings, FilingCache(), today=moment.date())
    return CompanyEvents(company=company, as_of=as_of, timeline=timeline.events)


if __name__ == "__main__":
    sys.exit(main())
