"""Input validation at the API boundary (the backend repeats what the form checks)."""

import pytest
from pydantic import ValidationError

from app.models import ResearchRequest

VALID = {
    "question": "What opportunities and risks should an organization examine before using AI?",
    "decision": "Whether to investigate a limited internal pilot",
}


def test_defaults_and_accepts_valid_request() -> None:
    request = ResearchRequest(**VALID)
    assert request.source_budget == 10
    assert request.seed_urls == []
    assert request.scope_notes == ""


@pytest.mark.parametrize(
    "overrides",
    [
        {"question": "Too short?"},
        {"question": "x" * 2001},
        {"question": "   " * 20},
        {"decision": "short"},
        {"decision": "d" * 501},
        {"scope_notes": "n" * 5001},
        {"source_budget": 5},
        {"source_budget": 16},
        {"source_budget": "ten"},
        {"seed_urls": ["ftp://example.org/x"]},
        {"seed_urls": ["http://localhost/"]},
        {"seed_urls": ["https://example.org/a", "https://example.org/a"]},
        {"seed_urls": ["not a url"]},
        {"seed_urls": [f"https://example.org/{i}" for i in range(21)]},
    ],
)
def test_rejects_invalid_fields(overrides: dict) -> None:
    with pytest.raises(ValidationError):
        ResearchRequest(**{**VALID, **overrides})


def test_seed_urls_are_canonicalized_and_duplicates_rejected() -> None:
    with pytest.raises(ValidationError, match="distinct"):
        ResearchRequest(
            **VALID,
            seed_urls=["https://example.org/a/", "HTTPS://example.org/a#frag"],
        )
    request = ResearchRequest(
        **VALID, seed_urls=["https://example.org/a/?utm_source=x"]
    )
    assert request.seed_urls == ["https://example.org/a"]


def test_text_fields_are_trimmed() -> None:
    request = ResearchRequest(**{**VALID, "decision": "  Whether to run a pilot  "})
    assert request.decision == "Whether to run a pilot"
