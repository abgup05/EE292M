"""Write each pending cassette request as plain text, for whoever answers it.

``python -m tests.cassette_prompts <cassette> <out-dir>`` writes one
``<key>.txt`` per pending request: the system prompt, the user prompt and the
JSON schema, with real line breaks instead of JSON escapes.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path


def dump(cassette: Path, out: Path) -> list[Path]:
    """Write the plain-text prompt files and return their paths."""
    out.mkdir(parents=True, exist_ok=True)
    written: list[Path] = []
    for path in sorted((cassette / "pending").glob("*.json")):
        request = json.loads(path.read_text())
        text = (
            f"KEY: {request['key']}\nSTEP: {request['step']}\n\n"
            f"=== SYSTEM PROMPT ===\n{request['system']}\n\n"
            f"=== USER PROMPT ===\n{request['user']}\n\n"
            f"=== JSON SCHEMA THE ANSWER MUST SATISFY ===\n"
            f"{json.dumps(request['schema'], indent=2)}\n"
        )
        target = out / f"{request['key']}.txt"
        target.write_text(text)
        written.append(target)
    return written


if __name__ == "__main__":
    for item in dump(Path(sys.argv[1]), Path(sys.argv[2])):
        print(item)
