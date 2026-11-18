"""Every number in the data contract, in one place.

``Capstone/PROMPT.md`` states these limits; the request model, the pipeline, the
model prompts, the export and the page all read them from here, so they cannot
drift apart. This module imports nothing from the application.
"""

# Request (validated at the API boundary)
MIN_DECISION_CHARS = 10
MAX_DECISION_CHARS = 500
MIN_CLAIMS = 1
MAX_CLAIMS = 6
MIN_CLAIM_CHARS = 15
MAX_CLAIM_CHARS = 400
MAX_SCOPE_CHARS = 2000
DEFAULT_FILINGS = 3
MAX_FILINGS = 5
MAX_EXTRA_URLS = 5

# Retrieval and assessment
PASSAGE_TARGET_CHARS = 1100
PASSAGE_MAX_CHARS = 1800
PASSAGES_PER_CLAIM = 8
MAX_PASSAGES_PER_SOURCE = 5
MAX_QUERIES_PER_CLAIM = 4
MAX_FINDINGS_PER_CLAIM = 4

# A filing with less than this share of its text under numbered Item headings is flagged.
MIN_ITEM_COVERAGE = 0.5

# Evidence
MIN_EXCERPT_CHARS = 20
MAX_EXCERPT_CHARS = 600
CONTEXT_CHARS = 240

# The meaning check: a second model's one-sentence reason per finding, at most this long.
MAX_SUPPORT_REASON_CHARS = 300

# Reported figures (XBRL company facts)
FIGURE_QUARTERS = 3
FIGURE_YEARS = 2
MAX_FIGURES_OFFERED = 40
METRICS_CACHE_SECONDS = 900
# Figures from a filing's own tags (segments, products, geographies, customers), offered after
# the figures above when a run asks for them (ThesisRequest.tagged_figures). When the newest
# annual and quarterly report hold more, members are taken largest first in every breakdown at
# once, a value always with its change (app.core.tagged_figures.select_tagged). 40 keeps the
# three largest members of each NVIDIA breakdown in both filings (52 are built).
MAX_TAGGED_FIGURES_OFFERED = 40

# Current reports (8-K) since the annual report (app.core.events, app.services.events).
# The documents of at most this many 8-Ks are read per run, newest first: every 8-K filed after
# the newest periodic report read, then those of a substantive category since the annual report.
# Eight covers every such 8-K NVIDIA filed in the nine months after its 10-K of February 2026
# (seven) with one to spare; each is one request of about 30 KB.
MAX_EVENTS_READ = 8
# The opening sentences of each item of an 8-K kept on the record and shown on the page.
EVENT_OPENING_SENTENCES = 2
# Item sections of 8-Ks offered to a claim of the same category, beside its retrieved passages.
EVENT_PASSAGES_PER_CLAIM = 2

# Dated facts (app.core.facts, app.core.claimtest). A run or a ledger may be computed as of a
# past date no earlier than this: XBRL company facts begin in 2009.
EARLIEST_AS_OF = "2009-01-01"
# A computed claim's history (app.core.claim_eval): its outcome as of each 10-K and 10-Q
# filing date of the last five years, at most 24 points (five years of quarterly filers
# give 20), from the facts the run already has.
HISTORY_YEARS = 5
MAX_HISTORY_POINTS = 24
# Periods a streak ("has grown for N consecutive quarters") walks back at most.
MAX_STREAK_PERIODS = 40

# Review and saved theses
MAX_NOTE_CHARS = 500
MAX_THESIS_NAME_CHARS = 80

# Run bounds
RUN_TIME_LIMIT_SECONDS = 300.0
# Claims assessed at once: each assessment is one model call of several seconds.
MAX_CONCURRENT_ASSESSMENTS = 3
