"""Check real HTTP responses after the container starts."""

import json
import time
import urllib.error
import urllib.request

ROOT = "http://127.0.0.1:8000"


def fetch_json(path: str) -> object:
    """Wait briefly for Uvicorn and fetch one JSON response."""
    for attempt in range(30):
        try:
            with urllib.request.urlopen(ROOT + path, timeout=3) as response:
                return json.load(response)
        except urllib.error.HTTPError:
            raise
        except urllib.error.URLError:
            if attempt == 29:
                raise
            time.sleep(0.25)
    raise RuntimeError("App did not start")


graph = fetch_json("/api/graph?focus=47")
assert graph["selected"]["id"] == "47" and len(graph["nodes"]) == 7
assert len(fetch_json("/api/sectors")) == 50
assert fetch_json("/api/search?q=VRT")[0]["ticker"] == "VRT"
with urllib.request.urlopen(ROOT + "/", timeout=3) as response:
    assert b"Dependency Explorer" in response.read()
print("Smoke: graph, sector list, search, and page returned expected content")
