"""Retrieval and metadata checks against the recorded real seed page(s).

``make fixtures`` records the HTML and a manifest with the UTC retrieval time.
These tests run offline and fail if extraction of the real page regresses.
The GAO seed page returned HTTP 403 to this fetcher when fixtures were
recorded, so only the NIST page is covered; see the README.
"""

import json
from pathlib import Path

import pytest

from app.extract import extract_document
from app.models import ResearchRequest
from app.synthesize import ExtractiveSynthesizer

FIXTURES = Path(__file__).parent / "fixtures"
MANIFEST = FIXTURES / "manifest.json"


def fixture_names() -> list[str]:
    if not MANIFEST.exists():
        return []
    manifest = json.loads(MANIFEST.read_text())
    return [name for name, value in manifest.items() if isinstance(value, dict)]


@pytest.fixture(scope="module")
def manifest() -> dict:
    if not MANIFEST.exists():
        pytest.skip("no recorded fixtures; run `make fixtures`")
    return json.loads(MANIFEST.read_text())


@pytest.mark.parametrize("name", fixture_names())
def test_recorded_page_extracts_consistently(name: str, manifest: dict) -> None:
    entry = manifest[name]
    html = (FIXTURES / f"{name}.html").read_text()
    doc = extract_document(entry["final_url"], html)
    assert doc.title == entry["title"]
    assert doc.publisher == entry["publisher"]
    assert doc.published_date == entry["published_date"]
    assert doc.content_hash == entry["content_hash"]
    assert entry["retrieved_at"].endswith("+00:00")
    assert len(doc.text) > 500
    assert doc.sections


def test_nist_rmf_metadata_matches_the_public_record(manifest: dict) -> None:
    entry = manifest.get("nist_ai_rmf")
    if entry is None:
        pytest.skip("NIST fixture not recorded")
    doc = extract_document(entry["final_url"], (FIXTURES / "nist_ai_rmf.html").read_text())
    assert doc.title == "Artificial Intelligence Risk Management Framework (AI RMF 1.0)"
    assert doc.publisher == "NIST"
    assert doc.published_date == "2023-01-26"
    assert "AI RMF" in doc.text
    # The abstract is the substantive text on this landing page and must be citable.
    assert "The Framework is intended to be voluntary, rights-preserving" in doc.text
    assert any("Abstract" == section.heading for section in doc.sections)
    # Navigation and footer boilerplate must not leak into citable text.
    assert "Skip to main content" not in doc.text
    assert "Privacy Policy" not in doc.text


def test_extractive_findings_from_real_page_are_exact_substrings(manifest: dict) -> None:
    entry = manifest.get("nist_ai_rmf")
    if entry is None:
        pytest.skip("NIST fixture not recorded")
    doc = extract_document(entry["final_url"], (FIXTURES / "nist_ai_rmf.html").read_text())
    request = ResearchRequest(
        question=(
            "What opportunities and risks should an organization examine before using "
            "generative AI in internal workflows?"
        ),
        decision="Whether to investigate a limited internal pilot",
    )
    synthesizer = ExtractiveSynthesizer()
    draft = synthesizer.synthesize(request, synthesizer.plan(request), {"src-1": doc})
    assert draft.findings
    assert all(item.excerpt in doc.text for item in draft.evidence)
