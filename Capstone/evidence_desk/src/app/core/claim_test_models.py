"""Record types for a claim computed from dated facts: the test, its operands and its history.

Pure data. :mod:`app.core.claim_eval` computes a :class:`ComputedTest` from a
compiled claim (:mod:`app.core.claimtest`) and one company's
:class:`~app.core.facts.FactBook`; a run keeps it on the claim
(``Claim.computed``) and a view only draws it.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

from app.core.metric_models import FactRef

ComputedOutcome = Literal["holds", "fails", "cannot_compute"]
OperandUnit = Literal["USD", "percent", "USD_per_share", "count", "shares"]


class Operand(BaseModel):
    """One number a test read or computed, with the facts and arithmetic behind it.

    ``term`` is the bound term ("gross_margin[Q2 FY2027]"); ``label`` says what and
    which period in words ("Gross margin, quarter ended 2026-07-26"). ``value`` is
    unrounded (a percent as 72.4) and None when it cannot be computed, with ``note``
    saying why. ``formula`` writes the arithmetic out with the numbers used; it is empty
    for a value read from one fact. ``inputs`` are the facts, each with its filing's
    accession, form and filing date.
    """

    term: str
    label: str
    value: float | None
    unit: OperandUnit
    display: str
    formula: str = ""
    inputs: list[FactRef] = Field(default_factory=list)
    note: str = ""


class HistoryPoint(BaseModel):
    """The test as of one periodic report's filing date, from the facts filed by then.

    ``filed``, ``form`` and ``accession`` name the 10-K or 10-Q whose filing date the
    point is as of. ``left`` and ``right`` are the two sides compared, as values and
    as text; ``bound`` is the test with that day's periods. ``flipped`` is True when
    the outcome differs from the last point that could be computed before it.
    """

    filed: str
    form: str
    accession: str
    outcome: ComputedOutcome
    bound: str = ""
    left: float | None = None
    left_display: str = ""
    right: float | None = None
    right_display: str = ""
    flipped: bool = False
    reason: str = ""


class ClaimReading(BaseModel):
    """One reader's reading of a claim: the canonical test, or ``none`` and why.

    ``reader`` is "grammar" (:mod:`app.core.claimtest`), "model" or "model_2" (the
    model readers, :mod:`app.engines.claim_reader`); ``reason`` says why it read no test.
    ``normal_form`` is the test in the form the counting rule compares
    (:func:`app.core.claim_normal.normal_form`), "none" for no test; empty before the
    counting rule compared normal forms.
    """

    reader: Literal["grammar", "model", "model_2"]
    canonical: str
    reason: str = ""
    normal_form: str = ""


class ComputedTest(BaseModel):
    """A compiled claim evaluated against one company's facts.

    ``canonical`` is the test as compiled, with unbound periods; ``bound`` the same
    test with the periods it was computed for. ``outcome`` is "holds", "fails" or
    "cannot_compute", with ``reason`` saying why it could not be computed.
    ``left`` and ``right`` are the two sides compared; ``right`` is a constant for a
    threshold. ``operands`` are every measure value read to get them. ``arithmetic``
    writes the computation out line by line; ``margin`` is left minus right in the
    sides' unit (points for percents), with ``margin_display``. ``counted_as`` is the
    stance the verdict rule counts ("supports" when it holds, "challenges" when it
    fails, "" when it could not be computed). ``as_of`` is the date the facts were
    read up to ("" for every fact). ``history`` is the outcome as of each 10-K and
    10-Q filing date of the last years, oldest first; ``history_note`` says what it
    covers or why there is none. ``read_by`` names the readers whose reading this test
    is ("grammar", and "model" when the model parser read the same test); empty before
    version 14. ``agreement`` is the counting rule's conclusion
    (:data:`app.core.policy.AGREEMENT_LABELS`, with ``agreement_label`` in words) and
    ``dissent`` the readings of a different test by a reader outside the agreement;
    both empty before the counting rule had several readers. ``combines`` is "each" for a
    test held in each of several periods and "and" for two tests joined by "and", with
    ``parts`` the tests it combines, each computed on its own (newest period first);
    ``left`` and ``right`` are then the first part's, and ``margin`` is None. Both are
    empty for a single test, and in runs recorded before these forms.
    """

    canonical: str
    form: str
    bound: str = ""
    outcome: ComputedOutcome
    outcome_label: str
    reason: str = ""
    comparison: str
    left: Operand | None = None
    right: Operand | None = None
    operands: list[Operand] = Field(default_factory=list)
    arithmetic: list[str] = Field(default_factory=list)
    margin: float | None = None
    margin_display: str = ""
    counted_as: str = ""
    note: str = ""
    as_of: str = ""
    history: list[HistoryPoint] = Field(default_factory=list)
    history_note: str = ""
    read_by: list[str] = Field(default_factory=list)
    agreement: str = ""
    agreement_label: str = ""
    dissent: list[ClaimReading] = Field(default_factory=list)
    combines: str = ""
    parts: list[ComputedTest] = Field(default_factory=list)
