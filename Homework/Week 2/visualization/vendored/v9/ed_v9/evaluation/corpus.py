"""The filings the golden set is measured on: pinned by hash, read offline when possible.

Every filing a case names is pinned in ``eval/filings.json`` (ticker, accession,
form, period end, filing date, URL and the SHA-256 of the original HTML, and the
company's CIK and name); the file also pins each company's XBRL facts under
``"facts"`` (see :mod:`app.evaluation.companies`). The
primary document is read, in order, from the recorded test fixtures
(``tests/fixtures/edgar``, listed in their ``manifest.json``), from the local
cache ``eval/cache`` (gitignored), and only then from SEC EDGAR through
:class:`app.sources.edgar.EdgarClient`, whose body is written to the cache. A body
whose hash differs from its pin is an error wherever it came from, so a score
is always computed on the text that was pinned.

The document is parsed with :func:`app.sources.filing.parse_filing`, exactly as
a thesis run parses it.
"""

from __future__ import annotations

import gzip
import hashlib
import json
from collections.abc import Callable, Iterable, Mapping
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from ed_v9.core.documents import Document
from ed_v9.core.ports import SourceError
from ed_v9.sources.edgar import EdgarClient
from ed_v9.sources.filing import parse_filing

APP_ROOT = Path(__file__).resolve().parents[3]
EVAL_DIR = APP_ROOT / "eval"
FILINGS_PATH = EVAL_DIR / "filings.json"
CACHE_DIR = EVAL_DIR / "cache"
FIXTURE_DIR = APP_ROOT / "tests" / "fixtures" / "edgar"
FIXTURE_MANIFEST = "manifest.json"
PINS_VERSION = 1

ACCESSION_PATTERN = r"^\d{10}-\d{2}-\d{6}$"
DATE_PATTERN = r"^\d{4}-\d{2}-\d{2}$"
SHA256_PATTERN = r"^[0-9a-f]{64}$"
ARCHIVE_PREFIX = "https://www.sec.gov/Archives/edgar/data/"

Origin = Literal["fixture", "cache", "edgar"]
Fetch = Callable[[str], bytes]


class CorpusError(RuntimeError):
    """A pinned filing could not be read or does not match its pin; safe to print."""


class PinnedFiling(BaseModel):
    """One filing as pinned: where it lives and the hash of its original HTML."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    ticker: str = Field(pattern=r"^[A-Z0-9][A-Z0-9-]{0,9}$")
    accession: str = Field(pattern=ACCESSION_PATTERN)
    form: Literal["10-K", "10-Q"]
    period_end: str = Field(pattern=DATE_PATTERN)
    filed_date: str = Field(pattern=DATE_PATTERN)
    url: str = Field(pattern=r"^https://www\.sec\.gov/Archives/edgar/data/\d+/\d{18}/[\w.-]+$")
    sha256: str = Field(pattern=SHA256_PATTERN)
    # The filer as EDGAR names it, pinned once: the model prompts carry both, so a
    # change would change every request key of the cassette.
    cik: int | None = Field(default=None, gt=0)
    name: str | None = Field(default=None, min_length=1, max_length=200)

    @property
    def title(self) -> str:
        """The title a thesis run would give this filing (ticker in place of the name)."""
        return f"{self.ticker} {self.form}, period ended {self.period_end}"


class PinnedFacts(BaseModel):
    """A company's XBRL company facts as pinned: where they came from and their hash."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    cik: int = Field(gt=0)
    url: str = Field(pattern=r"^https://data\.sec\.gov/")
    sha256: str = Field(pattern=SHA256_PATTERN)


class PinsFile(BaseModel):
    """The shape of ``eval/filings.json``: the filings, and the company facts by ticker."""

    model_config = ConfigDict(extra="forbid")

    version: Literal[1]
    filings: list[PinnedFiling]
    facts: dict[str, PinnedFacts] = Field(default_factory=dict)


def sha256_hex(body: bytes) -> str:
    """The SHA-256 of ``body`` as lower-case hex."""
    return hashlib.sha256(body).hexdigest()


def _read_pins_file(path: Path) -> PinsFile:
    try:
        return PinsFile.model_validate_json(path.read_bytes())
    except FileNotFoundError as exc:
        raise CorpusError(f"{path.name} not found at {path}") from exc
    except ValidationError as exc:
        count = exc.error_count()
        raise CorpusError(f"{path.name} is malformed: {count} problem(s)\n{exc}") from exc


def load_pins(path: Path = FILINGS_PATH) -> dict[str, PinnedFiling]:
    """The pinned filings by accession number. Raises :class:`CorpusError` on a bad file."""
    pins: dict[str, PinnedFiling] = {}
    for pin in _read_pins_file(path).filings:
        if pin.accession in pins:
            raise CorpusError(f"{path.name} pins {pin.accession} twice")
        pins[pin.accession] = pin
    return pins


def load_facts_pins(path: Path = FILINGS_PATH) -> dict[str, PinnedFacts]:
    """The pinned company facts by ticker. Raises :class:`CorpusError` on a bad file."""
    return dict(_read_pins_file(path).facts)


def save_pins(
    pins: Iterable[PinnedFiling],
    path: Path = FILINGS_PATH,
    facts: Mapping[str, PinnedFacts] | None = None,
) -> None:
    """Write the pins sorted by ticker, then period end (newest first).

    ``facts`` replaces the pinned company facts; when it is None the facts
    already in the file at ``path`` are kept.
    """
    if facts is None:
        facts = _read_pins_file(path).facts if path.exists() else {}
    ordered = sorted(pins, key=lambda pin: pin.period_end, reverse=True)
    ordered.sort(key=lambda pin: pin.ticker)  # stable: newest first within a ticker
    payload = PinsFile(version=PINS_VERSION, filings=ordered, facts=dict(sorted(facts.items())))
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload.model_dump(exclude_none=True), indent=2) + "\n")


def fixture_files(fixture_dir: Path = FIXTURE_DIR) -> dict[str, Path]:
    """Recorded primary documents (gzip) by original URL, from the fixture manifest."""
    manifest_path = fixture_dir / FIXTURE_MANIFEST
    try:
        manifest = json.loads(manifest_path.read_text())
    except FileNotFoundError:
        return {}
    except json.JSONDecodeError as exc:
        raise CorpusError(f"The fixture manifest {manifest_path} is not valid JSON") from exc
    files: dict[str, Path] = {}
    for name, entry in manifest.items():
        url = entry.get("url") if isinstance(entry, dict) else None
        if isinstance(url, str) and url.startswith(ARCHIVE_PREFIX) and name.endswith(".gz"):
            files[url] = fixture_dir / name
    return files


def _gunzip(path: Path) -> bytes:
    try:
        return gzip.decompress(path.read_bytes())
    except (OSError, EOFError) as exc:
        raise CorpusError(f"{path} is not a readable gzip file ({exc.__class__.__name__})") from exc


class Corpus:
    """Reads pinned filings: fixtures, then the cache, then EDGAR (when ``fetch`` is given).

    ``fetch`` is a function from URL to body, normally :meth:`EdgarClient.get`;
    without it the corpus is offline and a filing that is neither recorded nor
    cached is an error. Parsed documents are kept for the life of the object.
    """

    def __init__(
        self,
        pins: Mapping[str, PinnedFiling],
        *,
        fixture_dir: Path = FIXTURE_DIR,
        cache_dir: Path = CACHE_DIR,
        fetch: Fetch | None = None,
    ) -> None:
        """Serve the filings in ``pins`` (by accession)."""
        self.pins = dict(pins)
        self.cache_dir = cache_dir
        self._fixtures = fixture_files(fixture_dir)
        self._fetch = fetch
        self._documents: dict[str, Document] = {}

    def pin(self, ticker: str, accession: str) -> PinnedFiling:
        """The pin of ``accession``, checked to belong to ``ticker``."""
        pin = self.pins.get(accession)
        if pin is None:
            raise CorpusError(f"{accession} is not pinned in eval/filings.json")
        if pin.ticker != ticker:
            raise CorpusError(f"{accession} is pinned for {pin.ticker}, not {ticker}")
        return pin

    def cache_path(self, accession: str) -> Path:
        """Where the gzip of a filing's original HTML is cached."""
        return self.cache_dir / f"{accession}.htm.gz"

    def _check(self, pin: PinnedFiling, body: bytes, where: str) -> bytes:
        digest = sha256_hex(body)
        if digest != pin.sha256:
            raise CorpusError(
                f"{pin.ticker} {pin.accession} from {where} has SHA-256 {digest[:12]}..., "
                f"but the pin says {pin.sha256[:12]}...; the filing is not the one pinned"
            )
        return body

    def original(self, pin: PinnedFiling) -> tuple[bytes, Origin]:
        """The pinned filing's original HTML bytes and where they came from."""
        fixture = self._fixtures.get(pin.url)
        if fixture is not None and fixture.exists():
            return self._check(pin, _gunzip(fixture), f"fixture {fixture.name}"), "fixture"
        cached = self.cache_path(pin.accession)
        if cached.exists():
            return self._check(pin, _gunzip(cached), f"cache {cached.name}"), "cache"
        if self._fetch is None:
            raise CorpusError(
                f"{pin.ticker} {pin.accession} is neither recorded nor cached; "
                'run `make eval ARGS="fetch"` first'
            )
        try:
            fetched = self._fetch(pin.url)
        except SourceError as exc:
            raise CorpusError(f"{pin.ticker} {pin.accession}: {exc}") from exc
        body = self._check(pin, fetched, "EDGAR")
        self.write_cache(pin.accession, body)
        return body, "edgar"

    def write_cache(self, accession: str, body: bytes) -> Path:
        """Cache a filing's original HTML, gzip-compressed (written atomically)."""
        path = self.cache_path(accession)
        path.parent.mkdir(parents=True, exist_ok=True)
        partial = path.with_suffix(".partial")
        partial.write_bytes(gzip.compress(body, compresslevel=9, mtime=0))
        partial.replace(path)
        return path

    def recorded(self, url: str) -> bytes | None:
        """The original HTML of a recorded fixture with this URL, if there is one."""
        fixture = self._fixtures.get(url)
        return _gunzip(fixture) if fixture is not None and fixture.exists() else None

    def load_filing(self, ticker: str, accession: str) -> Document:
        """The parsed filing, as a thesis run would store it."""
        pin = self.pin(ticker, accession)
        document = self._documents.get(accession)
        if document is None:
            body, _ = self.original(pin)
            document = parse_filing(
                body.decode("utf-8", errors="replace"),
                url=pin.url,
                title=pin.title,
                published_date=pin.filed_date,
            )
            self._documents[accession] = document
        return document


def edgar_fetch(url: str) -> bytes:
    """One body from SEC EDGAR through a short-lived :class:`EdgarClient` (all its limits)."""
    try:
        with EdgarClient.from_env() as client:
            return client.get(url)
    except SourceError as exc:
        raise CorpusError(str(exc)) from exc


def load_filing(ticker: str, accession: str, *, online: bool = True) -> Document:
    """The parsed filing ``accession`` of ``ticker`` from the pins in ``eval/filings.json``.

    Reads the recorded fixtures, then ``eval/cache``, then (when ``online``) SEC
    EDGAR, caching what it fetched. Raises :class:`CorpusError`.
    """
    corpus = Corpus(load_pins(), fetch=edgar_fetch if online else None)
    return corpus.load_filing(ticker, accession)
