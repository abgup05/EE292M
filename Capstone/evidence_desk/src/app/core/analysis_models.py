"""Record types for a run's analysis: relevance, analytics, corollaries, odds and the argument.

Pure data. :mod:`app.services.analysis` computes them after the verdicts are final;
:mod:`app.core.analytics`, :mod:`app.core.persistence`, :mod:`app.core.corollaries` and
:mod:`app.core.relevance` do the arithmetic, :mod:`app.engines.analyser` asks a model for
the argument and :mod:`app.core.analysis_audit` checks every sentence it writes. A view
only draws these records. ``docs/analysis.md`` names every field.

Who wrote what is on the record: an :class:`Analytic` and its ``reading`` are always
written by code; a :class:`Corollary` is proposed by a model and computed by code; an
:class:`ArgSentence` is written by a model and audited by code. Every field has a
default, so a run recorded before version 0.14.2 loads with none of them.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

from app.core.claim_test_models import ComputedTest

AnalyticUnit = Literal[
    "USD",
    "USD_per_share",
    "percent",
    "points",
    "multiple",
    "days",
    "count",
    "probability",
    "shares",
]
RefKind = Literal["metric", "fact", "analytic", "computed_test", "external"]


class AnalyticInput(BaseModel):
    """One input an analytic used: a run metric, a reported fact, another analytic, a
    computed test, or (for a provider outside the run's facts) an external record.

    ``id`` is the input's id in the run (a metric id, an analytic id, ``test:c2``) or, for
    a fact, its concept and period. ``accession``, ``form`` and ``filed`` name the filing
    a fact came from; empty for an input that is not one fact.
    """

    ref_kind: RefKind
    id: str
    label: str
    value: float | None = None
    display: str = ""
    accession: str = ""
    form: str = ""
    filed: str = ""


class Analytic(BaseModel):
    """One number an analyst would work out, computed by code, with its arithmetic.

    ``id`` is stable across runs of the same thesis ("an:revenue:yoy", "an:c2:headroom",
    "an:eq:cash_conversion"). ``provider`` names the code that computed it (this version:
    "facts"); ``data_origin`` what it was computed from ("sec_xbrl_facts" for the run's
    dated XBRL facts, "sec_tagged_breakdowns" for a filing's own tags; later providers add
    their own). ``kind`` says what sort of analytic it is ("level", "yoy", "trend4",
    "headroom", "bridge", "earnings_quality", ...). ``claim_ids`` are the claims it bears
    on (empty: it bears on the thesis as a whole). ``measure`` is the catalogue key it is
    about, ``period`` the period in words. ``value`` is unrounded in ``unit`` (a percent as
    12.5; ``points`` are percentage points; ``probability`` is a percent of paths), None
    when it could not be computed, and then ``available`` is False and ``note`` says why.
    ``reading`` is one plain sentence written from a template, never by a model
    (``reading_origin`` is always "code").
    """

    id: str
    provider: str = "facts"
    data_origin: str = "sec_xbrl_facts"
    kind: str
    label: str
    claim_ids: list[str] = Field(default_factory=list)
    measure: str = ""
    period: str = ""
    value: float | None = None
    unit: AnalyticUnit = "USD"
    display: str = "n/a"
    formula: str = ""
    inputs: list[AnalyticInput] = Field(default_factory=list)
    reading: str = ""
    reading_origin: Literal["code"] = "code"
    available: bool = True
    note: str = ""


class RelevantMeasure(BaseModel):
    """A measure that bears on a claim, and why code decided it does.

    ``key`` is a catalogue key ("gross_margin") or a part ('revenue(segment "Data
    Center")'). ``reasons`` are one or more of "test operand", "cited by a finding",
    "named in the claim" and "part named in the claim". ``metric_ids`` are the run's
    reported figures of that measure (newest quarter and fiscal year), when it has any;
    ``analytic_ids`` the analytics about it.
    """

    key: str
    label: str
    reasons: list[str] = Field(default_factory=list)
    metric_ids: list[str] = Field(default_factory=list)
    analytic_ids: list[str] = Field(default_factory=list)


class HeadlineFigure(BaseModel):
    """One figure of the thesis's headline, drawn from what its claims bear on.

    ``source`` says whether ``id`` is a run metric or an analytic; ``claim_ids`` the
    claims it is relevant to, in claim order.
    """

    id: str
    source: Literal["metric", "analytic"]
    label: str
    period_label: str = ""
    value: float | None = None
    unit: str = ""
    display: str = ""
    claim_ids: list[str] = Field(default_factory=list)


CorollaryStatus = Literal[
    "agreed", "grammar_only", "proposer_only", "not_agreed", "not_computable"
]
CorollaryResult = Literal["as_expected", "against", "cannot_tell", "not_computed"]


class Corollary(BaseModel):
    """An observable implication of a claim: proposed by a model, compiled and computed by code.

    ``sentence`` is the implication in the claim-test language; ``expect`` the outcome it
    should have if the claim holds; ``why`` the proposer's one-line reason. ``grammar``
    and ``proposer`` are each reader's canonical test ("none" for no test) with
    ``grammar_reason`` / ``proposer_reason`` saying why not. ``status``: "agreed" (both
    read the same test), "grammar_only", "proposer_only" (the proposing model's typed form
    alone, labelled so), "not_agreed" (both read a test and they differ: the grammar's is
    computed and shown, and it is not counted as agreed) or "not_computable".
    ``read_by`` says it in words. ``computed`` is the test computed from the run's facts
    with its history; ``result`` compares its outcome with ``expect``. A corollary never
    moves a verdict (``docs/analysis.md``).
    """

    id: str
    claim_id: str
    sentence: str
    expect: Literal["holds", "fails"]
    why: str = ""
    grammar: str = "none"
    grammar_reason: str = ""
    proposer: str = "none"
    proposer_reason: str = ""
    status: CorollaryStatus = "not_computable"
    read_by: str = ""
    computed: ComputedTest | None = None
    result: CorollaryResult = "not_computed"
    result_label: str = ""


class Persistence(BaseModel):
    """How likely a claim's computed test is to still hold over the next quarters, by resampling.

    ``applicable`` is False with ``note`` saying why (no computed test, not a test on a
    quarterly measure against a constant). ``method`` writes the method out; ``changes``
    is how many historical quarterly changes were resampled (the sample size), ``paths``
    and ``seed`` make it repeatable, ``horizon`` is the number of quarters ahead.
    ``probability`` is the percent of paths in which the test holds in every one of those
    quarters (None with ``warning`` when the history is too short to mean anything).
    """

    id: str
    claim_id: str
    applicable: bool = False
    test: str = ""
    method: str = ""
    step: Literal["points", "relative", ""] = ""
    changes: int = 0
    paths: int = 0
    seed: int = 0
    horizon: int = 0
    start_value: float | None = None
    start_display: str = ""
    probability: float | None = None
    display: str = ""
    warning: str = ""
    note: str = ""


class ArgSentence(BaseModel):
    """One sentence of the argued analysis: written by a model, audited by code.

    ``cites`` are the ids it rests on (findings, analytics, metrics, computed tests,
    corollaries, odds, 8-K events; claim ids may be named but are not evidence).
    ``verified`` is True when every cited id is in this run and of an allowed kind, at
    least one is evidence, and every number the sentence writes is a value of something it
    cites; otherwise ``problems`` says why, one reason each. An unverified sentence is
    kept and marked, never removed.
    """

    text: str
    cites: list[str] = Field(default_factory=list)
    verified: bool = False
    problems: list[str] = Field(default_factory=list)


class Condition(ArgSentence):
    """What would change a verdict, as an observable condition.

    ``measure`` is a catalogue key ("" when the condition is an event or not a measure),
    with ``comparison`` (">", "<", ">=", "<=", or "none") and ``threshold`` in ``unit``
    ("percent", "USD" or "none"); ``event_category`` an 8-K category ("" for none).
    A measure or a category the catalogue does not know is cleared, and a problem says so.
    """

    measure: str = ""
    comparison: str = "none"
    threshold: float = 0.0
    unit: str = "none"
    event_category: str = ""


Lean = Literal["supports", "challenges", "mixed", "unclear"]


class ClaimArgument(BaseModel):
    """The model's argument about one claim, every sentence audited.

    ``lean`` is where the model reads the evidence as leaning; ``lean_flag`` is set by code
    when it contradicts the claim's verdict (the verdict is never changed). ``assessment``
    says whether the premise is true and whether the step from the claim to the decision
    is backed by anything in the record; then the case for, the case against, what decides
    it, and what would change the verdict.
    """

    claim_id: str
    lean: Lean = "unclear"
    lean_flag: str = ""
    assessment: list[ArgSentence] = Field(default_factory=list)
    case_for: list[ArgSentence] = Field(default_factory=list)
    case_against: list[ArgSentence] = Field(default_factory=list)
    decides: list[ArgSentence] = Field(default_factory=list)
    would_change: list[Condition] = Field(default_factory=list)


class Scenario(BaseModel):
    """A scenario stated as observable conditions (never a price target or advice)."""

    name: str
    conditions: list[ArgSentence] = Field(default_factory=list)


class ThesisArgument(BaseModel):
    """The model's argument about the thesis as a whole, every sentence audited.

    ``leans_on`` are the claim ids the thesis rests on, ``weakest_link`` the one it is
    weakest at (a claim id; "" when the model named none it could), with ``weakest_why``.
    """

    leans_on: list[str] = Field(default_factory=list)
    weakest_link: str = ""
    weakest_why: list[ArgSentence] = Field(default_factory=list)
    strongest_for: list[ArgSentence] = Field(default_factory=list)
    strongest_against: list[ArgSentence] = Field(default_factory=list)
    bottom_line: list[ArgSentence] = Field(default_factory=list)
    scenarios: list[Scenario] = Field(default_factory=list)


class ClaimAnalysis(BaseModel):
    """What the analysis holds for one claim (``Claim.analysis``).

    ``relevant`` are the measures that bear on it; ``relevance_note`` says plainly when
    there are none. ``analytic_ids`` are the analytics tied to it (in ``Run.analysis``).
    ``corollaries`` its implications and ``corollary_flag`` a visible note when most of
    those computed came out against the claim. ``persistence`` the resampled odds that its
    test still holds. ``argument`` the model's audited argument, None when no model wrote
    one (``Run.analysis.argument_note`` says why).
    """

    relevant: list[RelevantMeasure] = Field(default_factory=list)
    relevance_note: str = ""
    analytic_ids: list[str] = Field(default_factory=list)
    corollaries: list[Corollary] = Field(default_factory=list)
    corollary_flag: str = ""
    persistence: Persistence | None = None
    argument: ClaimArgument | None = None


class Analysis(BaseModel):
    """The run-level analysis (``Run.analysis``).

    ``headline`` is the ordered list of figures the page's headline is drawn from: those
    the claims bear on, in claim order (``headline_note`` says why it is empty when no
    claim names a measure). ``untied_metric_ids`` are the run's reported figures that no
    claim is tied to (they stay in ``Run.metrics``). ``analytics`` every analytic of the
    run, from every provider in ``providers``.

    Who wrote what: ``analytics_by`` is always "code". ``corollaries_by`` is the proposing
    model ("" when none was asked; ``corollaries_note`` says why) and ``corollary_rule``
    says what a corollary counts for. ``argument_by`` is "model" when a model's argument
    was recorded, "none" otherwise, with ``argument_detail`` (the model and the API, or the
    cassette it was replayed from) and ``argument_note`` (why there is none).
    ``flags`` are the lean flags and corollary flags in one list, for a reader in a hurry.
    """

    headline: list[HeadlineFigure] = Field(default_factory=list)
    headline_note: str = ""
    untied_metric_ids: list[str] = Field(default_factory=list)
    untied_note: str = ""
    analytics: list[Analytic] = Field(default_factory=list)
    providers: list[str] = Field(default_factory=list)
    analytics_by: Literal["code"] = "code"
    corollaries_by: str = ""
    corollaries_note: str = ""
    corollary_rule: str = ""
    persistence_method: str = ""
    argument_by: Literal["model", "none"] = "none"
    argument_detail: str = ""
    argument_note: str = ""
    thesis: ThesisArgument | None = None
    flags: list[str] = Field(default_factory=list)
