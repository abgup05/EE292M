"""Record types for current reports (8-K): the timeline of events since the annual report.

Pure data: nothing here touches the network or computes a result. The values
are computed by :mod:`app.core.events` and :mod:`app.services.events`, kept on a
run (:class:`app.core.models.Run`) and returned by the API; a view only draws them.
Every field has a default, so a run recorded before version 12 still loads.
"""

from __future__ import annotations

from enum import StrEnum

from pydantic import BaseModel, Field


class EventStatus(StrEnum):
    """What became of one 8-K the index lists.

    ``read``: its primary document was fetched (or read from the cache) and split.
    ``failed``: it was to be read and could not be; ``reason`` says why.
    ``capped``: it was to be read, and the cap on 8-Ks read per run came first.
    ``out_of_time``: it was to be read, and the run's time limit came first.
    ``index_only``: a routine 8-K filed before the newest periodic report the run
    read; it is listed from the index and its document is not read.
    """

    read = "read"
    failed = "failed"
    capped = "capped"
    out_of_time = "out_of_time"
    index_only = "index_only"


class EventItem(BaseModel):
    """One item an 8-K reports, as the index lists it and, once read, as its text says it.

    ``title`` and ``category`` come from SEC's list of Form 8-K items
    (:data:`app.core.events.ITEMS`); ``known`` is False for a number not in that list,
    which is kept with category "other". ``found`` says whether the document had a
    section for the item; ``locator`` is that section's heading, ``opening`` its first
    sentences word for word, and ``roles`` the officer roles an Item 5.02 names.
    """

    number: str
    title: str
    category: str
    known: bool = True
    found: bool = False
    locator: str = ""
    opening: list[str] = Field(default_factory=list)
    roles: list[str] = Field(default_factory=list)


class Event(BaseModel):
    """One 8-K or 8-K/A filed after the annual report: what the index says and what was read.

    ``event_date`` is the index's report date, the day of the event; ``filed_label`` the
    filing date as the page shows it. ``categories`` are those of its items, in the order
    of :class:`app.core.events.Category`; ``substantive`` is True when one of them has a
    claim lexicon. ``after_periodic`` is True when it was filed after the newest periodic
    report the run read. ``source_id`` names the run source made from it when one of its
    sections was offered to a claim; None otherwise.
    """

    id: str
    form: str
    accession: str
    filed_date: str
    event_date: str = ""
    filed_label: str = ""
    url: str
    items: list[EventItem] = Field(default_factory=list)
    categories: list[str] = Field(default_factory=list)
    substantive: bool = False
    after_periodic: bool = False
    status: EventStatus = EventStatus.index_only
    reason: str = ""
    content_hash: str = ""
    source_id: str | None = None


class EventCounts(BaseModel):
    """How many 8-Ks were listed and what became of them; every one is in exactly one count.

    ``listed`` = ``read`` + ``failed`` + ``capped`` + ``out_of_time`` + ``index_only``, and
    ``wanted`` (those the rule says to read) = ``listed`` - ``index_only``. ``line`` says it
    in words.
    """

    listed: int = 0
    wanted: int = 0
    read: int = 0
    failed: int = 0
    capped: int = 0
    out_of_time: int = 0
    index_only: int = 0
    cap: int = 0
    line: str = ""


class AsOf(BaseModel):
    """How old a run's evidence is, and what EDGAR lists after the annual report it read.

    ``newest_*`` is the newest filing read, of any form (a periodic report or an 8-K);
    ``periodic_*`` the newest periodic report read; ``annual_filed`` the filing date of
    the newest annual report read, after which the 8-Ks are listed.
    ``days_since_newest`` is the number of days from the newest filing read to the day
    the run started (to the day the list was made, outside a run). ``index_error`` says
    why the 8-Ks could not be listed; the timeline is then empty and says nothing.
    ``line`` is the one sentence the page and the brief show.
    """

    newest_form: str | None = None
    newest_filed: str | None = None
    newest_url: str = ""
    periodic_form: str | None = None
    periodic_filed: str | None = None
    annual_filed: str | None = None
    days_since_newest: int | None = None
    counts: EventCounts = Field(default_factory=EventCounts)
    index_error: str = ""
    line: str = ""


class Predating(BaseModel):
    """An 8-K filed after every filing a finding cites, on a subject of the finding's claim.

    ``items`` are its item numbers in the claim's categories; ``label`` is the line the
    page and the brief show ("Predates the 8-K of 12 Nov 2026, Item 5.02").
    """

    event_id: str
    filed_date: str
    items: list[str] = Field(default_factory=list)
    label: str = ""
