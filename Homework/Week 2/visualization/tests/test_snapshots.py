"""The capstone snapshots and /versions are served, and the Week 2 routes are unchanged."""

import asyncio
import json
import re

import pytest

from app.api import SNAPSHOT_DIR, WEB_DIR, app, snapshot_names


def call(path: str, method: str = "GET") -> tuple[int, dict[str, str], bytes]:
    """Send one HTTP request straight to the ASGI app; return status, headers and body."""
    path, _, query = path.partition("?")
    scope = {
        "type": "http",
        "asgi": {"version": "3.0"},
        "http_version": "1.1",
        "method": method,
        "scheme": "http",
        "path": path,
        "raw_path": path.encode(),
        "query_string": query.encode(),
        "root_path": "",
        "headers": [(b"host", b"testserver")],
        "client": ("127.0.0.1", 50000),
        "server": ("testserver", 80),
    }
    messages: list[dict] = []

    async def receive() -> dict:
        return {"type": "http.request", "body": b"", "more_body": False}

    async def send(message: dict) -> None:
        messages.append(message)

    asyncio.run(app(scope, receive, send))
    start = next(m for m in messages if m["type"] == "http.response.start")
    headers = {k.decode().lower(): v.decode() for k, v in start["headers"]}
    body = b"".join(m.get("body", b"") for m in messages if m["type"] == "http.response.body")
    return start["status"], headers, body


VERSIONS = snapshot_names()


def test_the_week2_page_and_assets_are_unchanged():
    for path, file in [
        ("/", "index.html"),
        ("/app.js", "app.js"),
        ("/styles.css", "styles.css"),
        ("/static/app.js", "app.js"),
    ]:
        status, _, body = call(path)
        assert status == 200, path
        assert body == (WEB_DIR / file).read_bytes(), path


def test_snapshots_are_present_in_version_order():
    assert VERSIONS, "no snapshot directory: run make site-export"
    assert VERSIONS == sorted(VERSIONS, key=lambda name: int(name[1:]))
    assert VERSIONS[0] == "v1"


def test_versions_page_lists_every_snapshot():
    status, headers, body = call("/versions")
    assert status == 200
    assert headers["content-type"].startswith("text/html")
    for name in VERSIONS:
        assert f'href="/{name}/"'.encode() in body, name


@pytest.mark.parametrize("name", VERSIONS)
def test_bare_version_path_leads_to_its_directory(name):
    status, headers, _ = call(f"/{name}")
    assert status == 307
    assert headers["location"] == f"/{name}/"


@pytest.mark.parametrize("name", VERSIONS)
def test_snapshot_page_carries_its_banner_and_shim_before_its_script(name):
    status, headers, body = call(f"/{name}/")
    assert status == 200
    assert headers["content-type"].startswith("text/html")
    page = body.decode()
    number = name[1:]
    assert f'data-snapshot-version="{number}"' in page
    assert f"Recorded snapshot of Evidence Desk version {number}." in page
    assert "Live runs need the app running locally." in page
    assert 'href="/versions"' in page
    assert f"https://github.com/abgup05/EE292M/tree/capstone-v{number}" in page
    assert page.index('src="snapshot.js"') < page.index('src="app.js"')
    assert not re.search(r'(?:href|src)="/(?!versions")', page), "an absolute reference is left"


@pytest.mark.parametrize("name", VERSIONS)
def test_every_recorded_answer_and_page_file_is_served(name):
    manifest = json.loads((SNAPSHOT_DIR / name / "snapshot.json").read_text())
    assert manifest["version"] == int(name[1:])
    files = [*manifest["page_files"], *manifest["routes"].values(), "snapshot.js"]
    for file in files:
        status, _, body = call(f"/{name}/{file}")
        assert status == 200, file
        assert body == (SNAPSHOT_DIR / name / file).read_bytes(), file
    shim = (SNAPSHOT_DIR / name / "snapshot.js").read_text()
    for route, file in manifest["routes"].items():
        assert json.dumps(route) + ": " + json.dumps(file) in shim, route


def test_every_snapshot_shows_a_real_record():
    """Version 1 opens a recorded run; every later version has a recorded sample run."""
    for name in VERSIONS:
        manifest = json.loads((SNAPSHOT_DIR / name / "snapshot.json").read_text())
        if manifest["open_run"]:
            assert any(manifest["open_run"] in route for route in manifest["routes"]), name
        else:
            assert "sample-run.json" in manifest["page_files"], name


@pytest.mark.parametrize("path", ["/v99/", "/v99", "/v1x/", "/versions/x", "/v1/../main.py"])
def test_unknown_paths_are_not_served(path):
    status, _, _ = call(path)
    assert status == 404
