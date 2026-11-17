"""Every number in ``app.core.limits`` equals the value the data contract states.

The contract is ``Capstone/PROMPT.md`` sections 3 (request) and 4 (method),
plus the limits later versions added (Item coverage, excerpt context, reported
figures, concurrent assessments; the review note and the saved thesis name).
The code reads each limit from the module, so
a test written against the module cannot notice a changed value; this one is
written against the contract. Changing a limit therefore means changing this
file in the same commit, and saying why.
"""

from __future__ import annotations

from app.core import limits

CONTRACT: dict[str, int | float] = {
    # PROMPT.md section 3: the request
    "MIN_DECISION_CHARS": 10,
    "MAX_DECISION_CHARS": 500,
    "MIN_CLAIMS": 1,
    "MAX_CLAIMS": 6,
    "MIN_CLAIM_CHARS": 15,
    "MAX_CLAIM_CHARS": 400,
    "MAX_SCOPE_CHARS": 2000,
    "DEFAULT_FILINGS": 3,
    "MAX_FILINGS": 5,
    "MAX_EXTRA_URLS": 5,
    # PROMPT.md section 4.5: chunking
    "PASSAGE_TARGET_CHARS": 1100,
    "PASSAGE_MAX_CHARS": 1800,
    # PROMPT.md section 4.6: retrieval
    "PASSAGES_PER_CLAIM": 8,
    "MAX_PASSAGES_PER_SOURCE": 5,
    "MAX_QUERIES_PER_CLAIM": 4,
    # PROMPT.md section 4.7: assessment
    "MAX_FINDINGS_PER_CLAIM": 4,
    # PROMPT.md section 4.8: verification
    "MIN_EXCERPT_CHARS": 20,
    "MAX_EXCERPT_CHARS": 600,
    # PROMPT.md section 4.9: the run time limit
    "RUN_TIME_LIMIT_SECONDS": 300.0,
    # Added in this version: Item-coverage flag and excerpt context
    "MIN_ITEM_COVERAGE": 0.5,
    "CONTEXT_CHARS": 240,
    # Added in this version: reported figures (XBRL company facts)
    "FIGURE_QUARTERS": 3,
    "FIGURE_YEARS": 2,
    "MAX_FIGURES_OFFERED": 40,
    "METRICS_CACHE_SECONDS": 900,
    # Added in version 3: claims assessed at once (each is one model call)
    "MAX_CONCURRENT_ASSESSMENTS": 3,
    # Added in version 4: a reviewer's note on a decision, and a saved thesis's name
    "MAX_NOTE_CHARS": 500,
    "MAX_THESIS_NAME_CHARS": 80,
}


def _public_constants() -> dict[str, object]:
    return {
        name: value
        for name, value in vars(limits).items()
        if name.isupper() and not name.startswith("_")
    }


def test_every_limit_has_its_contract_value() -> None:
    actual = _public_constants()
    wrong = {
        name: (actual.get(name), expected)
        for name, expected in CONTRACT.items()
        if actual.get(name) != expected
    }
    assert not wrong, f"limits differ from the contract (now, contract): {wrong}"


def test_no_limit_exists_outside_the_contract() -> None:
    unlisted = sorted(set(_public_constants()) - set(CONTRACT))
    assert not unlisted, f"add these limits to the contract test with their source: {unlisted}"
