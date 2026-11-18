"""The mechanical rename of tools/live/vendor.py: what it changes and what it leaves (make site-test)."""

from __future__ import annotations

import io
import sys
import tarfile
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import vendor  # noqa: E402

MODULES = {"core", "core.models", "watch", "api"}


def renamed(source: str) -> str:
    return vendor.rename(source, "ed_v9", MODULES)[0]


class RenameTest(unittest.TestCase):
    def test_every_import_form_is_renamed(self):
        cases = {
            "import app\n": "import ed_v9\n",
            "import app.core.models as m\n": "import ed_v9.core.models as m\n",
            "import os, app.core\n": "import os, ed_v9.core\n",
            "from app import wiring\n": "from ed_v9 import wiring\n",
            "from app.core.models import (\n    Run,\n    Thesis,\n)\n": (
                "from ed_v9.core.models import (\n    Run,\n    Thesis,\n)\n"
            ),
            "def f():\n    from app.core import limits\n    return limits\n": (
                "def f():\n    from ed_v9.core import limits\n    return limits\n"
            ),
            "x = 1; import app.api\n": "x = 1; import ed_v9.api\n",
            "try:\n    from app.watch import routes\nexcept ImportError:\n    routes = None\n": (
                "try:\n    from ed_v9.watch import routes\nexcept ImportError:\n    routes = None\n"
            ),
        }
        for source, expected in cases.items():
            self.assertEqual(renamed(source), expected, source)

    def test_names_that_only_look_like_the_package_are_left(self):
        for source in (
            "from apple import app\n",
            "import application\n",
            "from fastapi import FastAPI\napp = FastAPI()\napp.get('/')\n",
            "from .app import thing\n",
            "from os import app\n",
            "# from app.core import limits\n",
            '"""Run it with ``python -m app.cli``; see :mod:`app.core`."""\n',
            'FILES = {"/app.js": ("app.js", "text/javascript")}\n',
            'prog = "python -m app.cli"\n',
        ):
            self.assertEqual(renamed(source), source, source)

    def test_a_string_that_is_exactly_a_module_name_is_renamed_and_reported(self):
        source = 'own = thing.__module__.startswith("app.")\nname = "app.watch"\nother = "app.unknown"\n'
        text, report = vendor.rename(source, "ed_v9", MODULES)
        self.assertIn('startswith("ed_v9.")', text)
        self.assertIn('name = "ed_v9.watch"', text)
        self.assertIn('other = "app.unknown"', text)
        self.assertEqual(report.strings, ["app. -> ed_v9.", "app.watch -> ed_v9.watch"])


class VendorTest(unittest.TestCase):
    def archive(self, files: dict[str, bytes]) -> tarfile.TarFile:
        buffer = io.BytesIO()
        with tarfile.open(fileobj=buffer, mode="w") as tar:
            for name, body in files.items():
                info = tarfile.TarInfo(f"Capstone/evidence_desk/src/{name}")
                info.size = len(body)
                tar.addfile(info, io.BytesIO(body))
        buffer.seek(0)
        return tarfile.open(fileobj=buffer, mode="r:")

    def test_the_package_is_renamed_and_the_page_is_copied_byte_for_byte(self):
        page = b"<html><head></head><body>\xe2\x80\x94</body></html>"
        files = {
            "app/__init__.py": b"",
            "app/api.py": b"from app import core\n",
            "app/core.py": b"X = 1\n",
            "web/index.html": page,
        }
        with tempfile.TemporaryDirectory() as out:
            manifest = vendor.vendor(9, "capstone-v9", "c" * 40, self.archive(files), Path(out))
            self.assertEqual(manifest["renamed_imports"], 1)
            self.assertEqual((Path(out) / "v9/ed_v9/api.py").read_text(), "from ed_v9 import core\n")
            self.assertEqual((Path(out) / "v9/web/index.html").read_bytes(), page)
            self.assertFalse((Path(out) / "v9/app").exists())

    def test_a_tree_with_anything_but_the_package_and_the_page_is_refused(self):
        files = {"app/__init__.py": b"", "web/index.html": b"", "other/secret.txt": b"x"}
        with tempfile.TemporaryDirectory() as out, self.assertRaises(vendor.VendorError):
            vendor.vendor(9, "capstone-v9", "c" * 40, self.archive(files), Path(out))


if __name__ == "__main__":
    unittest.main()
