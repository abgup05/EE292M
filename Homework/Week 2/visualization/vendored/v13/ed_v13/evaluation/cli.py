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
- ``plan --cassette DIR [--out eval/queries.json]``: ask the planner, through the
  cassette, for every case's retrieval queries; write the queries file when every
  request is answered, otherwise list what is pending and exit 3.
- ``generate --cassette DIR --queries FILE [--out eval/results] [--check]``: assess
  every case through the cassette, gate it and score the answers; exit 3 while any
  assess request is pending, writing nothing. ``--check`` also runs the meaning check
  on every case's verified findings and adds its scores (``generation-checked-*``).
- ``mismatch --cassette DIR --queries FILE [--findings-cassette DIR] [--out eval/results]``:
  replay the golden generation run read-only from ``--findings-cassette`` (default
  ``eval/cassettes/golden``), plant mismatches (each verified finding's statement with
  another finding's quotes) and put them to the meaning checker through ``--cassette``;
  exit 3 while any check request is pending, writing nothing (``mismatch-*``).

``plan``, ``generate`` and ``fetch`` pin each company's CIK and name, and
``generate`` and ``fetch`` its XBRL facts, in ``eval/filings.json`` the first time.

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
from dataclasses import dataclass
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any

from ed_v13.core.documents import Document
from ed_v13.core.models import Company
from ed_v13.core.ports import SourceError
from ed_v13.evaluation.companies import (
    CompanyFigures,
    company_for,
    figures_for,
    pin_companies,
    read_facts,
)
from ed_v13.evaluation.corpus import (
    CACHE_DIR,
    EVAL_DIR,
    FILINGS_PATH,
    Corpus,
    CorpusError,
    Fetch,
    PinnedFiling,
    load_facts_pins,
    load_pins,
    save_pins,
    sha256_hex,
)
from ed_v13.evaluation.generation_eval import run_generation
from ed_v13.evaluation.golden import (
    GOLDEN_PATH,
    GoldenCase,
    Target,
    Validation,
    heading_matches,
    read_golden,
    render_validation,
    validate_golden,
)
from ed_v13.evaluation.mismatch_eval import run_mismatch
from ed_v13.evaluation.planning import run_plan
from ed_v13.evaluation.retrieval_eval import (
    VARIANTS,
    build_record,
    evaluate,
    get_variant,
    read_queries_file,
    render_markdown,
    write_record,
)
from ed_v13.sources.edgar import EdgarClient

COMMANDS = ("validate", "run", "fetch", "pin", "show", "plan", "generate", "mismatch")
GLOBAL_OPTIONS_WITH_VALUE = ("--golden", "--filings")
RESULTS_DIR = EVAL_DIR / "results"
QUERIES_PATH = EVAL_DIR / "queries.json"
CASSETTE_DIR = EVAL_DIR / "cassettes" / "golden"
MISMATCH_CASSETTE_DIR = EVAL_DIR / "cassettes" / "mismatch"


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="python -m app.evaluation", description=__doc__)
    parser.add_argument("--golden", type=Path, default=GOLDEN_PATH, help="the golden set")
    parser.add_argument("--filings", type=Path, default=FILINGS_PATH, help="the pinned filings")
    parser.add_argument("--offline", action="store_true", help="never contact EDGAR")
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("validate", help="check every golden case")
    run = commands.add_parser("run", help="validate, then score retrieval")
    run.add_argument("--variant", default="claim", choices=sorted(VARIANTS))
    run.add_argument("--queries", type=Path, help="a queries file, as plan writes it")
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
    plan = commands.add_parser("plan", help="model-written queries for every case")
    plan.add_argument("--cassette", type=Path, default=CASSETTE_DIR, help="the cassette")
    plan.add_argument("--out", type=Path, default=QUERIES_PATH, help="the queries file")
    generate = commands.add_parser("generate", help="assess every case and score the answers")
    generate.add_argument("--cassette", type=Path, default=CASSETTE_DIR, help="the cassette")
    generate.add_argument("--queries", type=Path, default=QUERIES_PATH, help="from plan")
    generate.add_argument("--out", type=Path, default=RESULTS_DIR, help="where the record goes")
    generate.add_argument(
        "--check",
        action="store_true",
        help="also run the meaning check on every case's verified findings, through the cassette",
    )
    mismatch = commands.add_parser(
        "mismatch", help="plant quote mismatches and see whether the meaning check rejects them"
    )
    mismatch.add_argument(
        "--cassette",
        type=Path,
        default=MISMATCH_CASSETTE_DIR,
        help="the cassette the mismatch checks are answered from",
    )
    mismatch.add_argument(
        "--findings-cassette",
        type=Path,
        default=CASSETTE_DIR,
        help="the golden run's cassette, replayed read-only for the findings",
    )
    mismatch.add_argument("--queries", type=Path, default=QUERIES_PATH, help="from plan")
    mismatch.add_argument("--out", type=Path, default=RESULTS_DIR, help="where the record goes")
    return parser


def normalize_argv(argv: Sequence[str]) -> list[str]:
    """Drop the ``run`` that ``make eval`` puts before another command name."""
    args = list(argv)
    position = next((n for n, arg in enumerate(args) if not arg.startswith("-")), None)
    if position is None or args[position] != "run":
        return args
    following = position + 1
    while following < len(args) and args[following].startswith("-"):
        # Global options may come between: --offline, and --golden/--filings with a value.
        following += 2 if args[following] in GLOBAL_OPTIONS_WITH_VALUE else 1
    if following < len(args) and args[following] in COMMANDS:
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
        book, _ = read_queries_file(args.queries, {case.id for case, _ in cases})
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


def _companies(
    args: argparse.Namespace, corpus: Corpus, client: EdgarClient | None, tickers: list[str]
) -> dict[str, Company]:
    """Each ticker's pinned company, looked up through EDGAR and pinned the first time."""
    pins, changed = pin_companies(tickers, corpus.pins, client.company if client else None)
    if changed:
        corpus.pins = pins
        save_pins(pins.values(), args.filings)
        print(f"pinned the CIK and name of {', '.join(changed)} in {_display(args.filings)}")
    return {ticker: company_for(ticker, pins) for ticker in tickers}


def _figures(
    args: argparse.Namespace, companies: dict[str, Company], client: EdgarClient | None
) -> dict[str, CompanyFigures]:
    """Each company's reported figures from its pinned facts, pinning facts read the first time."""
    pinned = load_facts_pins(args.filings)
    figures: dict[str, CompanyFigures] = {}
    added: list[str] = []
    for ticker, company in companies.items():
        facts = read_facts(
            ticker,
            company,
            pinned.get(ticker),
            cache_dir=CACHE_DIR,
            fetch=client.get if client else None,
        )
        if facts.pin is not None and ticker not in pinned:
            pinned[ticker] = facts.pin
            added.append(ticker)
        figures[ticker] = figures_for(facts)
        print(f"facts: {ticker}: {figures[ticker].note}")
    if added:
        save_pins(load_pins(args.filings).values(), args.filings, facts=pinned)
        print(f"pinned the XBRL facts of {', '.join(added)} in {_display(args.filings)}")
    return figures


def _tickers(cases: list[GoldenCase]) -> list[str]:
    return list(dict.fromkeys(case.ticker for case in cases))


def _golden_inputs(args: argparse.Namespace, golden_sha: str) -> dict[str, str]:
    return {
        "golden_file": _display(args.golden),
        "golden_sha256": golden_sha,
        "filings_sha256": sha256_hex(args.filings.read_bytes()),
    }


def cmd_plan(args: argparse.Namespace, corpus: Corpus, client: EdgarClient | None) -> int:
    """Plan every case's queries through the cassette; 3 while any request is pending."""
    validation, golden_sha = _validate(args.golden, corpus)
    if not validation.ok:
        print(render_validation(validation))
        print("plan: the golden set does not validate; nothing was asked")
        return 1
    cases = [case for case, _ in validation.cases()]
    companies = _companies(args, corpus, client, _tickers(cases))
    inputs = _golden_inputs(args, golden_sha)
    return run_plan(cases, companies, args.cassette, args.out, inputs=inputs)


@dataclass
class _GenerationSetup:
    """What a one-claim-per-case run of the golden set needs, checked and pinned."""

    cases: list[tuple[GoldenCase, list[Target]]]
    book: dict[str, list[str]]
    companies: dict[str, Company]
    figures: dict[str, CompanyFigures]
    inputs: dict[str, Any]


def _generation_setup(
    args: argparse.Namespace, corpus: Corpus, client: EdgarClient | None
) -> _GenerationSetup | None:
    """Validate, read the queries planned for this golden set, pin companies and facts.

    Prints why and returns None when the golden set does not validate or the
    queries were planned for another one.
    """
    validation, golden_sha = _validate(args.golden, corpus)
    if not validation.ok:
        print(render_validation(validation))
        print(f"{args.command}: the golden set does not validate; nothing was asked")
        return None
    cases = validation.cases()
    book, provenance = read_queries_file(args.queries, {case.id for case, _ in cases})
    planned_for = (provenance or {}).get("golden_sha256")
    if planned_for != golden_sha:
        print(
            f"{args.command}: {_display(args.queries)} was not planned for this golden set "
            f"(planned for {str(planned_for)[:12]}, golden is {golden_sha[:12]}); run plan again"
        )
        return None
    golden_cases = [case for case, _ in cases]
    companies = _companies(args, corpus, client, _tickers(golden_cases))
    figures = _figures(args, companies, client)
    inputs = {
        **_golden_inputs(args, golden_sha),
        "queries_file": _display(args.queries),
        "queries_sha256": sha256_hex(args.queries.read_bytes()),
        "queries_planned_by": (provenance or {}).get("cassette_description"),
    }
    return _GenerationSetup(cases, book, companies, figures, inputs)


def cmd_generate(args: argparse.Namespace, corpus: Corpus, client: EdgarClient | None) -> int:
    """Assess and score every case through the cassette; 3 while any request is pending."""
    setup = _generation_setup(args, corpus, client)
    if setup is None:
        return 1
    return run_generation(
        setup.cases,
        corpus.load_filing,
        setup.book,
        setup.companies,
        setup.figures,
        cassette=args.cassette,
        out_dir=args.out,
        inputs={**setup.inputs, "cassette": _display(args.cassette)},
        check=args.check,
        filing_periods={
            pin.accession: date.fromisoformat(pin.period_end) for pin in corpus.pins.values()
        },
    )


def cmd_mismatch(args: argparse.Namespace, corpus: Corpus, client: EdgarClient | None) -> int:
    """Plant quote mismatches in the golden run's findings; 3 while any check is pending."""
    setup = _generation_setup(args, corpus, client)
    if setup is None:
        return 1
    inputs = {
        **setup.inputs,
        "findings_cassette": _display(args.findings_cassette),
        "cassette": _display(args.cassette),
    }
    return run_mismatch(
        setup.cases,
        corpus.load_filing,
        setup.book,
        setup.companies,
        setup.figures,
        findings_cassette=args.findings_cassette,
        cassette=args.cassette,
        out_dir=args.out,
        inputs=inputs,
    )


def cmd_fetch(args: argparse.Namespace, corpus: Corpus, client: EdgarClient | None) -> int:
    """Read every pinned filing and company's facts; 0 when all filings matched their pins."""
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
    tickers = sorted({pin.ticker for pin in corpus.pins.values()})
    try:
        _figures(args, _companies(args, corpus, client, tickers), client)
    except CorpusError as exc:
        print(f"fetch: company facts FAILED: {exc}")
        failures += 1
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
            cik=company.cik,
            name=company.name,
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
        return cmd_fetch(args, corpus, client)
    if args.command == "plan":
        return cmd_plan(args, corpus, client)
    if args.command == "generate":
        return cmd_generate(args, corpus, client)
    if args.command == "mismatch":
        return cmd_mismatch(args, corpus, client)
    if args.command == "pin":
        return cmd_pin(args, corpus, client)
    if args.command == "show":
        return cmd_show(args, corpus.load_filing(args.ticker.upper(), args.accession))
    raise AssertionError(f"unhandled command {args.command}")  # pragma: no cover
