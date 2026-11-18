"""SEC's XBRL frames and its company list by industry code, fetched and kept on disk.

Two things only SEC holds and the outside view needs:

- a **frame**, ``https://data.sec.gov/api/xbrl/frames/us-gaap/<Concept>/<unit>/<period>.json``:
  one value per filer for one concept and calendar period;
- the **filers of an industry**, SEC's company browse by SIC code
  (``https://www.sec.gov/cgi-bin/browse-edgar?action=getcompany&SIC=...&output=atom``),
  read page by page.

Requests go through the app's EDGAR client (:meth:`app.sources.edgar.EdgarClient.get`:
its User-Agent, its allow-list of SEC hosts, its limits and retries), and this source
spaces its own requests at least :data:`MIN_SECONDS_BETWEEN` apart on top of the
client's limit, so a cold cache costs at most four requests a second. Every body is
kept gzipped under the cache directory (``data/cache/frames``, disposable); a frame SEC
does not have (HTTP 404: no filer tagged that concept for that period) is kept as
absent, so it is not asked again. A source made with ``get=None`` reads only what is on
disk (the recorded fixtures) and treats anything else as not read.
"""

from __future__ import annotations

import gzip
import html
import json
import re
import threading
import time
from collections.abc import Callable
from pathlib import Path
from typing import Any

from app.core.frames import check_concept
from app.core.ports import SourceError

FRAME_URL = "https://data.sec.gov/api/xbrl/frames/us-gaap/{concept}/{unit}/{period}.json"
SIC_URL = (
    "https://www.sec.gov/cgi-bin/browse-edgar?action=getcompany&SIC={sic}&type=10-K"
    "&dateb=&owner=include&count={count}&start={start}&output=atom"
)
SIC_PAGE = 100
MAX_SIC_PAGES = 40
MIN_SECONDS_BETWEEN = 0.25
PERIOD_PATTERN = re.compile(r"^CY\d{4}(?:Q[1-4]I?)?$")
UNIT_PATTERN = re.compile(r"^[A-Za-z]{1,10}(?:-per-[A-Za-z]{1,10})?$")
SIC_PATTERN = re.compile(r"^\d{3,4}$")
_CIK = re.compile(r"<cik>(\d{1,10})</cik>")
_NAME = re.compile(r"<name>([^<]*)</name>")
_SIC = re.compile(r"<sic>(\d{3,4})</sic>")
ABSENT = b'{"absent": true}'


class FramesSource:
    """SEC frames and the SIC company list, through ``get`` and a directory of kept bodies."""

    def __init__(
        self,
        get: Callable[[str], bytes] | None,
        cache_dir: Path,
        *,
        sleep: Callable[[float], None] = time.sleep,
        monotonic: Callable[[], float] = time.monotonic,
    ) -> None:
        self._get = get
        self.cache_dir = cache_dir
        self._sleep = sleep
        self._monotonic = monotonic
        self._lock = threading.Lock()
        self._next = float("-inf")
        self.requests = 0
        self.not_read: list[str] = []

    @property
    def offline(self) -> bool:
        """True when this source reads only the bodies on disk."""
        return self._get is None

    def _fetch(self, url: str) -> bytes:
        assert self._get is not None
        with self._lock:
            wait = self._next - self._monotonic()
            if wait > 0:
                self._sleep(wait)
            self._next = self._monotonic() + MIN_SECONDS_BETWEEN
        self.requests += 1
        return self._get(url)

    def _kept(self, name: str) -> Path:
        return self.cache_dir / name

    def _read_kept(self, path: Path) -> bytes | None:
        if not path.is_file():
            return None
        return gzip.decompress(path.read_bytes())

    def _keep(self, path: Path, body: bytes) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        temporary = path.with_suffix(path.suffix + ".part")
        temporary.write_bytes(gzip.compress(body, mtime=0))
        temporary.replace(path)

    def frame(self, concept: str, period: str, unit: str = "USD") -> dict[str, Any] | None:
        """The frame of ``concept`` for ``period`` as parsed JSON; None when SEC has none.

        Raises :class:`SourceError` when EDGAR fails otherwise or the body is not JSON.
        Offline, a frame not on disk is None and is listed in :attr:`not_read`.
        """
        check_concept(concept)
        if not PERIOD_PATTERN.fullmatch(period) or not UNIT_PATTERN.fullmatch(unit):
            raise ValueError(f"not a frame period and unit: {period!r}, {unit!r}")
        path = self._kept(f"{concept}-{unit}-{period}.json.gz")
        body = self._read_kept(path)
        if body is None:
            if self.offline:
                self.not_read.append(f"{concept}/{unit}/{period}")
                return None
            url = FRAME_URL.format(concept=concept, unit=unit, period=period)
            try:
                body = self._fetch(url)
            except SourceError as exc:
                if "HTTP 404" not in str(exc):
                    raise
                body = ABSENT
            self._keep(path, body)
        if body == ABSENT:
            return None
        try:
            payload = json.loads(body)
        except (json.JSONDecodeError, UnicodeDecodeError) as exc:
            raise SourceError(f"EDGAR returned a malformed frame for {concept}/{period}") from exc
        if not isinstance(payload, dict):
            raise SourceError(f"EDGAR returned a malformed frame for {concept}/{period}")
        return payload

    def sic_members(self, sic: str) -> list[tuple[int, str]]:
        """Every filer SEC lists under industry code ``sic`` that has filed a 10-K, as (CIK, name).

        Read page by page until a page is empty or adds no new filer, at most :data:`MAX_SIC_PAGES`.
        The list is SEC's today: a filer's current code, not the code it had in a past
        year. Offline, a list not on disk is empty and is listed in :attr:`not_read`.
        """
        if not SIC_PATTERN.fullmatch(sic):
            raise ValueError(f"not an SIC code: {sic!r}")
        path = self._kept(f"sic-{sic}.json.gz")
        kept = self._read_kept(path)
        if kept is not None:
            return [(int(cik), str(name)) for cik, name in json.loads(kept)]
        if self.offline:
            self.not_read.append(f"SIC {sic} company list")
            return []
        members: dict[int, str] = {}
        start = 0
        for _ in range(MAX_SIC_PAGES):
            text = self._fetch(SIC_URL.format(sic=sic, count=SIC_PAGE, start=start)).decode(
                "latin-1"
            )
            entries = text.count("<entry>")
            new = [(cik, name) for cik, name in parse_sic_page(text, sic) if cik not in members]
            if not entries or not new:
                break
            members.update(new)
            start += entries
        result = sorted(members.items())
        self._keep(path, json.dumps(result).encode("utf-8"))
        return result


def parse_sic_page(text: str, sic: str) -> list[tuple[int, str]]:
    """The (CIK, name) entries of one Atom page of SEC's company browse, of code ``sic`` only.

    Each ``<entry>`` is read on its own: its ``<cik>``, ``<name>`` and ``<sic>`` elements,
    in any order (an entry may list former names between them, escaped).
    """
    found: list[tuple[int, str]] = []
    for entry in text.split("<entry>")[1:]:
        cik, name, code = _CIK.search(entry), _NAME.search(entry), _SIC.search(entry)
        if cik and name and code and code.group(1) == sic:
            found.append((int(cik.group(1)), html.unescape(name.group(1)).strip()))
    return found
