"""/versions and every capstone version are served (live or recorded); the Week 2 routes are unchanged."""

import asyncio
import json
import re

import pytest

from app.api import SNAPSHOT_DIR, WEB_DIR, app, live_names, recorded_names


def call(
    path: str, method: str = "GET", body: bytes = b"", headers: list | None = None
) -> tuple[int, dict[str, str], bytes]:
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
        "headers": [(b"host", b"testserver"), *(headers or [])],
        "client": ("127.0.0.1", 50000),
        "server": ("testserver", 80),
    }
    messages: list[dict] = []

    sent = False

    async def receive() -> dict:
        # The body once; after it the client stays connected and says nothing more (a
        # response that listens for a disconnect while it sends must not be given one).
        nonlocal sent
        if not sent:
            sent = True
            return {"type": "http.request", "body": body, "more_body": False}
        await asyncio.sleep(3600)
        return {"type": "http.disconnect"}

    async def send(message: dict) -> None:
        messages.append(message)

    asyncio.run(app(scope, receive, send))
    start = next(m for m in messages if m["type"] == "http.response.start")
    headers = {k.decode().lower(): v.decode() for k, v in start["headers"]}
    body = b"".join(m.get("body", b"") for m in messages if m["type"] == "http.response.body")
    return start["status"], headers, body


LIVE = live_names()
RECORDED = recorded_names()
EVERY = sorted(LIVE + RECORDED, key=lambda name: int(name[1:]))


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


def test_versions_are_present_in_version_order():
    assert EVERY, "no live or recorded version: run make site-vendor"
    assert EVERY[0] == "v1"
    assert EVERY == [f"v{n}" for n in range(1, len(EVERY) + 1)]


def test_versions_page_lists_every_version():
    status, headers, body = call("/versions")
    assert status == 200
    assert headers["content-type"].startswith("text/html")
    for name in EVERY:
        assert f'href="/{name}/"'.encode() in body, name


@pytest.mark.parametrize("name", EVERY)
def test_bare_version_path_leads_to_its_directory(name):
    status, headers, _ = call(f"/{name}")
    assert status == 307
    assert headers["location"] == f"/{name}/"


@pytest.mark.parametrize("name", LIVE)
def test_live_page_is_the_versions_own_with_a_banner_and_the_shim_first(name):
    status, headers, body = call(f"/{name}/")
    assert status == 200
    assert headers["content-type"].startswith("text/html")
    page = body.decode()
    number = name[1:]
    assert f'data-live-version="{number}"' in page
    assert f"Evidence Desk version {number} as tagged" in page
    assert "running live on a shared public server" in page
    assert "Runs and saved items are not kept" in page
    assert "Live runs need the app running locally" not in page
    assert 'href="/versions"' in page
    assert f"https://github.com/abgup05/EE292M/tree/capstone-v{number}" in page
    assert page.index('src="live-shim.js"') < page.index('src="app.js"')
    assert not re.search(r'(?:href|src)="/(?!versions")', page), "an absolute reference is left"


@pytest.mark.parametrize("name", RECORDED)
def test_recorded_snapshot_page_carries_its_banner_and_shim_before_its_script(name):
    status, headers, body = call(f"/{name}/")
    assert status == 200
    page = body.decode()
    assert f'data-snapshot-version="{name[1:]}"' in page
    assert page.index('src="snapshot.js"') < page.index('src="app.js"')


@pytest.mark.parametrize("name", RECORDED)
def test_every_recorded_answer_and_page_file_is_served(name):
    manifest = json.loads((SNAPSHOT_DIR / name / "snapshot.json").read_text())
    assert manifest["version"] == int(name[1:])
    files = [*manifest["page_files"], *manifest["routes"].values(), "snapshot.js"]
    for file in files:
        status, _, body = call(f"/{name}/{file}")
        assert status == 200, file
        assert body == (SNAPSHOT_DIR / name / file).read_bytes(), file


@pytest.mark.parametrize("path", ["/v99/", "/v99", "/v1x/", "/versions/x", "/v1/../main.py"])
def test_unknown_paths_are_not_served(path):
    status, _, _ = call(path)
    assert status == 404
