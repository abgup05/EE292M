"""Every vendored capstone version imports whole under its new name and answers (make live-imports).

Each version is imported in a fresh interpreter whose path holds only that version's directory
(not this app's ``src``), so a module that still imported ``app`` would fail here. Then the
website builds the version as it does online (src/live/versions.py) and asks it for its page
and the address its page reads first.
"""

from __future__ import annotations

import asyncio
import json
import subprocess
import sys
from pathlib import Path

import pytest

from live.seed import Seed
from live.site import call
from live.versions import VENDOR_DIR, Version, discover

VERSIONS = discover()
IMPORT_ALL = """
import importlib, json, pkgutil, sys
sys.path.insert(0, sys.argv[2])
package = importlib.import_module(sys.argv[1])
names = [sys.argv[1]]
for info in pkgutil.walk_packages(package.__path__, sys.argv[1] + "."):
    if info.name.endswith(".__main__"):
        continue  # an entry point runs its command when imported
    importlib.import_module(info.name)
    names.append(info.name)
print(json.dumps({"modules": len(names), "leaked": sorted(
    n for n in sys.modules if n == "app" or n.startswith("app."))}))
"""


def test_every_version_in_the_map_is_vendored():
    assert sorted(VERSIONS) == list(range(1, len(VERSIONS) + 1)), sorted(VERSIONS)
    assert len(VERSIONS) >= 14


@pytest.mark.parametrize("number", sorted(VERSIONS))
def test_every_module_imports_under_its_new_name(number, tmp_path):
    info = VERSIONS[number]
    manifest = json.loads((info.directory / "VENDORED.json").read_text())
    result = subprocess.run(
        [sys.executable, "-B", "-E", "-c", IMPORT_ALL, info.package, str(info.directory)],
        cwd=tmp_path,
        env={"EVIDENCE_DESK_DATA_DIR": str(tmp_path), "HOME": "/tmp"},
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr[-2000:]
    report = json.loads(result.stdout.strip().splitlines()[-1])
    assert report["leaked"] == []
    entry_points = len(list((info.directory / info.package).rglob("__main__.py")))
    assert report["modules"] == manifest["python_files"] - entry_points


@pytest.mark.parametrize("number", sorted(VERSIONS))
def test_no_import_of_the_old_package_name_is_left(number):
    info = VERSIONS[number]
    for path in (info.directory / info.package).rglob("*.py"):
        for line in path.read_text(encoding="utf-8").splitlines():
            stripped = line.strip()
            assert not stripped.startswith(("from app.", "from app ", "import app")), (path, line)


@pytest.mark.parametrize("number", sorted(VERSIONS))
def test_the_website_builds_the_version_and_it_answers(number, tmp_path, monkeypatch):
    monkeypatch.setenv("LIVE_DATA_ROOT", str(tmp_path))
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    info = VERSIONS[number]
    app = Version(info, Seed(VENDOR_DIR / "seed")).load()
    scope = {
        "type": "http",
        "asgi": {"version": "3.0"},
        "http_version": "1.1",
        "scheme": "http",
        "root_path": f"/v{number}",
        "query_string": b"",
        "headers": [(b"host", b"testserver")],
        "client": ("127.0.0.1", 50000),
        "server": ("testserver", 80),
    }
    first = "/api/research" if info.era == "research" else "/api/meta"
    for path in ("/", "/app.js", first):
        status, _, body = asyncio.run(call(app, scope, "GET", path))
        assert status == 200, (path, body[:300])
    if info.era == "thesis":
        meta = json.loads(asyncio.run(call(app, scope, "GET", "/api/meta"))[2])
        assert meta.get("engine") in (None, "extractive"), meta.get("engine")
    # Its data went where the website put it, and nowhere in the source tree.
    assert any((tmp_path / f"v{number}").rglob("*.sqlite")), "no database under the data root"
    assert not list(Path(info.directory).rglob("*.sqlite"))
