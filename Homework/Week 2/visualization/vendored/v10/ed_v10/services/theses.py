"""Saved theses: a named thesis request that can be run again and compared.

A thesis holds the request and the ids of its runs, newest first. Each run is
an ordinary run record carrying the thesis id; :func:`latest_comparison` says
what moved between the two newest runs that finished.
"""

from __future__ import annotations

import threading
import uuid
from datetime import UTC, datetime

from ed_v10.core.compare import compare_runs
from ed_v10.core.models import Run, RunComparison, RunStatus, Thesis, ThesisCreate
from ed_v10.core.review import build_review
from ed_v10.services import thesis_run
from ed_v10.store import Store

NOT_ENOUGH_RUNS = "This thesis has fewer than two finished runs to compare."
# A run that finished with a brief; a failed run has no verdicts to compare.
FINISHED = (RunStatus.complete, RunStatus.partial)
# Serialises the read-modify-write of a thesis's run ids within this process.
_thesis_lock = threading.Lock()


class UnknownThesis(LookupError):
    """No saved thesis has the id asked for."""


class NotEnoughRuns(Exception):
    """The thesis has fewer than two finished runs, so there is nothing to compare."""


def create_thesis(store: Store, body: ThesisCreate) -> Thesis:
    """Save ``body`` as a new thesis with a fresh id and the current UTC time."""
    thesis = Thesis(
        id=f"th-{uuid.uuid4().hex[:12]}",
        name=body.name,
        request=body.request,
        created_at=datetime.now(UTC),
    )
    store.save_thesis(thesis)
    return thesis


def start_thesis_run(store: Store, thesis_id: str) -> Run:
    """Create and save a running run of the thesis, and put its id first in ``run_ids``.

    The caller executes the run. Raises :class:`UnknownThesis` for an unknown id.
    """
    with _thesis_lock:
        thesis = store.get_thesis(thesis_id)
        if thesis is None:
            raise UnknownThesis(thesis_id)
        run = thesis_run.new_run(thesis.request, thesis_id=thesis.id)
        store.save_run(run)
        thesis.run_ids.insert(0, run.id)
        store.save_thesis(thesis)
    return run


def latest_comparison(store: Store, thesis_id: str) -> RunComparison:
    """What moved between the two newest finished runs of the thesis, with their reviews.

    Raises :class:`UnknownThesis` for an unknown id and :class:`NotEnoughRuns`
    when fewer than two runs have finished as complete or partial.
    """
    if store.get_thesis(thesis_id) is None:
        raise UnknownThesis(thesis_id)
    finished = [run for run in store.runs_of_thesis(thesis_id) if run.status in FINISHED]
    if len(finished) < 2:
        raise NotEnoughRuns(NOT_ENOUGH_RUNS)
    later, earlier = finished[0], finished[1]
    return compare_runs(
        earlier,
        later,
        build_review(earlier, store.list_decisions(earlier.id)),
        build_review(later, store.list_decisions(later.id)),
    )
