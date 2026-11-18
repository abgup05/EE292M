"""Command line of the retrieval evaluation (``python -m app.evaluation``).

Commands:

- ``validate``: check every golden case; print a table; exit 1 on any failure.
- ``run [--variant claim] [--queries FILE] [--out eval/results]``: validate, score
  retrieval, print the summary and per-case table, write the JSON and Markdown record.
- ``fetch``: fill ``eval/cache`` with every pinned filing not in the fixtures.
- ``pin TICKER [ACCESSION ...]``: pin filings in ``eval/filings.json`` (default: the
  latest 10-K and the newest 10-Q filed after it).
- ``show TICKER ACCESSION [SECTION] [--grep REGEX] [--text]``: print a filing's outline,
  one section, matching lines, or the whole stored text, for drafting cases.

``make eval ARGS="..."`` runs ``python -m app.evaluation run ...``, so a leading
``run`` followed by another command name is dropped: ``make eval ARGS="fetch"``
fetches and ``make eval ARGS="run --variant claim"`` scores. (While ``eval`` is not
in the Makefile's ``.PHONY``, the ``eval/`` directory masks the target; use ``make -B``.)
"""

from __future__ import annotations

import argparse
import hashlib
import re
import sys
from collections.abc import Sequence
from datetime import UTC, datetime
from pathlib import Path

from ed_v4.core.documents import Document
from ed_v4.core.ports import SourceError
from ed_v4.evaluation.corpus import (
    CACHE_DIR,
    EVAL_DIR,
    FILINGS_PATH,
    Corpus,
    CorpusError,
    Fetch,
    PinnedFiling,
    load_pins,
    save_pins,
    sha256_hex,
)
from ed_v4.evaluation.golden import (
    GOLDEN_PATH,
    Validation,
    heading_matches,
    read_golden,
    render_validation,
    validate_golden,
)
from ed_v4.evaluation.retrieval_eval import (
    VARIANTS,
    build_record,
    evaluate,
    get_variant,
    read_queries,
    render_markdown,
    write_record,
)
from ed_v4.sources.edgar import EdgarClient

COMMANDS = ("validate", "run", "fetch", "pin", "show")
RESULTS_DIR = EVAL_DIR / "results"


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="python -m app.evaluation", description=__doc__)
    parser.add_argument("--golden", type=Path, default=GOLDEN_PATH, help="the golden set")
    parser.add_argument("--filings", type=Path, default=FILINGS_PATH, help="the pinned filings")
    parser.add_argument("--offline", action="store_true", help="never contact EDGAR")
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("validate", help="check every golden case")
    run = commands.add_parser("run", help="validate, then score retrieval")
    run.add_argument("--variant", default="claim", choices=sorted(VARIANTS))
    run.add_argument("--queries", type=Path, help="JSON {case_id: [query, ...]}")
    run.add_argument("--out", type=Path, default=RESULTS_DIR, help="where the record goes")
    commands.add_parser("fetch", help="cache every pinned filing not in the fixtures")
    pin = commands.add_parser("pin", help="pin a company's filings in eval/filings.json")
    pin.add_argument("ticker")
    pin.add_argument("accessions", nargs="*", help="default: latest 10-K and newest 10-Q")
    show = commands.add_parser("show", help="print a filing's outline, a section or lines")
    show.add_argument("ticker")
    show.add_argument("accession")
    show.add_argument("section", nargs="?", default="", help="a heading prefix, e.g. 'Item 1A'")
    show.add_argument("--grep", help="print only lines matching this regex (case-insensitive)")
    show.add_argument("--text", action="store_true", help="print the whole stored text")
    return parser


def normalize_argv(argv: Sequence[str]) -> list[str]:
    """Drop the ``run`` that ``make eval`` puts before another command name."""
    args = list(argv)
    position = next((n for n, arg in enumerate(args) if not arg.startswith("-")), None)
    if (
        position is not None
        and args[position] == "run"
        and position + 1 < len(args)
        and args[position + 1] in COMMANDS
    ):
        del args[position]
    return args


def _validate(golden: Path, corpus: Corpus) -> tuple[Validation, str]:
    raw, digest = read_golden(golden)
    return validate_golden(raw, corpus.load_filing), digest


def cmd_validate(args: argparse.Namespace, corpus: Corpus) -> int:
    """Print the validation table; 0 when every case passed."""
    validation, _ = _validate(args.golden, corpus)
    print(render_validation(validation))
    return 0 if validation.ok else 1


def cmd_run(args: argparse.Namespace, corpus: Corpus) -> int:
    """Validate, score one variant, print the report and write its record."""
    variant = get_variant(args.variant)
    validation, golden_sha = _validate(args.golden, corpus)
    if not validation.ok:
        print(render_validation(validation))
        print("run: the golden set does not validate; nothing was scored")
        return 1
    cases = validation.cases()
    book: dict[str, list[str]] = {}
    queries_sha = None
    if args.queries is not None:
        book = read_queries(args.queries, {case.id for case, _ in cases})
        queries_sha = sha256_hex(args.queries.read_bytes())
    elif variant.needs_queries:
        print(f"run: variant {variant.name!r} needs --queries FILE")
        return 2
    results = evaluate(cases, corpus.load_filing, variant.name, book)
    now = datetime.now(UTC)
    unanswerable = [case.id for case, _ in cases if case.kind == "unanswerable"]
    inputs = {
        "golden_file": _display(args.golden),
        "golden_version": validation.version,
        "golden_status": validation.status,
        "golden_sha256": golden_sha,
        "filings_sha256": sha256_hex(args.filings.read_bytes()),
        "queries_file": _display(args.queries) if args.queries else None,
        "queries_sha256": queries_sha,
        "cases_total": len(cases),
        "cases_answerable": len(cases) - len(unanswerable),
        "cases_unanswerable": len(unanswerable),
    }
    record = build_record(
        results, variant=variant.name, inputs=inputs, unanswerable=unanswerable, generated_at=now
    )
    markdown = render_markdown(record, results)
    json_path, md_path = write_record(record, markdown, args.out, variant.name, now)
    print(markdown)
    print(f"run: wrote {_display(json_path)} and {_display(md_path)}")
    return 0


def cmd_fetch(corpus: Corpus) -> int:
    """Read every pinned filing (fixture, cache or EDGAR); 0 when all matched their pins."""
    failures = 0
    for pin in sorted(corpus.pins.values(), key=lambda p: (p.ticker, p.period_end)):
        try:
            body, origin = corpus.original(pin)
        except CorpusError as exc:
            print(f"fetch: {pin.ticker} {pin.accession} FAILED: {exc}")
            failures += 1
            continue
        print(
            f"fetch: {pin.ticker} {pin.form} {pin.period_end} {pin.accession}: "
            f"{len(body):,} bytes from {origin}, hash matches pin"
        )
    print(f"fetch: {len(corpus.pins) - failures} of {len(corpus.pins)} pinned filing(s) ready")
    return 1 if failures else 0


def cmd_pin(args: argparse.Namespace, corpus: Corpus, client: EdgarClient | None) -> int:
    """Pin filings of one company from EDGAR's index, hashing the original HTML."""
    if client is None:
        print("pin: needs EDGAR; drop --offline")
        return 2
    company = client.company(args.ticker)
    refs = client.periodic_filings(company, 5)
    if args.accessions:
        chosen = [ref for ref in refs if ref.accession in args.accessions]
        missing = set(args.accessions) - {ref.accession for ref in chosen}
        if missing:
            print(f"pin: not among {company.ticker}'s current periodic filings: {sorted(missing)}")
            return 1
    else:
        annual = [ref for ref in refs if ref.form == "10-K"][:1]
        quarterly = [ref for ref in refs if ref.form == "10-Q"][:1]
        chosen = quarterly + annual
    pins = dict(corpus.pins)
    for ref in chosen:
        body = corpus.recorded(ref.url)
        origin = "fixture"
        if body is None:
            body, origin = client.get(ref.url), "edgar"
            corpus.write_cache(ref.accession, body)
        pin = PinnedFiling(
            ticker=company.ticker.upper().replace(".", "-"),
            accession=ref.accession,
            form=ref.form,  # type: ignore[arg-type]
            period_end=ref.period_end,
            filed_date=ref.filed_date,
            url=ref.url,
            sha256=hashlib.sha256(body).hexdigest(),
        )
        pins[pin.accession] = pin
        print(f"pin: {pin.ticker} {pin.form} {pin.period_end} {pin.accession} ({origin})")
    save_pins(pins.values(), args.filings)
    print(f"pin: wrote {_display(args.filings)} ({len(pins)} filing(s))")
    return 0


def cmd_show(args: argparse.Namespace, document: Document) -> int:
    """Print the outline, a section, matching lines, or the whole text of one filing."""
    if args.text:
        print(document.text)
        return 0
    pattern = re.compile(args.grep, re.IGNORECASE) if args.grep else None
    if not args.section and pattern is None:
        for section in document.sections:
            print(f"{len(section.text):8,d}  {section.heading}")
        return 0
    shown = 0
    for section in document.sections:
        if args.section and not heading_matches(section.heading, args.section):
            continue
        if pattern is None:
            print(f"## {section.heading}\n{section.text}\n")
            shown += 1
            continue
        for line in section.text.split("\n"):
            if pattern.search(line):
                print(f"[{section.heading}]\n{line}\n")
                shown += 1
    print(f"show: {shown} match(es)", file=sys.stderr)
    return 0


def _display(path: Path) -> str:
    try:
        return str(path.resolve().relative_to(EVAL_DIR.parent))
    except ValueError:
        return str(path)


def main(argv: Sequence[str] | None = None) -> int:
    """Parse the command line and run one command; returns the exit status."""
    args = _parser().parse_args(normalize_argv(sys.argv[1:] if argv is None else argv))
    try:
        pins = load_pins(args.filings) if args.filings.exists() or args.command != "pin" else {}
        if args.offline:
            return _dispatch(args, Corpus(pins, cache_dir=CACHE_DIR), None)
        with EdgarClient.from_env() as client:
            fetch: Fetch = client.get
            return _dispatch(args, Corpus(pins, cache_dir=CACHE_DIR, fetch=fetch), client)
    except (CorpusError, SourceError, ValueError) as exc:
        print(f"{args.command}: error: {exc}", file=sys.stderr)
        return 1


def _dispatch(args: argparse.Namespace, corpus: Corpus, client: EdgarClient | None) -> int:
    if args.command == "validate":
        return cmd_validate(args, corpus)
    if args.command == "run":
        return cmd_run(args, corpus)
    if args.command == "fetch":
        return cmd_fetch(corpus)
    if args.command == "pin":
        return cmd_pin(args, corpus, client)
    if args.command == "show":
        return cmd_show(args, corpus.load_filing(args.ticker.upper(), args.accession))
    raise AssertionError(f"unhandled command {args.command}")  # pragma: no cover
