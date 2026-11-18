"""Tests of the snapshot exporter, the secret scan and the versions page (``make site-test``)."""

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

import export
import scan
import versions_page

PAGE = """<!doctype html>
<html><head><title>Evidence Desk</title>
<link rel="stylesheet" href="/styles.css"></head>
<body class="x">
<a href="?sample">See a recorded run</a> <a href="?sample=changes">Changes</a>
<script src="app.js"></script></body></html>
"""


class CaptureFileTest(unittest.TestCase):
    def test_json_answer_gets_json_suffix(self) -> None:
        self.assertEqual(export.capture_file("/api/meta", "application/json"), "api/meta.json")

    def test_markdown_brief_is_not_doubled(self) -> None:
        self.assertEqual(
            export.capture_file("/api/runs/run-1/export.md", "text/markdown"), "api/runs/run-1/export.md"
        )

    def test_query_is_kept_in_the_name(self) -> None:
        self.assertEqual(
            export.capture_file("/api/runs/r/export.md?reviewed=true&changes=true", "text/markdown"),
            "api/runs/r/export__reviewed-true_changes-true.md",
        )

    def test_dot_segments_are_refused(self) -> None:
        with self.assertRaises(export.ExportError):
            export.capture_file("/api/../secret", "application/json")


class PageTest(unittest.TestCase):
    def test_absolute_references_become_relative(self) -> None:
        self.assertIn('href="styles.css"', export.relative_refs(PAGE))

    def test_assets_and_samples_are_found(self) -> None:
        self.assertEqual(export.asset_names(PAGE), ["styles.css", "app.js"])
        script = 'const SAMPLE_RUN_CHANGES = { run: "sample-run-changes.json" };'
        self.assertEqual(
            export.sample_names(PAGE, script),
            ["sample-changes.json", "sample-run-changes.json", "sample-run.json"],
        )

    def test_banner_and_shim_are_injected_once_in_order(self) -> None:
        page = export.inject(PAGE, 7)
        self.assertEqual(page.count("data-snapshot-version"), 1)
        self.assertIn("Recorded snapshot of Evidence Desk version 7.", page)
        self.assertIn("/tree/capstone-v7", page)
        self.assertLess(page.index('src="snapshot.js"'), page.index("</head>"))
        self.assertLess(page.index('<body class="x">'), page.index("snapshot-banner\""))
        self.assertLess(page.index('src="snapshot.js"'), page.index('src="app.js"'))

    def test_brief_links_follow_the_version(self) -> None:
        self.assertEqual(export.brief_queries("x"), [""])
        self.assertEqual(export.brief_queries("`/export.md?reviewed=true`"), ["", "reviewed=true"])
        self.assertEqual(
            export.brief_queries('query.set("changes", "true");'),
            ["changes=true", "reviewed=true&changes=true"],
        )


class WriteTest(unittest.TestCase):
    def test_every_route_has_its_file_and_the_shim_names_it(self) -> None:
        snapshot = export.Snapshot(version=3, source="http://127.0.0.1:8703")
        snapshot.files = {"index.html": b"<html>", "app.js": b"1"}
        snapshot.routes = [export.Capture("/api/meta", "api/meta.json", b'{"a": 1}', "application/json")]
        with tempfile.TemporaryDirectory() as tmp:
            export.write(snapshot, Path(tmp))
            root = Path(tmp) / "v3"
            manifest = json.loads((root / "snapshot.json").read_text())
            self.assertEqual(manifest["routes"], {"/api/meta": "api/meta.json"})
            self.assertEqual((root / "api/meta.json").read_bytes(), b'{"a": 1}')
            self.assertIn('"/api/meta": "api/meta.json"', (root / "snapshot.js").read_text())
            first = {p: p.read_bytes() for p in root.rglob("*") if p.is_file()}
            export.write(snapshot, Path(tmp))
            second = {p: p.read_bytes() for p in root.rglob("*") if p.is_file()}
            self.assertEqual(first, second, "a second export of the same answers must not differ")

    def test_two_answers_for_one_file_are_refused(self) -> None:
        snapshot = export.Snapshot(version=3, source="s")
        snapshot.routes = [
            export.Capture("/api/a", "api/a.json", b"1", "application/json"),
            export.Capture("/api/a?", "api/a.json", b"2", "application/json"),
        ]
        with tempfile.TemporaryDirectory() as tmp, self.assertRaises(export.ExportError):
            export.write(snapshot, Path(tmp))


class ScanTest(unittest.TestCase):
    def findings(self, text: str) -> list[str]:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "f.json"
            path.write_text(text)
            return scan.scan_file(path)

    def test_each_kind_of_leak_is_found(self) -> None:
        for leak in [
            "key sk-ant-api03-abcdef",
            "contact someone@example.org",
            '"User-Agent": "Evidence Desk research tool"',
            "/Users/someone/code",
            "ANTHROPIC_API_KEY=abcdefgh1234",
        ]:
            with self.subTest(leak=leak):
                self.assertTrue(self.findings(leak))

    def test_a_finding_does_not_print_the_secret(self) -> None:
        findings = self.findings("sk-ant-api03-SECRETVALUE")
        self.assertTrue(findings)
        for finding in findings:
            self.assertNotIn("SECRETVALUE", finding)

    def test_ordinary_record_text_passes(self) -> None:
        self.assertEqual(self.findings('{"ticker": "NVDA", "url": "https://www.sec.gov/x.htm"}'), [])


class VersionsPageTest(unittest.TestCase):
    TABLE = """# Versions

Intro with a [link](../README.md).

| Version | Snapshot |
| --- | --- |
| [`capstone-v1`](https://github.com/abgup05/EE292M/tree/capstone-v1) | [/v1/](https://ee292m-visualization.vercel.app/v1/) |
| 2 <b> | none |

After the table.
"""

    def test_table_rows_and_links_are_rendered(self) -> None:
        page = versions_page.render(self.TABLE)
        self.assertIn('<a href="/v1/">/v1/</a>', page)
        self.assertIn('<a href="https://github.com/abgup05/EE292M/tree/capstone-v1"><code>capstone-v1</code></a>', page)
        self.assertIn("2 &lt;b&gt;", page)
        self.assertIn('href="https://github.com/abgup05/EE292M/blob/main/README.md"', page)
        self.assertEqual(page.count("<tr>"), 3)


if __name__ == "__main__":
    unittest.main()
