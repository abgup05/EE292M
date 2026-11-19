"""Model-written retrieval queries for the golden set, obtained as a thesis run obtains them.

The golden cases are grouped by ticker, in file order, into requests of at most
``limits.MAX_CLAIMS`` claims, answerable and unanswerable alike, so the planner
is never told which is which. Each group becomes the
:class:`~app.core.models.ThesisRequest` a run would build (that ticker, the
fixed decision :data:`DECISION`, those claims) and goes to
:meth:`app.engines.claude.ClaudeAnalyst.plan` through a cassette
(:mod:`app.engines.cassette`). A request with no recorded answer is saved as
pending; :func:`run_plan` then reports it and exits 3 without writing anything,
so the command can be run again once the answers are recorded.
"""

from __future__ import annotations

import json
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from ed_v8.core import limits
from ed_v8.core.models import Company, ThesisRequest
from ed_v8.engines.cassette import CassetteMiss, CassetteTransport, request_key
from ed_v8.engines.claude import ClaudeAnalyst
from ed_v8.engines.transport import EngineError, ModelRequest, Transport
from ed_v8.evaluation.golden import GoldenCase

DECISION = "Whether the thesis still holds after the latest filings"
EXIT_PENDING = 3


@dataclass(frozen=True)
class PlanGroup:
    """One plan request: up to ``MAX_CLAIMS`` cases of one ticker, in file order."""

    ticker: str
    case_ids: tuple[str, ...]
    claims: tuple[str, ...]

    def request(self) -> ThesisRequest:
        """The thesis request a run would build for these claims."""
        return ThesisRequest(ticker=self.ticker, decision=DECISION, claims=list(self.claims))


def group_cases(cases: Sequence[GoldenCase], size: int = limits.MAX_CLAIMS) -> list[PlanGroup]:
    """Every case, grouped by ticker (in order of first appearance), ``size`` at most per group."""
    by_ticker: dict[str, list[GoldenCase]] = {}
    for case in cases:
        by_ticker.setdefault(case.ticker, []).append(case)
    groups: list[PlanGroup] = []
    for ticker, members in by_ticker.items():
        for first in range(0, len(members), size):
            chunk = members[first : first + size]
            groups.append(
                PlanGroup(ticker, tuple(c.id for c in chunk), tuple(c.claim for c in chunk))
            )
    return groups


class KeyRecorder:
    """A transport wrapper that notes the cassette key of every request it passes on."""

    def __init__(self, inner: Transport) -> None:
        """Pass requests to ``inner``."""
        self.inner = inner
        self.keys: list[str] = []

    @property
    def detail(self) -> str:
        """The wrapped transport's description, if it has one."""
        return str(getattr(self.inner, "detail", "") or "")

    def __call__(self, request: ModelRequest) -> dict[str, Any]:
        """Note the request's key, then answer it through the wrapped transport."""
        self.keys.append(request_key(request))
        return self.inner(request)


@dataclass
class GroupStatus:
    """What happened to one plan request: answered, pending, or failed (with why)."""

    group: PlanGroup
    key: str
    status: str  # "answered", "pending" or "failed"
    message: str = ""


@dataclass
class PlanOutcome:
    """Every group's status and, for answered groups, each case's queries."""

    statuses: list[GroupStatus] = field(default_factory=list)
    queries: dict[str, list[str]] = field(default_factory=dict)

    def count(self, status: str) -> int:
        """How many groups have ``status``."""
        return sum(1 for s in self.statuses if s.status == status)


def plan_groups(
    groups: Sequence[PlanGroup], companies: Mapping[str, Company], transport: Transport
) -> PlanOutcome:
    """Ask the planner for every group; a missing answer is pending, a malformed one failed."""
    recorder = KeyRecorder(transport)
    analyst = ClaudeAnalyst(transport=recorder)
    outcome = PlanOutcome()
    for group in groups:
        asked = len(recorder.keys)
        try:
            planned = analyst.plan(group.request(), companies[group.ticker])
        except CassetteMiss as exc:
            outcome.statuses.append(GroupStatus(group, _key(recorder, asked), "pending", str(exc)))
            continue
        except EngineError as exc:
            outcome.statuses.append(GroupStatus(group, _key(recorder, asked), "failed", str(exc)))
            continue
        outcome.statuses.append(GroupStatus(group, _key(recorder, asked), "answered"))
        outcome.queries.update(zip(group.case_ids, planned, strict=True))
    return outcome


def _key(recorder: KeyRecorder, asked: int) -> str:
    return recorder.keys[-1] if len(recorder.keys) > asked else ""


def queries_document(
    outcome: PlanOutcome,
    case_order: Sequence[str],
    *,
    description: str,
    cassette: str,
    inputs: Mapping[str, Any],
    when: datetime,
) -> dict[str, Any]:
    """The queries file: provenance first, then each case's queries in golden-set order."""
    return {
        "provenance": {
            "kind": "planned-queries",
            "planned_at": when.isoformat(timespec="seconds"),
            "cassette": cassette,
            "cassette_description": description,
            "decision": DECISION,
            "max_claims_per_request": limits.MAX_CLAIMS,
            **inputs,
            "requests": [
                {"ticker": s.group.ticker, "case_ids": list(s.group.case_ids), "key": s.key}
                for s in outcome.statuses
            ],
        },
        "queries": {case_id: outcome.queries[case_id] for case_id in case_order},
    }


def render_statuses(outcome: PlanOutcome) -> str:
    """One line per plan request: ticker, cases, cassette key and status."""
    lines = []
    for number, status in enumerate(outcome.statuses, start=1):
        line = (
            f"plan: request {number} {status.group.ticker} ({len(status.group.case_ids)} claims) "
            f"key {status.key or '-'}: {status.status}"
        )
        if status.status == "failed":
            line += f" ({status.message})"
        lines.append(line)
    return "\n".join(lines)


def run_plan(
    cases: Sequence[GoldenCase],
    companies: Mapping[str, Company],
    cassette: Path,
    out: Path,
    *,
    inputs: Mapping[str, Any],
    now: datetime | None = None,
) -> int:
    """Plan every case through ``cassette``; write ``out`` only when every request is answered.

    Returns 0 when written, 3 while requests are pending (none failed), 1 when
    a recorded answer could not be used (delete it and answer it again).
    """
    transport = CassetteTransport(cassette)
    groups = group_cases(cases)
    outcome = plan_groups(groups, companies, transport)
    print(render_statuses(outcome))
    pending, failed = outcome.count("pending"), outcome.count("failed")
    if failed:
        print(
            f"plan: {failed} of {len(groups)} plan request(s) have an unusable recorded answer; "
            f"delete those responses/<key>.json and answer them again. Nothing was written."
        )
        return 1
    if pending:
        print(
            f"plan: {pending} of {len(groups)} plan request(s) pending in {cassette}/pending. "
            "Answer them (docs/cassettes.md) and run again. Nothing was written."
        )
        return EXIT_PENDING
    document = queries_document(
        outcome,
        [case.id for case in cases],
        description=transport.detail,
        cassette=str(cassette),
        inputs=inputs,
        when=now or datetime.now(UTC),
    )
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(document, indent=2, ensure_ascii=False) + "\n")
    print(f"plan: all {len(groups)} plan request(s) answered; wrote {out}")
    return 0
