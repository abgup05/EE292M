"""The golden set: known thesis claims with the filing passage a correct answer must cite.

``eval/golden.json`` holds ``{"version": 1, "status": ..., "cases": [...]}``. Each
case names a company, the filings the claim is tested against, the claim in an
analyst's words, whether the filings can answer it, the stance a careful reader
would take, and (for answerable cases) one to three ``must_retrieve`` excerpts.

:func:`validate_golden` checks every case and collects every problem instead of
stopping at the first: the fields and their enums, unique ids, pinned filings,
and that each excerpt is located by :meth:`app.core.gate.TextIndex.locate` in
the named filing's stored text inside a section whose heading starts with the
stated prefix. The located span is kept: it is what the retrieval scorer
compares passages with.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Annotated, Any, Literal, Self

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    StringConstraints,
    ValidationError,
    model_validator,
)

from ed_v9.core import limits
from ed_v9.core.documents import Document
from ed_v9.core.gate import TextIndex
from ed_v9.evaluation.corpus import ACCESSION_PATTERN, EVAL_DIR, CorpusError

GOLDEN_PATH = EVAL_DIR / "golden.json"
GOLDEN_VERSION = 1
MIN_EXCERPT_CHARS = 60
MAX_EXCERPT_CHARS = 400
MAX_MUST_RETRIEVE = 3

Kind = Literal["answerable", "unanswerable"]
Expected = Literal["supports", "challenges", "mixed", "none"]
Loader = Callable[[str, str], Document]
Accession = Annotated[str, StringConstraints(pattern=ACCESSION_PATTERN)]


class MustRetrieve(BaseModel):
    """An exact excerpt a correct answer would have to cite, and where it sits."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    accession: Accession
    section: str = Field(min_length=4, description="a prefix of the section heading")
    text: str = Field(min_length=MIN_EXCERPT_CHARS, max_length=MAX_EXCERPT_CHARS)


class GoldenCase(BaseModel):
    """One known claim and what retrieval must bring back for it."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    id: str = Field(pattern=r"^[a-z0-9]+(?:-[a-z0-9]+)*$", max_length=80)
    ticker: str = Field(pattern=r"^[A-Z0-9][A-Z0-9-]{0,9}$")
    filings: list[Accession] = Field(min_length=1, max_length=limits.MAX_FILINGS)
    claim: str = Field(min_length=limits.MIN_CLAIM_CHARS, max_length=limits.MAX_CLAIM_CHARS)
    kind: Kind
    expected: Expected
    must_retrieve: list[MustRetrieve] = Field(default_factory=list, max_length=MAX_MUST_RETRIEVE)
    why: str = Field(min_length=10, max_length=400)

    @model_validator(mode="after")
    def _consistent(self) -> Self:
        if len(set(self.filings)) != len(self.filings):
            raise ValueError("filings repeats an accession number")
        if self.kind == "answerable":
            if self.expected == "none":
                raise ValueError("an answerable case expects supports, challenges or mixed")
            if not self.must_retrieve:
                raise ValueError("an answerable case needs one to three must_retrieve excerpts")
        else:
            if self.expected != "none":
                raise ValueError('an unanswerable case expects "none"')
            if self.must_retrieve:
                raise ValueError("an unanswerable case must have no must_retrieve excerpts")
        for record in self.must_retrieve:
            if record.accession not in self.filings:
                raise ValueError(f"must_retrieve names {record.accession}, not in filings")
        return self


@dataclass(frozen=True)
class Target:
    """A must-retrieve excerpt as located: its filing, section heading and span."""

    accession: str
    section: str
    start: int
    end: int


@dataclass
class CaseCheck:
    """The result of checking one case; ``case`` is None when its fields are invalid."""

    position: int
    case_id: str
    case: GoldenCase | None = None
    targets: list[Target] = field(default_factory=list)
    problems: list[str] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        """True when the case passed every check."""
        return self.case is not None and not self.problems


@dataclass
class Validation:
    """Every case's check, plus problems with the file as a whole."""

    version: int | None = None
    status: str = ""
    checks: list[CaseCheck] = field(default_factory=list)
    problems: list[str] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        """True when the file and every case passed."""
        return not self.problems and bool(self.checks) and all(c.ok for c in self.checks)

    def cases(self) -> list[tuple[GoldenCase, list[Target]]]:
        """The valid cases with their located targets, in file order."""
        return [(c.case, c.targets) for c in self.checks if c.ok and c.case is not None]


@dataclass(frozen=True)
class SectionSpan:
    """Where one section's text lies in its document's text."""

    heading: str
    start: int
    end: int


def heading_matches(heading: str, prefix: str) -> bool:
    """True when ``heading`` starts with ``prefix`` and the prefix ends at a word boundary.

    So "Item 1A" matches "Item 1A. Risk Factors" but "Item 1" does not, and
    "Part I" does not match "Part II, Item 1A".
    """
    prefix = prefix.strip()
    if not prefix or not heading.startswith(prefix):
        return False
    return len(heading) == len(prefix) or not heading[len(prefix)].isalnum()


def section_spans(document: Document) -> list[SectionSpan]:
    """Each section's span in ``document.text``, found as the chunker finds it."""
    spans: list[SectionSpan] = []
    cursor = 0
    for section in document.sections:
        laid_out = document.text.find(f"{section.heading.strip()}\n{section.text}", cursor)
        if laid_out >= 0:
            start = laid_out + len(section.heading.strip()) + 1
        else:
            start = document.text.find(section.text, cursor)
            if start < 0:
                start = document.text.find(section.text)
        if start < 0:
            raise ValueError(f"section {section.heading!r} is not part of the document text")
        end = start + len(section.text)
        spans.append(SectionSpan(section.heading, start, end))
        cursor = max(cursor, end)
    return spans


def _section_at(spans: list[SectionSpan], start: int, end: int) -> SectionSpan | None:
    return next((s for s in spans if s.start <= start and end <= s.end), None)


class _FilingText:
    """A loaded filing with its quote index and section spans, built once per validation."""

    def __init__(self, document: Document) -> None:
        self.document = document
        self.index = TextIndex(document.text)
        self.sections = section_spans(document)


def locate_excerpt(filing: _FilingText, record: MustRetrieve) -> tuple[Target | None, str]:
    """The excerpt's span under the stated section prefix, or None and the reason."""
    position = 0
    elsewhere: str | None = None
    while (span := filing.index.locate(record.text, position)) is not None:
        section = _section_at(filing.sections, *span)
        if section is not None and heading_matches(section.heading, record.section):
            return Target(record.accession, section.heading, span[0], span[1]), ""
        if elsewhere is None:
            elsewhere = section.heading if section else "text spanning two sections"
        position = span[0] + 1
    if elsewhere is None:
        return None, f"excerpt not found in {record.accession}: {record.text[:50]!r}..."
    return None, (
        f"excerpt is in {elsewhere!r}, not under {record.section!r} in {record.accession}"
    )


def _case_id(raw: object, position: int) -> str:
    if isinstance(raw, dict) and isinstance(raw.get("id"), str) and raw["id"]:
        return raw["id"]
    return f"(case {position + 1})"


def _field_problems(exc: ValidationError) -> list[str]:
    problems = []
    for error in exc.errors():
        where = ".".join(str(part) for part in error["loc"]) or "case"
        problems.append(f"{where}: {error['msg']}")
    return problems


def validate_golden(raw: object, loader: Loader) -> Validation:
    """Check a parsed golden file; ``loader(ticker, accession)`` returns a filing's Document.

    Collects every problem: a loader failure (:class:`CorpusError`, such as an
    unpinned filing) is a problem of the case that needed it, not a crash.
    """
    result = Validation()
    if not isinstance(raw, dict):
        result.problems.append("the golden file is not a JSON object")
        return result
    unknown = set(raw) - {"version", "status", "cases"}
    if unknown:
        result.problems.append(f"unknown top-level field(s): {', '.join(sorted(unknown))}")
    version = raw.get("version")
    result.version = version if isinstance(version, int) else None
    if version != GOLDEN_VERSION:
        result.problems.append(f"version must be {GOLDEN_VERSION}, found {version!r}")
    status = raw.get("status")
    result.status = status if isinstance(status, str) else ""
    if not result.status.strip():
        result.problems.append("status must say who drafted the set and how it was checked")
    cases = raw.get("cases")
    if not isinstance(cases, list) or not cases:
        result.problems.append("cases must be a non-empty list")
        return result

    filings: dict[str, _FilingText | str] = {}  # accession -> loaded text, or the load error
    seen: dict[str, int] = {}
    for position, raw_case in enumerate(cases):
        check = CaseCheck(position=position, case_id=_case_id(raw_case, position))
        result.checks.append(check)
        if check.case_id in seen:
            check.problems.append(f"duplicate id (also case {seen[check.case_id] + 1})")
        else:
            seen[check.case_id] = position
        try:
            case = GoldenCase.model_validate(raw_case)
        except ValidationError as exc:
            check.problems.extend(_field_problems(exc))
            continue
        check.case = case
        for accession in case.filings:
            key = f"{case.ticker} {accession}"
            if key not in filings:
                try:
                    filings[key] = _FilingText(loader(case.ticker, accession))
                except CorpusError as exc:
                    filings[key] = str(exc)
            if isinstance(filings[key], str):
                check.problems.append(str(filings[key]))
        for record in case.must_retrieve:
            filing = filings.get(f"{case.ticker} {record.accession}")
            if not isinstance(filing, _FilingText):
                continue
            target, problem = locate_excerpt(filing, record)
            if target is None:
                check.problems.append(problem)
            else:
                check.targets.append(target)
    return result


def read_golden(path: Path = GOLDEN_PATH) -> tuple[Any, str]:
    """The parsed golden file and the SHA-256 of its bytes. Raises ValueError if unreadable."""
    try:
        body = path.read_bytes()
    except FileNotFoundError as exc:
        raise ValueError(f"golden file not found: {path}") from exc
    try:
        return json.loads(body), hashlib.sha256(body).hexdigest()
    except json.JSONDecodeError as exc:
        raise ValueError(f"{path.name} is not valid JSON: {exc}") from exc


def _cell(value: object) -> str:
    return " ".join(str(value).split()).replace("|", "\\|")


def render_validation(result: Validation) -> str:
    """A Markdown table of every case's check, then a one-line verdict."""
    lines = [
        "| # | Case | Ticker | Kind | Expected | Filings | Excerpts | Result |",
        "|---|---|---|---|---|---|---|---|",
    ]
    for check in result.checks:
        case = check.case
        kind = case.kind if case else ""
        expected = case.expected if case else ""
        filings = str(len(case.filings)) if case else ""
        excerpts = f"{len(check.targets)}/{len(case.must_retrieve)}" if case else ""
        verdict = "ok" if check.ok else "; ".join(check.problems)
        ticker = case.ticker if case else ""
        row = [check.position + 1, check.case_id, ticker, kind, expected, filings, excerpts]
        row.append(verdict)
        lines.append("| " + " | ".join(_cell(cell) for cell in row) + " |")
    failed = sum(1 for check in result.checks if not check.ok)
    lines.append("")
    lines.extend(f"- file: {problem}" for problem in result.problems)
    lines.append(
        f"validate: {len(result.checks) - failed} of {len(result.checks)} case(s) valid; "
        + ("PASS" if result.ok else "FAIL")
    )
    return "\n".join(lines) + "\n"
