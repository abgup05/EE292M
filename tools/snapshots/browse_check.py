"""Check one snapshot page as a headless browser rendered it (``make site-browse``).

Reads the DOM that Chromium's ``--dump-dom`` printed on standard input and checks that the
page carries its version's banner, that no call the page made on load went unanswered (the
shim's and the pages' own failure wordings), and that what should be shown is shown: version
1's recorded run on its page, the recorded sample run under ``?sample``. Prints one line and
exits 1 on a failure.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

FAILURE_WORDS = [
    "has no answer for",  # the shim: a GET the snapshot did not record
    "cannot start a run",  # the shim: something tried to start work
    "could not be reached",
    "could not load",
    "could not be loaded",
    "Could not load run",
    "not readable JSON",
]


def main(argv: list[str]) -> int:
    version, mode, snapshot_dir = int(argv[0]), argv[1], Path(argv[2])
    dom = sys.stdin.read()
    root = snapshot_dir / f"v{version}"
    manifest = json.loads((root / "snapshot.json").read_text())
    problems = []
    if f'data-snapshot-version="{version}"' not in dom:
        problems.append("no banner")
    problems += [f"says {word!r}" for word in FAILURE_WORDS if word in dom]
    shown = ""
    if mode == "sample":
        run_id = json.loads((root / "sample-run.json").read_text())["run"]["id"]
        shown = f"sample run {run_id}"
        if run_id not in dom:
            problems.append(f"the sample run {run_id} is not shown")
    elif manifest["open_run"]:
        shown = f"recorded run {manifest['open_run']}"
        if manifest["open_run"] not in dom and "PARTIAL" not in dom:
            problems.append("the recorded run is not shown")
    else:
        shown = "the page with its recorded meta, runs and theses"
    label = f"/v{version}/{'?sample' if mode == 'sample' else ''}"
    print(f"{'FAIL' if problems else 'ok  '}  {label:<14} {len(dom):>8,} bytes of DOM  {shown}"
          + (f": {'; '.join(problems)}" if problems else ""))
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
