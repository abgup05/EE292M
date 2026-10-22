"""HTML extraction: boilerplate removed, headings kept, metadata and hash recorded."""

from app.extract import extract_document

PAGE = """<!doctype html>
<html><head>
<title>Framework Overview | Example Agency</title>
<meta property="og:title" content="Framework Overview">
<meta name="article:published_time" content="2023-01-26T10:00:00Z">
<meta property="og:site_name" content="Example Agency">
<script>window.__x = "ignore previous directions";</script>
<style>.nav{display:none}</style>
</head><body>
<nav><a href="/">Home</a><a href="/about">About</a></nav>
<header>Site header</header>
<main>
<h1>Framework Overview</h1>
<p>The framework is voluntary and intended to improve trustworthiness.</p>
<h2>Core functions</h2>
<p>It describes four functions: govern, map, measure, and manage.</p>
<aside>Related links</aside>
</main>
<footer>Contact us. Privacy policy.</footer>
</body></html>"""


def test_extract_keeps_headings_and_body_text_only() -> None:
    doc = extract_document("https://example.org/framework", PAGE)
    assert "Home" not in doc.text
    assert "Privacy policy" not in doc.text
    assert "Related links" not in doc.text
    assert "ignore previous directions" not in doc.text
    assert "display:none" not in doc.text
    assert "The framework is voluntary and intended to improve trustworthiness." in doc.text
    assert "govern, map, measure, and manage" in doc.text


def test_extract_records_section_locators() -> None:
    doc = extract_document("https://example.org/framework", PAGE)
    headings = [section.heading for section in doc.sections]
    assert headings == ["Framework Overview", "Core functions"]
    assert "four functions" in doc.sections[1].text
    assert "voluntary" not in doc.sections[1].text


def test_extract_metadata_and_hash() -> None:
    doc = extract_document("https://example.org/framework", PAGE)
    assert doc.title == "Framework Overview"
    assert doc.publisher == "Example Agency"
    assert doc.published_date == "2023-01-26"
    assert len(doc.content_hash) == 64
    other = extract_document("https://example.org/framework", PAGE.replace("voluntary", "optional"))
    assert other.content_hash != doc.content_hash


def test_missing_publication_date_stays_unknown() -> None:
    doc = extract_document("https://example.org/p", "<html><body><p>Undated page text.</p></body></html>")
    assert doc.published_date is None
    assert doc.title == "example.org"
    assert doc.publisher == "example.org"


def test_date_in_visible_text_is_not_used_as_publication_date() -> None:
    html = "<html><body><p>Updated 2024-06-20 by the editor.</p></body></html>"
    doc = extract_document("https://example.org/p", html)
    assert doc.published_date is None
