"""Run each engine step on a primary engine and fall back to a second one if it fails.

Every fallback is reported through ``on_failure`` so the run can record it and
mark itself partial; a failure is never hidden. If the fallback engine fails
too, its exception propagates.
"""

from __future__ import annotations

from collections.abc import Callable, Sequence

from ed_v7.core.documents import Passage
from ed_v7.core.metric_models import Metric
from ed_v7.core.models import Claim, Company, Finding, ThesisRequest
from ed_v7.core.ports import Analyst, ClaimDraft, SummaryDraft


class FallbackAnalyst:
    """An :class:`~app.core.ports.Analyst` answering with ``fallback`` when ``primary`` raises."""

    def __init__(
        self,
        primary: Analyst,
        fallback: Analyst,
        on_failure: Callable[[str, Exception], None],
    ) -> None:
        self.primary = primary
        self.fallback = fallback
        self.on_failure = on_failure
        self.name = primary.name

    @property
    def detail(self) -> str:
        """The primary engine's account of how it answers; fallbacks are reported per step."""
        return str(getattr(self.primary, "detail", ""))

    def plan(self, request: ThesisRequest, company: Company) -> list[list[str]]:
        """The primary's queries, or the fallback's after reporting step ``"plan"``."""
        try:
            return self.primary.plan(request, company)
        except Exception as exc:
            self.on_failure("plan", exc)
            return self.fallback.plan(request, company)

    def assess(
        self,
        request: ThesisRequest,
        company: Company,
        claim: Claim,
        passages: list[Passage],
        figures: Sequence[Metric] = (),
    ) -> ClaimDraft:
        """The primary's draft, or the fallback's after reporting step ``"assess"``.

        ``figures`` reach both engines; when there are none the argument is left
        out, so an engine written before figures existed is called as it was.
        """
        extra = {"figures": figures} if figures else {}
        try:
            return self.primary.assess(request, company, claim, passages, **extra)
        except Exception as exc:
            self.on_failure("assess", exc)
            return self.fallback.assess(request, company, claim, passages, **extra)

    def summarize(
        self,
        request: ThesisRequest,
        company: Company,
        claims: list[Claim],
        findings: list[Finding],
    ) -> SummaryDraft:
        """The primary's summary, or the fallback's after reporting step ``"summarize"``."""
        try:
            return self.primary.summarize(request, company, claims, findings)
        except Exception as exc:
            self.on_failure("summarize", exc)
            return self.fallback.summarize(request, company, claims, findings)
