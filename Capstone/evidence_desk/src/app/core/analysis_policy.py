"""Every number and sentence the analysis uses, in one place (version 0.14.2).

Kept apart from :mod:`app.core.limits` and :mod:`app.core.policy`, as the watch keeps its
own (:mod:`app.core.watch_policy`), so the contract test of ``limits.py`` is not widened.
``docs/analysis.md`` explains each choice.
"""

from __future__ import annotations

# Analytics (app.core.analytics)
# Quarters a measure's trend is read over, and the fewest moves a typical move is the median of.
SHORT_WINDOW = 4
LONG_WINDOW = 8
# A balance is matched to a quarter's end within this many days.
BALANCE_MATCH_DAYS = 10
# The length of a quarter when the facts do not give its start (days in a year / 4).
DEFAULT_QUARTER_DAYS = 91

# The providers that read EDGAR during a run (app.services.view_providers): the most seconds
# each may take before the run records it as failed and carries on. A run must finish in
# about four minutes, often with nothing kept on disk yet.
OUTSIDE_BUDGET_SECONDS = 20.0
MARKET_BUDGET_SECONDS = 15.0
PROVIDER_OUT_OF_TIME = "its time budget of {seconds:g} seconds ran out"
PROVIDER_FAILED_ERROR = (
    "The analytics provider {name} gave nothing ({why}); its analytics are missing from the record."
)

# The headline (app.core.relevance): at most this many figures.
MAX_HEADLINE = 12

# Persistence odds (app.core.persistence)
PERSISTENCE_PATHS = 10_000
PERSISTENCE_SEED = 20261118
PERSISTENCE_HORIZON = 4
# Fewer historical quarterly changes than this give no estimate, only a warning.
PERSISTENCE_MIN_CHANGES = 8
# The most quarters of history read for the changes resampled (five years).
PERSISTENCE_MAX_HISTORY = 20

# Corollaries (app.core.corollaries)
MAX_COROLLARIES_PER_CLAIM = 3
# A claim gets a visible flag when at least this many of its corollaries were computed with
# a known outcome and more than half came out against what the claim implies.
COROLLARY_FLAG_MIN = 2
# The typed form of each implication the proposing model writes; off, the proposal is the
# sentence alone and the grammar reads it (if the API refuses the schema as too large).
PROPOSE_TYPED_FORM = True

# The model steps (app.engines.analyser)
PROPOSE_STEP = "propose"
ANALYSE_STEP = "analyse"
ANALYSIS_MODEL_VARIABLE = "ANTHROPIC_ANALYSIS_MODEL"
PROPOSE_MAX_TOKENS = 8_000
ANALYSE_MAX_TOKENS = 10_000
# One request must finish well under two minutes; it is not retried on a timeout.
MODEL_TIMEOUT_SECONDS = 110.0
# Sentences per section of the argument: the assessment and the bottom line are arguments.
ASSESSMENT_SENTENCES = 6
BOTTOM_LINE_SENTENCES = 6
SECTION_SENTENCES = 3
MAX_CONDITIONS = 3
MAX_SCENARIOS = 3
MAX_SENTENCE_CHARS = 600
# The 8-K events, findings and figures shown to the analyse step, at most.
MAX_EVENTS_SHOWN = 12
MAX_METRICS_SHOWN = 40

# Who wrote what
CODE = "code"
COROLLARY_RULE = (
    "A corollary is an implication a model proposed and code computed. Each is read by the "
    "grammar and by the typed form the proposing model wrote: two readers, which is weaker "
    "than the two-of-three rule the thesis's own claims are read under. A corollary never "
    "moves a verdict; when most of a claim's computed corollaries come out against it, the "
    "claim is flagged."
)
READ_BY = {
    "agreed": "the grammar and the proposing model read the same test",
    "grammar_only": "the grammar alone (the proposing model gave no typed test that validated)",
    "proposer_only": "the proposing model only (the grammar read no test)",
    "not_agreed": (
        "not agreed: the grammar and the proposing model read different tests; the proposing "
        "model's is computed and both are shown, and it counts toward nothing"
    ),
    "not_computable": "no test: neither the grammar nor the proposing model read one",
}
RESULT_LABELS = {
    "as_expected": "came out as the claim implies",
    "against": "came out against what the claim implies",
    "cannot_tell": "could not be computed from the facts",
    "not_computed": "not computed",
}
COROLLARY_FLAG = (
    "Most of this claim's computed corollaries came out against what it implies "
    "({against} of {known}). The verdict is unchanged; read them before relying on the claim."
)
NO_PROPOSER = "No corollaries: no model was asked to propose them."
PROPOSE_FAILED = "No corollaries: the request for them failed ({why})."
NO_ARGUMENT = "No model wrote an argument: {why}. The figures and their readings are code's."
NO_MODEL_WHY = (
    "this run was given no analysing model (the extractive engine, no key, or a run the "
    "watcher started)"
)
OUT_OF_TIME_WHY = "the run's time limit was reached first"
# One line in Run.errors whenever the record holds less than a model's full analysis.
COMPUTED_ONLY_ERROR = (
    "The analysis holds what code computed only, with no model's corollaries or argument: {why}."
)
MODEL_STEP_ERROR = (
    "The analysis is missing a model step ({why}); what the record holds of the analysis "
    "says who wrote it."
)
LEAN_FLAG = (
    "The model reads the evidence as {lean}, but the verdict is {verdict}. The verdict "
    "stands: it is computed from verified evidence and the computed test."
)
NO_MEASURE = (
    "This claim names no measure the facts report, cites none and compiles to no test: no "
    "figure is tied to it."
)
NO_HEADLINE = (
    "No claim names a measure the facts report, so no figure is a headline; every reported "
    "figure is listed below, not tied to a claim."
)
UNTIED = "Reported figures no claim is tied to: on the record, not part of the analysis."
PERSISTENCE_METHOD = (
    "Resampling with replacement: {paths:,} paths of {horizon} quarters, each step drawn "
    "from the measure's own last {changes} quarterly changes ({step}), from the current "
    "value; the share of paths in which the test holds in every one of the {horizon} "
    "quarters. Seed {seed}. It assumes the past changes are exchangeable: it ignores trend, "
    "seasonality and anything not in the facts. It describes the history; it is not a "
    "forecast."
)
PERSISTENCE_CAVEAT = (
    "This describes the measure's own past quarterly changes, resampled; it knows nothing of "
    "trend, seasonality or events, and is not a forecast."
)
PERSISTENCE_SHORT = (
    "Only {changes} quarterly changes are in the facts; at least {needed} are needed for the "
    "resampled odds to mean anything, so none is given."
)
PERSISTENCE_NOT_APPLICABLE = {
    "no_test": "The claim has no computed test.",
    "form": (
        "Odds are computed for a test of a quarterly measure (its value or its growth on a "
        "year earlier) against a constant; this test is not one."
    ),
    "uncomputed": "The test could not be computed, so its persistence cannot be either.",
}
