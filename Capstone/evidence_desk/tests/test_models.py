"""Request validation the model owns (PROMPT.md 3 and the Rejection truth in 5)."""

import pytest
from pydantic import ValidationError

from app.core import limits
from app.core.models import ThesisRequest

VALID = {
    "ticker": "NVDA",
    "decision": "Keep the position into the next earnings report",
    "claims": ["Data-center revenue is still growing", "A few customers account for most revenue"],
}


def _rejected_field(overrides: dict) -> str:
    with pytest.raises(ValidationError) as caught:
        ThesisRequest(**{**VALID, **overrides})
    return str(caught.value.errors()[0]["loc"][0])


def test_defaults_and_accepts_valid_request() -> None:
    request = ThesisRequest(**VALID)
    assert request.filings == limits.DEFAULT_FILINGS == 3
    assert request.extra_urls == []
    assert request.scope_notes == ""
    assert request.claims == VALID["claims"]


@pytest.mark.parametrize(
    ("given", "stored"),
    [("nvda", "NVDA"), (" msft ", "MSFT"), ("BRK.B", "BRK.B"), ("brk-b", "BRK-B"), ("A", "A")],
)
def test_ticker_accepted_and_upper_cased(given: str, stored: str) -> None:
    assert ThesisRequest(**{**VALID, "ticker": given}).ticker == stored


@pytest.mark.parametrize("ticker", ["nv da$", "", "TOOLONGX", "BRK.BBB", "NV$DA", "BRK/B"])
def test_bad_ticker_is_refused_naming_the_field(ticker: str) -> None:
    assert _rejected_field({"ticker": ticker}) == "ticker"


@pytest.mark.parametrize(
    "claims",
    [
        [],
        [f"Claim number {i} about data-center revenue" for i in range(7)],
        ["Short"],
        ["Data-center revenue is still growing", "x" * (limits.MAX_CLAIM_CHARS + 1)],
        ["Data-center revenue is still growing", "  data-center  REVENUE is still\ngrowing "],
        ["               ", "A few customers account for most revenue"],
    ],
    ids=["zero", "seven", "five-characters", "too-long", "repeat-case-and-space", "blank"],
)
def test_bad_claims_are_refused_naming_the_field(claims: list[str]) -> None:
    assert _rejected_field({"claims": claims}) == "claims"


def test_repeated_claim_message_says_which() -> None:
    with pytest.raises(ValidationError, match="distinct; claim 2 repeats"):
        claims = ["Revenue is still growing fast", "revenue is  STILL growing fast"]
        ThesisRequest(**{**VALID, "claims": claims})


def test_six_claims_and_claim_length_bounds_are_accepted() -> None:
    claims = [f"Claim number {i} about revenue" for i in range(5)]
    claims.append("x" * limits.MAX_CLAIM_CHARS)
    claims[0] = "y" * limits.MIN_CLAIM_CHARS
    assert len(ThesisRequest(**{**VALID, "claims": claims}).claims) == 6


def test_claim_whitespace_is_collapsed() -> None:
    request = ThesisRequest(**{**VALID, "claims": ["  Data-center revenue\n is   still growing "]})
    assert request.claims == ["Data-center revenue is still growing"]


@pytest.mark.parametrize("filings", [0, 6, -1, "3", 3.0, None])
def test_bad_filings_are_refused_naming_the_field(filings: object) -> None:
    assert _rejected_field({"filings": filings}) == "filings"


@pytest.mark.parametrize("filings", [1, 5])
def test_filings_bounds_are_accepted(filings: int) -> None:
    assert ThesisRequest(**{**VALID, "filings": filings}).filings == filings


def test_six_extra_urls_are_refused_naming_the_field() -> None:
    urls = [f"https://investor.example.com/{i}" for i in range(6)]
    assert _rejected_field({"extra_urls": urls}) == "extra_urls"


def test_five_extra_urls_are_accepted() -> None:
    urls = [f"https://investor.example.com/{i}" for i in range(5)]
    assert ThesisRequest(**{**VALID, "extra_urls": urls}).extra_urls == urls


@pytest.mark.parametrize(
    "decision", ["too short", "   short   ", "d" * (limits.MAX_DECISION_CHARS + 1)]
)
def test_bad_decision_is_refused_naming_the_field(decision: str) -> None:
    assert _rejected_field({"decision": decision}) == "decision"


def test_scope_notes_too_long_is_refused() -> None:
    assert _rejected_field({"scope_notes": "n" * (limits.MAX_SCOPE_CHARS + 1)}) == "scope_notes"


def test_text_fields_are_trimmed() -> None:
    request = ThesisRequest(
        **{**VALID, "decision": "  Keep the position for now  ", "scope_notes": " GAAP only "}
    )
    assert request.decision == "Keep the position for now"
    assert request.scope_notes == "GAAP only"
