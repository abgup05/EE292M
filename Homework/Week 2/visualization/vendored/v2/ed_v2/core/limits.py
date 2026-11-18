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

# Evidence
MIN_EXCERPT_CHARS = 20
MAX_EXCERPT_CHARS = 600
CONTEXT_CHARS = 240

# Run bounds
RUN_TIME_LIMIT_SECONDS = 300.0
