"""SEC's XBRL "company facts" API: where it lives and how its body is read.

The transport is injected (``get(url) -> bytes``, normally
:meth:`app.sources.edgar.EdgarClient.get`), so this module only builds the
address and turns the body into a JSON object. The shape of the facts inside is
checked by :class:`app.core.facts.FactBook`.
"""

from __future__ import annotations

import json
from collections.abc import Callable
from typing import Any

from ed_v5.core.ports import SourceError

COMPANY_FACTS_URL = "https://data.sec.gov/api/xbrl/companyfacts/CIK{cik:010d}.json"
MAX_CIK = 9_999_999_999


def company_facts_url(cik: int) -> str:
    """The company-facts address for ``cik``, zero-padded to ten digits as EDGAR expects.

    Raises ValueError for a CIK that cannot exist (not 1 to ten digits).
    """
    if isinstance(cik, bool) or not isinstance(cik, int) or not 0 < cik <= MAX_CIK:
        raise ValueError(f"CIK must be a positive integer of at most ten digits, got {cik!r}")
    return COMPANY_FACTS_URL.format(cik=cik)


def fetch_company_facts(get: Callable[[str], bytes], cik: int) -> dict[str, Any]:
    """Retrieve and parse the company facts of ``cik`` through ``get``.

    Errors from ``get`` (a :class:`SourceError` for the EDGAR client) pass
    through unchanged. A body that is not a JSON object raises SourceError.
    """
    url = company_facts_url(cik)
    body = get(url)
    try:
        payload = json.loads(body)
    except (json.JSONDecodeError, UnicodeDecodeError) as exc:
        raise SourceError(f"EDGAR returned malformed company facts for CIK {cik}") from exc
    if not isinstance(payload, dict):
        raise SourceError(
            f"EDGAR returned malformed company facts for CIK {cik}: expected a JSON object"
        )
    return payload
