"""Render docs/versions.md as the website's /versions page (``make site-index``).

docs/versions.md is the one source: this script turns its headings, paragraphs, lists and
its table into a static HTML page, written as ``versions.html`` in the snapshot directory.
It understands only the Markdown that file uses: ``#`` headings, paragraphs, ``-`` lists,
pipe tables, ``code``, **bold** and [links](...). Links to files in the repository become
links to GitHub; links to the website's own snapshots become paths on the site. Every other
character is escaped. The output depends on the input only, so it is deterministic.
"""

from __future__ import annotations

import html
import posixpath
import re
import sys
from pathlib import Path

REPOSITORY_BLOB = "https://github.com/abgup05/EE292M/blob/main/"
SITE = "https://ee292m-visualization.vercel.app"
SOURCE_DIR = "docs"
INLINE = re.compile(r"`([^`]+)`|\*\*([^*]+)\*\*|\[([^\]]+)\]\(([^)\s]+)\)")


def link_target(url: str) -> str:
    """Where a link in docs/versions.md points from the website."""
    if url.startswith(SITE + "/"):
        return url[len(SITE) :]
    if re.match(r"^[a-z]+:", url) or url.startswith("#"):
        return url
    path, _, anchor = url.partition("#")
    resolved = posixpath.normpath(posixpath.join(SOURCE_DIR, path))
    return REPOSITORY_BLOB + resolved + (f"#{anchor}" if anchor else "")


def inline(text: str) -> str:
    """Escape a run of Markdown text and render its code, bold and links."""
    out, last = [], 0
    for match in INLINE.finditer(text):
        out.append(html.escape(text[last : match.start()]))
        code, bold, label, url = match.groups()
        if code is not None:
            out.append(f"<code>{html.escape(code)}</code>")
        elif bold is not None:
            out.append(f"<strong>{inline(bold)}</strong>")
        else:
            out.append(f'<a href="{html.escape(link_target(url))}">{inline(label)}</a>')
        last = match.end()
    out.append(html.escape(text[last:]))
    return "".join(out)


def cells(line: str) -> list[str]:
    """The cells of one pipe-table row."""
    return [cell.strip() for cell in line.strip().strip("|").split("|")]


def body(markdown: str) -> str:
    """The HTML of the document's blocks."""
    blocks: list[str] = []
    lines = markdown.splitlines()
    i = 0
    while i < len(lines):
        line = lines[i]
        if not line.strip():
            i += 1
        elif line.startswith("#"):
            level = len(line) - len(line.lstrip("#"))
            blocks.append(f"<h{level}>{inline(line[level:].strip())}</h{level}>")
            i += 1
        elif line.startswith("|"):
            rows = []
            while i < len(lines) and lines[i].startswith("|"):
                rows.append(cells(lines[i]))
                i += 1
            head, rest = rows[0], [r for r in rows[1:] if not all(set(c) <= set("-: ") for c in r)]
            table = ["<table>", "<thead><tr>" + "".join(f"<th>{inline(c)}</th>" for c in head) + "</tr></thead>"]
            table.append("<tbody>")
            table += ["<tr>" + "".join(f"<td>{inline(c)}</td>" for c in r) + "</tr>" for r in rest]
            table.append("</tbody></table>")
            blocks.append('<div class="table-wrap">' + "\n".join(table) + "</div>")
        elif line.startswith("- "):
            items = []
            while i < len(lines) and lines[i].startswith("- "):
                items.append(f"<li>{inline(lines[i][2:].strip())}</li>")
                i += 1
            blocks.append("<ul>" + "".join(items) + "</ul>")
        else:
            paragraph = []
            while i < len(lines) and lines[i].strip() and not lines[i].startswith(("#", "|", "- ")):
                paragraph.append(lines[i].strip())
                i += 1
            blocks.append(f"<p>{inline(' '.join(paragraph))}</p>")
    return "\n".join(blocks)


STYLE = """
  :root { color-scheme: light dark; --bg: #fbfaf7; --fg: #22211d; --muted: #6b685e; --line: #dedad0; --link: #1d4f91; }
  @media (prefers-color-scheme: dark) { :root { --bg: #171714; --fg: #e8e5dc; --muted: #a29e92; --line: #39372f; --link: #8db4ec; } }
  body { margin: 0; background: var(--bg); color: var(--fg); font: 15px/1.5 system-ui, -apple-system, "Segoe UI", sans-serif; }
  main { max-width: 1200px; margin: 0 auto; padding: 24px 16px 48px; }
  h1 { font-size: 1.6rem; margin: 0 0 12px; }
  h2 { font-size: 1.15rem; margin: 28px 0 8px; }
  p, li { max-width: 75ch; }
  a { color: var(--link); }
  code { font: 0.9em ui-monospace, SFMono-Regular, Menlo, monospace; }
  .table-wrap { overflow-x: auto; border: 1px solid var(--line); border-radius: 6px; }
  table { border-collapse: collapse; font-size: 0.875rem; min-width: 900px; }
  th, td { text-align: left; vertical-align: top; padding: 8px 10px; border-bottom: 1px solid var(--line); }
  th { color: var(--muted); font-weight: 600; white-space: nowrap; }
  tbody tr:last-child td { border-bottom: 0; }
  .back { color: var(--muted); font-size: 0.875rem; }
"""


def render(markdown: str) -> str:
    """The complete /versions page."""
    return (
        "<!doctype html>\n<html lang=\"en\">\n<head>\n<meta charset=\"utf-8\">\n"
        '<meta name="viewport" content="width=device-width, initial-scale=1">\n'
        "<title>Evidence Desk versions</title>\n"
        f"<style>{STYLE}</style>\n</head>\n<body>\n<main>\n"
        '<p class="back">EE292M · <a href="/">Week 2 Industry Flow Explorer</a> · '
        f'<a href="{REPOSITORY_BLOB}docs/versions.md">this page in the repository</a></p>\n'
        f"{body(markdown)}\n</main>\n</body>\n</html>\n"
    )


def main(argv: list[str]) -> int:
    if len(argv) != 2:
        print("Usage: versions_page.py docs/versions.md OUT_DIR", file=sys.stderr)
        return 2
    source, out = Path(argv[0]), Path(argv[1])
    page = render(source.read_text(encoding="utf-8"))
    out.mkdir(parents=True, exist_ok=True)
    (out / "versions.html").write_text(page, encoding="utf-8")
    print(f"Wrote {out / 'versions.html'} ({len(page.encode()):,} bytes) from {source}.")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
