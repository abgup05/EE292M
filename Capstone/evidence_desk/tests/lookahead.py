"""The no-lookahead checks: what a computation as of a date may and may not have seen.

Two checks, used by every test that computes something "as of" a date:

- :func:`late_refs`: every fact reference in an output (any nested ``filed`` beside an
  ``accession``) must have been filed on or before the date;
- :func:`pruned`: the payload with every fact filed after the date deleted, written
  here independently of :mod:`app.core.facts`, so that an output computed as of the
  date can be compared with the same output computed from a payload that never held
  the later facts.

Neither touches the code under test, so a filter in the application that leaks a
later fact is caught by both.
"""

from __future__ import annotations

import copy
from collections.abc import Iterator
from datetime import date
from typing import Any

from pydantic import BaseModel


def pruned(payload: dict[str, Any], as_of: date) -> dict[str, Any]:
    """A deep copy of a company-facts body without any fact filed after ``as_of``."""
    result = copy.deepcopy(payload)
    for taxonomy in result.get("facts", {}).values():
        for concept in taxonomy.values():
            for unit, entries in list(concept.get("units", {}).items()):
                concept["units"][unit] = [
                    entry for entry in entries if date.fromisoformat(entry["filed"]) <= as_of
                ]
    return result


def _plain(value: object) -> object:
    if isinstance(value, BaseModel):
        return value.model_dump(mode="json")
    return value


def _refs(value: object) -> Iterator[dict[str, Any]]:
    """Every mapping with both ``accession`` and ``filed`` inside ``value``, at any depth."""
    value = _plain(value)
    if isinstance(value, dict):
        if "accession" in value and "filed" in value:
            yield value
        for item in value.values():
            yield from _refs(item)
    elif isinstance(value, list | tuple):
        for item in value:
            yield from _refs(_plain(item))


def fact_refs(output: object) -> list[dict[str, Any]]:
    """Every fact reference (a mapping with ``accession`` and ``filed``) in ``output``."""
    return list(_refs(output))


def late_refs(output: object, as_of: date) -> list[str]:
    """The fact references in ``output`` filed after ``as_of``, as "accession filed" lines."""
    return [
        f"{ref['accession']} filed {ref['filed']}"
        for ref in fact_refs(output)
        if ref["filed"] and date.fromisoformat(str(ref["filed"])) > as_of
    ]


def filing_dates(payload: dict[str, Any], forms: tuple[str, ...] = ("10-K", "10-Q")) -> list[date]:
    """Every distinct filing date of a periodic report in a company-facts body, oldest first."""
    days = {
        date.fromisoformat(entry["filed"])
        for taxonomy in payload.get("facts", {}).values()
        for concept in taxonomy.values()
        for entries in concept.get("units", {}).values()
        for entry in entries
        if entry.get("form") in forms
    }
    return sorted(days)
