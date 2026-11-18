"""HTTP routes of the standing watch, added to the app by :func:`add_routes`.

Validated like the neighbouring routes: a body is a strict schema (an unknown field is
refused), ids in a path have a fixed shape, paging is bounded; a refusal is 422
``{"error", "details": [{"field", "message"}]}`` through the app's own handler. 404 for
an unknown thesis or inbox item, as ``{"error"}`` like every refusal of the app; 409 for a
valid request the state forbids (a run that
is not waiting, a thesis not watched); 503 when EDGAR cannot be read to start a watch.

    PUT    /api/theses/{id}/watch     {"policy": "ask" | "auto"}: watch (201) or change policy (200)
    DELETE /api/theses/{id}/watch     take it off watch
    GET    /api/watch                 every watch: policy, last and next check, last error
    GET    /api/watch/health          is a watcher alive, its last cycle, the queue
    GET    /api/watch/meta            the labels and numbers the page draws with
    GET    /api/inbox                 unread first, newest first; ?limit=&offset=&thesis_id=
    GET    /api/inbox/{id}            one item
    POST   /api/inbox/read            {"ids": [...], "read": true | false}
    POST   /api/inbox/{id}/run        start the run an item holds waiting (202)
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from datetime import datetime
from typing import Annotated, Any

from fastapi import FastAPI, HTTPException, Path, Query, Request, Response
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict, Field

from ed_v14 import wiring
from ed_v14.core import watch_policy as wording
from ed_v14.core.models import Run
from ed_v14.core.ports import FilingSource, UnknownTicker
from ed_v14.core.watch_models import InboxItem, WatchPolicy
from ed_v14.services import theses
from ed_v14.store import FilingCache, Store
from ed_v14.watch.service import (
    NotWaiting,
    UnknownItem,
    WatchedSource,
    WatchSettings,
    finish_inbox_run,
    start_waiting_run,
    start_watching,
    stop_watching,
)
from ed_v14.watch.store import WatchStatus, WatchStore
from ed_v14.watch.views import WatcherHealth, WatchList, WatchSummary, health, watch_list

log = logging.getLogger(__name__)

THESIS_ID = r"^[A-Za-z0-9-]{1,64}$"
ITEM_ID = r"^ib-[A-Za-z0-9-]{1,160}$"
NOT_WATCHED = "This thesis is not watched."
NOT_WAITING = "This inbox item holds no run waiting to be started."
TICKER_GONE = "The thesis's ticker is no longer in SEC's company list: {reason}"

ThesisId = Annotated[str, Path(pattern=THESIS_ID)]
ItemId = Annotated[str, Path(pattern=ITEM_ID)]


class WatchConflict(Exception):
    """A valid request the watch's state forbids (409)."""


class WatchRequest(BaseModel):
    """What a client sends to watch a thesis: its policy (``ask`` unless it says ``auto``)."""

    model_config = ConfigDict(extra="forbid")

    policy: WatchPolicy = wording.DEFAULT_POLICY


class WatchChanged(BaseModel):
    """A thesis put on watch (``created``) or its policy changed."""

    created: bool
    watch: WatchSummary


class Unwatched(BaseModel):
    """A thesis taken off watch; its inbox and jobs stay."""

    thesis_id: str
    watching: bool = False


class InboxList(BaseModel):
    """One page of the inbox: unread first, then newest first.

    ``total`` and ``unread`` count the whole inbox (of one thesis when asked), and so
    does ``folded``: the items of the kinds a listing folds (``collapsed_kinds`` in the
    meta: seen, not relevant), whichever page is drawn. ``next_offset`` is the offset of
    the next page, None on the last.
    """

    items: list[InboxItem]
    total: int
    unread: int
    folded: int = 0
    limit: int
    offset: int
    next_offset: int | None = None


class MarkRead(BaseModel):
    """Inbox items to mark read (or unread, with ``read`` false)."""

    model_config = ConfigDict(extra="forbid")

    ids: list[Annotated[str, Field(pattern=ITEM_ID)]] = Field(
        min_length=1, max_length=wording.MAX_MARK_READ
    )
    read: bool = Field(default=True, strict=True)


class Marked(BaseModel):
    """Which items were marked, which ids no item has, and how many are left unread."""

    marked: list[str]
    unknown: list[str]
    unread: int


class WaitingRunStarted(BaseModel):
    """The run started from an inbox item, in the background like any run."""

    id: str
    status: str
    item_id: str


def meta() -> dict[str, Any]:
    """Every label and number the page draws the watch with."""
    return {
        "kind_labels": {kind.value: label for kind, label in wording.KIND_LABELS.items()},
        "collapsed_kinds": [kind.value for kind in wording.COLLAPSED_KINDS],
        "policy_labels": {p.value: label for p, label in wording.POLICY_LABELS.items()},
        "default_policy": wording.DEFAULT_POLICY.value,
        "job_state_labels": {s.value: label for s, label in wording.JOB_STATE_LABELS.items()},
        "rule_labels": {r.value: label for r, label in wording.RULE_LABELS.items()},
        "forms": list(wording.WATCH_FORMS),
        "limits": {
            "min_interval_seconds": wording.MIN_INTERVAL_SECONDS,
            "default_interval_seconds": wording.DEFAULT_INTERVAL_SECONDS,
            "default_auto_runs_per_day": wording.DEFAULT_AUTO_RUNS_PER_DAY,
            "max_attempts": wording.MAX_ATTEMPTS,
            "backoff_seconds": list(wording.BACKOFF_SECONDS),
            "lease_seconds": wording.LEASE_SECONDS,
            "paragraphs_per_claim": wording.PARAGRAPHS_PER_CLAIM,
            "default_page_size": wording.DEFAULT_PAGE_SIZE,
            "max_page_size": wording.MAX_PAGE_SIZE,
        },
    }


def add_routes(
    app: FastAPI,
    *,
    store: Store,
    cache: FilingCache,
    filings: FilingSource,
    execute: Callable[[Run], None],
    background: Callable[[Callable[[], None]], object],
    now: Callable[[], datetime],
    settings: WatchSettings | None = None,
) -> None:
    """Add the watch's routes to ``app``.

    ``execute`` runs a started run to its end (the app's own worker function) and
    ``background`` hands it a function to run off the request thread (its executor's
    ``submit``). ``now`` is the wall clock; ``settings`` default to the environment's.
    """
    watches = WatchStore(store)
    status = WatchStatus(cache)
    source: WatchedSource = filings  # type: ignore[assignment]  # EdgarClient lists forms too
    interval = (settings or wiring.watch_settings_from_env()).interval_seconds

    @app.exception_handler(WatchConflict)
    async def conflict(_: Request, exc: WatchConflict) -> JSONResponse:
        return JSONResponse(status_code=409, content={"error": str(exc)})

    def summary(thesis_id: str) -> WatchSummary:
        listed = watch_list(store, watches, status, interval).watches
        return next(row for row in listed if row.thesis_id == thesis_id)

    @app.put("/api/theses/{thesis_id}/watch")
    def watch_thesis(thesis_id: ThesisId, body: WatchRequest, response: Response) -> WatchChanged:
        """Put a saved thesis on watch, or change its policy.

        On first watching, the filings EDGAR lists now are marked seen: the watch reports
        what is new from then on. 201 when the watch is new, 200 when only its policy
        changed; 404 for an unknown thesis; 503 when EDGAR cannot be read (nothing saved).
        """
        try:
            _, created = start_watching(store, watches, source, thesis_id, body.policy, now())
        except theses.UnknownThesis as exc:
            raise HTTPException(status_code=404, detail="Thesis not found") from exc
        except UnknownTicker as exc:
            raise WatchConflict(TICKER_GONE.format(reason=exc)) from exc
        response.status_code = 201 if created else 200
        return WatchChanged(created=created, watch=summary(thesis_id))

    @app.delete("/api/theses/{thesis_id}/watch")
    def unwatch_thesis(thesis_id: ThesisId) -> Unwatched:
        """Take a thesis off watch; its inbox and jobs stay. 404 unknown thesis; 409 not watched."""
        if store.get_thesis(thesis_id) is None:
            raise HTTPException(status_code=404, detail="Thesis not found")
        if not stop_watching(watches, thesis_id):
            raise WatchConflict(NOT_WATCHED)
        return Unwatched(thesis_id=thesis_id)

    @app.get("/api/watch")
    def list_watches() -> WatchList:
        """Every watch, oldest first: its policy, last and next check, last error, jobs, inbox."""
        return watch_list(store, watches, status, interval)

    @app.get("/api/watch/health")
    def watcher_health() -> WatcherHealth:
        """Whether a watcher is alive (its heartbeat), its last cycle, and the queue depth."""
        return health(watches, status, now(), interval)

    @app.get("/api/watch/meta")
    def watch_meta() -> dict[str, Any]:
        """The labels and numbers of the watch, so the page computes none."""
        return meta()

    @app.get("/api/inbox")
    def list_inbox(
        limit: Annotated[int, Query(ge=1, le=wording.MAX_PAGE_SIZE)] = wording.DEFAULT_PAGE_SIZE,
        offset: Annotated[int, Query(ge=0)] = 0,
        thesis_id: Annotated[str | None, Query(pattern=THESIS_ID)] = None,
    ) -> InboxList:
        """One page of the inbox, unread first, then newest first."""
        page = watches.list_items(limit=limit, offset=offset, thesis_id=thesis_id)
        following = offset + len(page.items)
        return InboxList(
            items=page.items,
            total=page.total,
            unread=page.unread,
            folded=page.folded,
            limit=limit,
            offset=offset,
            next_offset=following if following < page.total else None,
        )

    @app.get("/api/inbox/{item_id}")
    def get_inbox_item(item_id: ItemId) -> InboxItem:
        """One inbox item; 404 for an unknown id."""
        item = watches.get_item(item_id)
        if item is None:
            raise HTTPException(status_code=404, detail="Inbox item not found")
        return item

    @app.post("/api/inbox/read")
    def mark_read(body: MarkRead) -> Marked:
        """Mark items read (or unread); ids no item has are listed, not an error."""
        marked = watches.mark_read(body.ids, now(), read=body.read)
        unknown = sorted(set(body.ids) - set(marked))
        return Marked(
            marked=marked,
            unknown=unknown,
            unread=watches.list_items(limit=1, offset=0).unread,
        )

    @app.post("/api/inbox/{item_id}/run", status_code=202)
    def start_waiting(item_id: ItemId) -> WaitingRunStarted:
        """Start the run an inbox item holds waiting; when it ends, the item says what moved.

        404 for an unknown item or a thesis that no longer exists; 409 when no run waits
        (it was never needed, or it has started already).
        """
        try:
            run = start_waiting_run(store, watches, item_id, now())
        except UnknownItem as exc:
            raise HTTPException(status_code=404, detail="Inbox item not found") from exc
        except theses.UnknownThesis as exc:
            raise HTTPException(status_code=404, detail="Thesis not found") from exc
        except NotWaiting as exc:
            raise WatchConflict(NOT_WAITING) from exc

        def run_and_report() -> None:
            execute(run)
            finished = store.get_run(run.id) or run
            try:
                finish_inbox_run(store, watches, item_id, finished, now())
            except Exception:  # noqa: BLE001 - logged; the item stays "running" with the run's id
                log.exception("Writing the outcome of run %s into %s failed", run.id, item_id)

        background(run_and_report)
        return WaitingRunStarted(id=run.id, status=run.status, item_id=item_id)
