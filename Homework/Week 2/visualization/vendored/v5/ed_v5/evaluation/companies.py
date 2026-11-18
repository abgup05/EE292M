"""The companies of the golden set: who they are, and the figures a run would show the model.

A model prompt names the company (name, ticker, CIK), so the evaluation reads
them from ``eval/filings.json`` rather than from EDGAR's current company list:
:func:`pin_companies` looks a ticker up once (normally through
:meth:`app.sources.edgar.EdgarClient.company`) and the result stays pinned.

The reported figures come from the company's XBRL company facts, read once and
pinned by the SHA-256 of their bytes under ``"facts"`` in the same file. The
facts are read from the recorded fixture (NVIDIA), then from ``eval/cache``,
then from EDGAR; a body whose hash differs from its pin is an error. When the
facts cannot be had at all, the company is assessed without figures, and
:func:`figures_for` says so. The figures are chosen by
:func:`app.services.numbers.select_figures`, exactly as a run chooses them.
"""

from __future__ import annotations

import gzip
import json
from collections.abc import Callable, Iterable, Mapping
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Literal

from ed_v5.core.facts import FactBook, FactsError
from ed_v5.core.metric_models import Metric
from ed_v5.core.metrics import build_report
from ed_v5.core.models import Company
from ed_v5.core.ports import SourceError
from ed_v5.evaluation.corpus import FIXTURE_DIR, CorpusError, Fetch, PinnedFacts, PinnedFiling
from ed_v5.evaluation.corpus import sha256_hex as _sha256
from ed_v5.services.numbers import select_figures
from ed_v5.sources.xbrl import company_facts_url

FactsOrigin = Literal["fixture", "cache", "edgar", "none"]
Lookup = Callable[[str], Company]

# Recorded company facts the tests also read; any other company's are fetched and cached.
FACTS_FIXTURES: dict[str, Path] = {"NVDA": FIXTURE_DIR / "companyfacts-CIK0001045810.json.gz"}


def company_for(ticker: str, pins: Mapping[str, PinnedFiling]) -> Company:
    """The pinned company of ``ticker``. Raises :class:`CorpusError` if absent or inconsistent."""
    found = {(pin.cik, pin.name) for pin in pins.values() if pin.ticker == ticker}
    if not found:
        raise CorpusError(f"no filing of {ticker} is pinned in eval/filings.json")
    if len(found) > 1:
        companies = sorted(found, key=str)
        raise CorpusError(f"the filings of {ticker} pin different companies: {companies}")
    cik, name = found.pop()
    if cik is None or name is None:
        raise CorpusError(
            f"the cik and name of {ticker} are not pinned in eval/filings.json; "
            "run a command that may use EDGAR (without --offline) once to pin them"
        )
    return Company(cik=cik, ticker=ticker, name=name)


def pin_companies(
    tickers: Iterable[str], pins: Mapping[str, PinnedFiling], lookup: Lookup | None
) -> tuple[dict[str, PinnedFiling], list[str]]:
    """Fill in the cik and name of each ticker whose filings lack them.

    Returns the updated pins and the tickers looked up (in order). A ticker
    already pinned is never looked up again. Without ``lookup`` a missing
    company raises :class:`CorpusError`.
    """
    updated = dict(pins)
    changed: list[str] = []
    for ticker in dict.fromkeys(tickers):
        try:
            company_for(ticker, updated)
            continue
        except CorpusError:
            if lookup is None:
                raise
        company = lookup(ticker)
        for accession, pin in updated.items():
            if pin.ticker == ticker:
                identity = {"cik": company.cik, "name": company.name}
                updated[accession] = pin.model_copy(update=identity)
        company_for(ticker, updated)  # raises if the ticker has no pinned filing
        changed.append(ticker)
    return updated, changed


@dataclass(frozen=True)
class FactsRead:
    """A company's facts as read: the parsed payload, its pin and origin, or why not."""

    payload: dict[str, Any] | None
    pin: PinnedFacts | None
    origin: FactsOrigin
    error: str | None = None


def facts_cache_path(cache_dir: Path, cik: int) -> Path:
    """Where the gzip of a company's facts is cached."""
    return cache_dir / f"companyfacts-CIK{cik:010d}.json.gz"


def _gunzip(path: Path) -> bytes:
    try:
        return gzip.decompress(path.read_bytes())
    except (OSError, EOFError) as exc:
        raise CorpusError(f"{path} is not a readable gzip file ({exc.__class__.__name__})") from exc


def _body(
    ticker: str, company: Company, cache_dir: Path, fetch: Fetch | None
) -> tuple[bytes | None, FactsOrigin, str | None]:
    fixture = FACTS_FIXTURES.get(ticker)
    if fixture is not None and fixture.exists():
        return _gunzip(fixture), "fixture", None
    cached = facts_cache_path(cache_dir, company.cik)
    if cached.exists():
        return _gunzip(cached), "cache", None
    if fetch is None:
        return None, "none", "the facts are neither recorded nor cached, and EDGAR was not used"
    try:
        body = fetch(company_facts_url(company.cik))
    except SourceError as exc:
        return None, "none", str(exc)
    cached.parent.mkdir(parents=True, exist_ok=True)
    partial = cached.with_suffix(".partial")
    partial.write_bytes(gzip.compress(body, compresslevel=9, mtime=0))
    partial.replace(cached)
    return body, "edgar", None


def read_facts(
    ticker: str,
    company: Company,
    pinned: PinnedFacts | None,
    *,
    cache_dir: Path,
    fetch: Fetch | None,
) -> FactsRead:
    """The company facts of ``company``: fixture, cache, then EDGAR (when ``fetch`` is given).

    A body is checked against ``pinned`` when there is a pin, and a new pin is
    returned when there is none. A body that differs from its pin raises
    :class:`CorpusError`; facts that cannot be had come back with ``error``.
    """
    body, origin, error = _body(ticker, company, cache_dir, fetch)
    if body is None:
        return FactsRead(None, pinned, "none", error)
    digest = _sha256(body)
    if pinned is not None and digest != pinned.sha256:
        raise CorpusError(
            f"the company facts of {ticker} from {origin} have SHA-256 {digest[:12]}..., but the "
            f"pin says {pinned.sha256[:12]}...; the facts are not the ones pinned"
        )
    pin = pinned or PinnedFacts(cik=company.cik, url=company_facts_url(company.cik), sha256=digest)
    try:
        payload = json.loads(body)
    except json.JSONDecodeError, UnicodeDecodeError:
        return FactsRead(None, pin, origin, "the company facts are not valid JSON")
    if not isinstance(payload, dict):
        return FactsRead(None, pin, origin, "the company facts are not a JSON object")
    return FactsRead(payload, pin, origin)


@dataclass(frozen=True)
class CompanyFigures:
    """The figures offered for every claim of one company, and a note saying where from."""

    figures: list[Metric] = field(default_factory=list)
    note: str = ""


def figures_for(facts: FactsRead) -> CompanyFigures:
    """The figures a run would offer, built from ``facts`` as the pipeline builds them."""
    if facts.payload is None:
        return CompanyFigures([], f"assessed without reported figures: {facts.error}")
    try:
        figures = select_figures(build_report(FactBook(facts.payload)))
    except FactsError as exc:
        return CompanyFigures([], f"assessed without reported figures: {exc}")
    sha = facts.pin.sha256[:12] if facts.pin else "?"
    return CompanyFigures(
        figures, f"{len(figures)} figures from the XBRL facts ({facts.origin}, SHA-256 {sha}...)"
    )
