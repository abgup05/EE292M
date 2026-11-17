"""Extraction checks against the recorded real public page.

The NIST page and its manifest were recorded by the earlier fixture recorder;
they are kept so the public-page extractor (used for a run's optional extra
URLs) is still tested offline against a real page. The SEC EDGAR fixtures under
``tests/fixtures/edgar/`` are covered by ``test_filing.py``.
"""

import json
from pathlib import Path

import pytest

from app.sources.web import extract_document

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
        pytest.skip("no recorded public-page fixtures")
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


def test_real_page_sections_are_exact_substrings(manifest: dict) -> None:
    entry = manifest.get("nist_ai_rmf")
    if entry is None:
        pytest.skip("NIST fixture not recorded")
    doc = extract_document(entry["final_url"], (FIXTURES / "nist_ai_rmf.html").read_text())
    assert all(section.text in doc.text for section in doc.sections)
