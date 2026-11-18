"""Fail if an exported website file looks like it holds a secret or personal data.

Every file under the given paths is read as text (undecodable bytes are replaced, so a binary
file is scanned too) and checked line by line against the patterns below. A finding prints
the file, the line, the pattern's name and a masked excerpt, never the matched text whole.
Exit status 1 if anything is found, 2 if a path does not exist. Run it as ``make site-scan``.
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

PATTERNS: dict[str, re.Pattern[str]] = {
    "Anthropic key prefix (sk-ant)": re.compile(r"sk-ant", re.IGNORECASE),
    "other API key shape (sk-, ghp_, github_pat_, AKIA, xox)": re.compile(
        r"\b(?:sk-[A-Za-z0-9_-]{20,}|ghp_[A-Za-z0-9]{20,}|github_pat_[A-Za-z0-9_]{20,}"
        r"|AKIA[0-9A-Z]{16}|xox[abpr]-[A-Za-z0-9-]{10,})"
    ),
    "private key block": re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----"),
    "key assignment (…_API_KEY=, …_TOKEN=, …_SECRET=)": re.compile(
        r"[A-Z0-9_]*(?:API_KEY|TOKEN|SECRET|PASSWORD)\s*[=:]\s*[\"']?[A-Za-z0-9_\-]{8,}"
    ),
    "email address": re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9-]+(?:\.[A-Za-z0-9-]+)*\.[A-Za-z]{2,}"),
    "User-Agent string": re.compile(r"user[-_ ]?agent", re.IGNORECASE),
    "absolute path under /Users/": re.compile(r"/Users/"),
    "absolute path under /home/": re.compile(r"/home/[a-z]"),
}


def mask(text: str) -> str:
    """A short excerpt with letters and digits after the first four replaced by '*'."""
    text = text.strip()[:60]
    return text[:4] + re.sub(r"[A-Za-z0-9]", "*", text[4:])


def scan_file(path: Path) -> list[str]:
    """Every finding in one file, as printable lines."""
    findings = []
    text = path.read_bytes().decode("utf-8", errors="replace")
    for number, line in enumerate(text.splitlines(), start=1):
        for name, pattern in PATTERNS.items():
            match = pattern.search(line)
            if match:
                start = max(match.start() - 10, 0)
                findings.append(f"{path}:{number}: {name}: {mask(line[start : match.end() + 10])}")
    return findings


def files_under(paths: list[Path]) -> list[Path]:
    """Every regular file named or under a named directory, sorted."""
    found: list[Path] = []
    for path in paths:
        if path.is_file():
            found.append(path)
        else:
            found.extend(p for p in path.rglob("*") if p.is_file())
    return sorted(found)


def main(argv: list[str]) -> int:
    paths = [Path(arg) for arg in argv]
    missing = [str(p) for p in paths if not p.exists()]
    if not paths or missing:
        print(f"Usage: scan.py PATH...; missing: {', '.join(missing) or 'none given'}", file=sys.stderr)
        return 2
    files = files_under(paths)
    findings = [finding for path in files for finding in scan_file(path)]
    size = sum(p.stat().st_size for p in files)
    for finding in findings:
        print(finding)
    print(
        f"Scanned {len(files)} files ({size:,} bytes) under {', '.join(map(str, paths))} "
        f"for {len(PATTERNS)} patterns: {len(findings)} findings."
    )
    return 1 if findings else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
