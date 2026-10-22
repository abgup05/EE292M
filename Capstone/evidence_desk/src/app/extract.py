"""Turn retrieved HTML into stored source text with section locators.

The extracted text is the only text evidence may quote from: every excerpt is
later verified as an exact substring of :attr:`ExtractedDocument.text`.
Page content is data; nothing here interprets it as instructions.
"""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass, field
from urllib.parse import urlsplit

from bs4 import BeautifulSoup, Tag

REMOVED_TAGS = (
    "script",
    "style",
    "noscript",
    "template",
    "svg",
    "iframe",
    "nav",
    "header",
    "footer",
    "aside",
    "form",
    "button",
)
REMOVED_ROLES = frozenset({"navigation", "banner", "contentinfo", "complementary", "search"})
HEADING_TAGS = ("h1", "h2", "h3", "h4", "h5", "h6")
BLOCK_TAGS = HEADING_TAGS + ("p", "li", "blockquote", "pre", "td", "th", "dd", "dt", "figcaption")
DATE_META_NAMES = (
    "article:published_time",
    "datePublished",
    "date",
    "dc.date",
    "dc.date.issued",
    "dcterms.issued",
    "dcterms.date",
    "citation_publication_date",
    "citation_date",
    "pubdate",
    "publish-date",
    "publication_date",
)
ISO_DATE = re.compile(r"(\d{4}-\d{2}-\d{2})")
WHITESPACE = re.compile(r"\s+")


@dataclass(frozen=True)
class Section:
    """Text under one heading; ``heading`` is the citation locator."""

    heading: str
    text: str


@dataclass(frozen=True)
class ExtractedDocument:
    """Stored source text plus the metadata the brief shows for it."""

    url: str
    title: str
    publisher: str
    published_date: str | None
    text: str
    content_hash: str
    sections: list[Section] = field(default_factory=list)


def _clean(value: str) -> str:
    return WHITESPACE.sub(" ", value).strip()


def _meta(soup: BeautifulSoup, *names: str) -> str | None:
    for name in names:
        tag = soup.find("meta", attrs={"property": name}) or soup.find("meta", attrs={"name": name})
        if isinstance(tag, Tag):
            content = tag.get("content")
            if isinstance(content, str) and content.strip():
                return content.strip()
    return None


def _published_date(soup: BeautifulSoup) -> str | None:
    """Publication date from metadata only; visible text is never guessed from."""
    value = _meta(soup, *DATE_META_NAMES)
    if value is None:
        tag = soup.find("time", attrs={"datetime": True})
        if isinstance(tag, Tag) and isinstance(tag.get("datetime"), str):
            value = str(tag["datetime"])
    if value is None:
        return None
    match = ISO_DATE.search(value)
    return match.group(1) if match else None


def _strip_boilerplate(soup: BeautifulSoup) -> None:
    for tag in soup.find_all(REMOVED_TAGS):
        tag.decompose()
    for tag in soup.find_all(attrs={"role": True}):
        if isinstance(tag, Tag) and str(tag.get("role", "")).lower() in REMOVED_ROLES:
            tag.decompose()


def _sections(root: Tag) -> list[Section]:
    sections: list[Section] = []
    heading = ""
    buffer: list[str] = []

    def flush() -> None:
        text = _clean(" ".join(buffer))
        if text or heading:
            sections.append(Section(heading=heading, text=text))
        buffer.clear()

    for block in root.find_all(BLOCK_TAGS):
        if block.find_parent(BLOCK_TAGS) is not None:
            continue  # nested block; the parent's text already includes it
        text = _clean(block.get_text(" "))
        if not text:
            continue
        if block.name in HEADING_TAGS:
            flush()
            heading = text
        else:
            buffer.append(text)
    flush()
    return [section for section in sections if section.text]


def extract_document(url: str, html: str) -> ExtractedDocument:
    """Extract title, publisher, publication date, sections and body text from ``html``."""
    soup = BeautifulSoup(html, "html.parser")
    domain = (urlsplit(url).hostname or "").lower()
    title = _meta(soup, "og:title", "twitter:title") or (
        _clean(soup.title.get_text()) if soup.title else ""
    )
    title = title.split(" | ")[0].strip() or domain
    publisher = _meta(soup, "og:site_name", "publisher", "dc.publisher") or domain
    published = _published_date(soup)

    _strip_boilerplate(soup)
    root: Tag = soup.find("main") or soup.find("article") or soup.body or soup
    sections = _sections(root)
    if not sections:
        fallback = _clean(root.get_text(" "))
        sections = [Section(heading="", text=fallback)] if fallback else []
    text = "\n\n".join(
        f"{section.heading}\n{section.text}" if section.heading else section.text
        for section in sections
    )
    return ExtractedDocument(
        url=url,
        title=title,
        publisher=publisher,
        published_date=published,
        text=text,
        content_hash=hashlib.sha256(text.encode("utf-8")).hexdigest(),
        sections=sections,
    )
