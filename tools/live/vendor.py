"""Vendor tagged Evidence Desk versions into the website, each under its own package name.

Every version's Python package is called ``app``, as is the Week 2 app's, so one process can
hold only one of them under that name. ``make site-vendor`` therefore copies each version's
``Capstone/evidence_desk/src`` (read from git as a tar on standard input, never from a
working tree) into ``OUT/vN/`` with one mechanical change: the package ``app`` becomes
``ed_vN``. Only two kinds of token are rewritten, each listed in ``OUT/vN/VENDORED.json``:

- in an ``import`` or ``from`` statement, a dotted module name that starts with ``app``;
- a string literal whose whole text names the package or one of its modules (``"app."``,
  ``"app.watch"``), because the code compares module names (``__module__.startswith``).

``"app.js"`` and every other string, comment and docstring are left alone. Nothing else in
the source changes; the web files are copied byte for byte.

``seed`` writes the EDGAR seed (``OUT/seed/``) from a tar of a version's
``tests/fixtures``: the recorded EDGAR answers that version's tests read, each with its URL,
its retrieval time and whether the recording is whole or was trimmed when it was recorded.

``prune`` removes ``OUT/vN`` for every version no longer in the map. Standard library only.
"""

from __future__ import annotations

import argparse
import gzip
import hashlib
import io
import json
import re
import shutil
import sys
import tarfile
import tokenize
from dataclasses import dataclass, field
from pathlib import Path, PurePosixPath

OLD = "app"
SOURCE_ROOT = PurePosixPath("Capstone/evidence_desk/src")
FIXTURE_ROOT = PurePosixPath("Capstone/evidence_desk/tests/fixtures")
VERSION_DIR = re.compile(r"v([0-9]{1,3})")
STRING_PREFIX = re.compile(r"^([rRbBuU]{0,2})('''|\"\"\"|'|\")")
DOTTED = re.compile(r"^app(?:\.[A-Za-z_][A-Za-z0-9_]*)*\.?$")


class VendorError(RuntimeError):
    """The version could not be vendored as asked; nothing is written for it."""


@dataclass
class Renamed:
    """What the rename changed in one file."""

    imports: int = 0
    strings: list[str] = field(default_factory=list)


def package_name(version: int) -> str:
    """The name version ``version``'s package has in the website: ``ed_v14``."""
    return f"ed_v{version}"


def module_names(paths: list[PurePosixPath]) -> set[str]:
    """Every dotted module name under the package, relative to it (``core``, ``core.models``)."""
    names: set[str] = set()
    for path in paths:
        if path.suffix != ".py":
            continue
        parts = list(path.with_suffix("").parts)
        if parts[-1] == "__init__":
            parts = parts[:-1]
        for end in range(1, len(parts) + 1):
            names.add(".".join(parts[:end]))
    return names


def _names_module(text: str, modules: set[str]) -> bool:
    """True when ``text`` ("app.", "app.watch") names the package or one of its modules."""
    if not DOTTED.fullmatch(text):
        return False
    rest = text[len(OLD) :].strip(".")
    return rest == "" or rest in modules


def rename(source: str, new: str, modules: set[str]) -> tuple[str, Renamed]:
    """``source`` with the package ``app`` renamed to ``new`` in imports and module-name strings."""
    report = Renamed()
    edits: list[tuple[int, int, int, str]] = []  # (row, start column, end column, text)
    tokens = list(tokenize.generate_tokens(io.StringIO(source).readline))
    statement: str | None = None  # "import" or "from" while inside such a statement
    previous: tokenize.TokenInfo | None = None
    for token in tokens:
        if token.type in (tokenize.NEWLINE, tokenize.ENDMARKER):
            statement = None
        elif token.type == tokenize.NAME and statement is None and token.string in ("import", "from"):
            first = previous is None or previous.type in (
                tokenize.NEWLINE,
                tokenize.NL,
                tokenize.INDENT,
                tokenize.DEDENT,
            ) or (previous.type == tokenize.OP and previous.string == ";")
            if first:
                statement = token.string
        elif token.type == tokenize.NAME and token.string == "import" and statement == "from":
            statement = "from-names"  # what follows names objects, not modules
        elif (
            token.type == tokenize.NAME
            and token.string == OLD
            and previous is not None
            and (
                (statement == "from" and previous.string == "from")
                or (statement == "import" and previous.string in ("import", ","))
            )
        ):
            if token.start[0] != token.end[0]:
                raise VendorError("an import name spans lines")
            edits.append((token.start[0], token.start[1], token.end[1], new))
            report.imports += 1
        elif token.type == tokenize.STRING:
            match = STRING_PREFIX.match(token.string)
            if match and "b" not in match.group(1).lower() and token.start[0] == token.end[0]:
                quote = match.group(2)
                body = token.string[match.end() : len(token.string) - len(quote)]
                if _names_module(body, modules):
                    renamed = new + body[len(OLD) :]
                    text = token.string[: match.end()] + renamed + quote
                    edits.append((token.start[0], token.start[1], token.end[1], text))
                    report.strings.append(f"{body} -> {renamed}")
        if token.type not in (tokenize.COMMENT, tokenize.NL):
            previous = token
    lines = source.splitlines(keepends=True)
    for row, start, end, text in sorted(edits, reverse=True):
        line = lines[row - 1]
        lines[row - 1] = line[:start] + text + line[end:]
    return "".join(lines), report


def _members(archive: tarfile.TarFile, root: PurePosixPath) -> dict[PurePosixPath, bytes]:
    """Every regular file under ``root`` in the archive, by its path relative to ``root``."""
    files: dict[PurePosixPath, bytes] = {}
    for member in archive.getmembers():
        path = PurePosixPath(member.name)
        if not member.isfile() or root not in path.parents:
            continue
        relative = path.relative_to(root)
        if any(part in ("..", "") or part.startswith("__pycache__") for part in relative.parts):
            raise VendorError(f"refusing the archive member {member.name!r}")
        extracted = archive.extractfile(member)
        if extracted is None:
            raise VendorError(f"cannot read {member.name!r}")
        files[relative] = extracted.read()
    return files


def vendor(version: int, ref: str, commit: str, archive: tarfile.TarFile, out: Path) -> dict:
    """Write ``out/vN`` from the archive of the version's ``src``; return its manifest."""
    files = _members(archive, SOURCE_ROOT)
    package_files = {p.relative_to(OLD): b for p, b in files.items() if p.parts[0] == OLD}
    web_files = {p.relative_to("web"): b for p, b in files.items() if p.parts[0] == "web"}
    others = sorted(str(p) for p in files if p.parts[0] not in (OLD, "web"))
    if not package_files or "index.html" not in {str(p) for p in web_files}:
        raise VendorError(f"{ref} has no src/{OLD} package or no src/web/index.html")
    if others:
        raise VendorError(f"{ref} has files under src/ that are not app/ or web/: {others}")
    new = package_name(version)
    modules = module_names(list(package_files))
    staging = out / f".v{version}.partial"
    if staging.exists():
        shutil.rmtree(staging)
    renamed_imports = 0
    renamed_strings: dict[str, list[str]] = {}
    for path, body in sorted(package_files.items()):
        target = staging / new / Path(*path.parts)
        target.parent.mkdir(parents=True, exist_ok=True)
        if path.suffix == ".py":
            text, report = rename(body.decode("utf-8"), new, modules)
            renamed_imports += report.imports
            if report.strings:
                renamed_strings[str(path)] = report.strings
            target.write_text(text, encoding="utf-8")
        else:
            target.write_bytes(body)
    for path, body in sorted(web_files.items()):
        target = staging / "web" / Path(*path.parts)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(body)
    manifest = {
        "version": version,
        "ref": ref,
        "commit": commit,
        "package": new,
        "python_files": sum(1 for p in package_files if p.suffix == ".py"),
        "web_files": sorted(str(p) for p in web_files),
        "renamed_imports": renamed_imports,
        "renamed_strings": renamed_strings,
    }
    (staging / "VENDORED.json").write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n")
    target_dir = out / f"v{version}"
    if target_dir.exists():
        shutil.rmtree(target_dir)
    staging.rename(target_dir)
    return manifest


def _content_type(url: str) -> str:
    return "application/json" if url.endswith(".json") else "text/html"


def seed(ref: str, commit: str, archive: tarfile.TarFile, out: Path) -> list[dict]:
    """Write ``out/seed`` from the archive of a version's ``tests/fixtures``; return its entries.

    Each recorded answer is stored gzip-compressed under its fixture name. ``whole`` is true
    when the stored bytes hash to the SHA-256 the recording noted for the original answer, so
    a trimmed recording (SEC's company list cut to a few tickers, an index cut to its newest
    rows, company facts cut to a few concepts) is marked and never passed off as whole.
    """
    files = _members(archive, FIXTURE_ROOT)
    edgar = {str(p.relative_to("edgar")): b for p, b in files.items() if p.parts[0] == "edgar"}
    manifest = json.loads(edgar.get("manifest.json", b"{}"))
    facts = json.loads(edgar.get("facts-manifest.json", b"[]"))
    entries: list[dict] = []
    recorded: list[tuple[str, bytes, dict]] = []
    for name, info in manifest.items():
        recorded.append((name, edgar[name], {"url": info["url"], "retrieved_at": info["retrieved_at"],
                                             "sha256": info["sha256"]}))
    for info in facts:
        recorded.append((info["file"], edgar[info["file"]], {"url": info["url"],
                         "retrieved_at": info["retrieved_at"], "sha256": info["original_sha256"]}))
    pages = json.loads(files.get(PurePosixPath("manifest.json"), b"{}"))
    for key, info in pages.items():
        if isinstance(info, dict) and "requested_url" in info:
            name = f"{key}.html"
            # A page's recording notes its size, not the SHA-256 of its bytes.
            body = files[PurePosixPath(name)]
            same = hashlib.sha256(body).hexdigest() if len(body) == info["bytes"] else ""
            recorded.append((name, body, {"url": info["requested_url"],
                             "retrieved_at": info["retrieved_at"], "sha256": same}))
    staging = out / ".seed.partial"
    if staging.exists():
        shutil.rmtree(staging)
    staging.mkdir(parents=True)
    for name, stored, info in sorted(recorded, key=lambda item: item[2]["url"]):
        body = gzip.decompress(stored) if name.endswith(".gz") else stored
        file = name.removesuffix(".gz") + ".gz"
        (staging / file).write_bytes(gzip.compress(body, mtime=0))
        entries.append({
            "url": info["url"],
            "file": file,
            "content_type": _content_type(info["url"]) if not name.endswith(".html") else "text/html",
            "retrieved_at": info["retrieved_at"],
            "whole": hashlib.sha256(body).hexdigest() == info["sha256"],
            "bytes": len(body),
        })
    (staging / "seed.json").write_text(json.dumps(
        {"ref": ref, "commit": commit, "entries": entries}, indent=2, sort_keys=True) + "\n")
    target = out / "seed"
    if target.exists():
        shutil.rmtree(target)
    staging.rename(target)
    return entries


def prune(out: Path, keep: set[int]) -> list[str]:
    """Remove ``out/vN`` for every N not in ``keep``; return what was removed."""
    removed = []
    for path in sorted(out.iterdir()) if out.is_dir() else []:
        match = VERSION_DIR.fullmatch(path.name)
        if match and path.is_dir() and int(match.group(1)) not in keep:
            shutil.rmtree(path)
            removed.append(path.name)
    return removed


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    sub = parser.add_subparsers(dest="command", required=True)
    one = sub.add_parser("version", help="vendor one version from a tar of its src on stdin")
    one.add_argument("number", type=int)
    for command in (one, sub.add_parser("seed", help="write the EDGAR seed from a tar on stdin")):
        command.add_argument("--ref", required=True)
        command.add_argument("--commit", required=True)
        command.add_argument("--out", type=Path, required=True)
    trim = sub.add_parser("prune", help="remove versions no longer in the map")
    trim.add_argument("--out", type=Path, required=True)
    trim.add_argument("keep", type=int, nargs="*")
    args = parser.parse_args(argv)
    try:
        if args.command == "prune":
            for name in prune(args.out, set(args.keep)):
                print(f"removed {name}: it is no longer in the map")
            return 0
        archive = tarfile.open(fileobj=io.BytesIO(sys.stdin.buffer.read()), mode="r:")
        if args.command == "seed":
            entries = seed(args.ref, args.commit, archive, args.out)
            whole = sum(entry["whole"] for entry in entries)
            print(f"seed  {args.ref} ({args.commit[:7]}): {len(entries)} recorded answers, "
                  f"{whole} whole, {len(entries) - whole} trimmed when recorded")
            return 0
        manifest = vendor(args.number, args.ref, args.commit, archive, args.out)
    except (VendorError, KeyError, ValueError, OSError, tarfile.TarError) as error:
        print(f"FAILED: {error}", file=sys.stderr)
        return 1
    strings = sum(len(v) for v in manifest["renamed_strings"].values())
    print(f"v{manifest['version']:<3} {manifest['ref']} ({manifest['commit'][:7]}): "
          f"{manifest['python_files']} modules as {manifest['package']}, "
          f"{manifest['renamed_imports']} imports and {strings} module-name strings renamed, "
          f"{len(manifest['web_files'])} web files")
    return 0


if __name__ == "__main__":
    sys.exit(main())
