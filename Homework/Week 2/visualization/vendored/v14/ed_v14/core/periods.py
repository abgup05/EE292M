"""The period check: each year or fiscal label a statement names must be in its evidence.

The number check (:mod:`app.core.numcheck`) never looks at a year, so a
statement that puts a figure in fiscal 2023 passes above a quote about fiscal
2025. This module reports such a statement. It withholds nothing: a finding it
cannot place keeps its status, and the check says so.

What counts as evidence for a year:

- a year any quoted excerpt shows, in any context (:func:`years_in`, generous,
  since accepting more means fewer false alarms);
- the fiscal year, and the calendar year, of the period end of each filing
  quoted ("Data Center revenue was $89.0 billion, up 117% from a year ago"
  carries no year; the 10-Q it is from does);
- the fiscal year, and the calendar year, of each cited figure's period end
  and of the end of each of its inputs (so the base year of a year-over-year
  change is evidence).

A fiscal label ("fiscal 2026", "FY26") passes when it is in a quote or is the
fiscal year of a filing or a figure; a calendar year is not enough, because a
fiscal label is not the calendar year of a period's end (NVIDIA's fiscal 2027
ends in January 2027). A year inside a date ("July 26, 2026", "June 2026")
passes when it is in a quote or is the calendar year of a period end; the
fiscal year is not enough, because a date names a calendar year. A bare year
("in 2025") passes on any of them, since it may be meant either way. A year that does not pass is
*unverified*; when it is one or two less than the fiscal year of a filing or a
figure it is also listed as *comparative*: the years a report prints beside its
own. That classification changes nothing; it is there to be counted.

A company's fiscal calendar comes from the newest annual report in its company
facts (:func:`fiscal_calendar`). That is the one place ``fy`` is read: it
describes the filing, and the filing's own label is what is wanted. Without a
calendar, a period end is taken to fall in the fiscal year of its own calendar
year or of the next, and the check says the calendar could not be read.

The years a statement names are read with the number check's own recognition
of dates, labels and years (:func:`app.core.numcheck.date_spans`,
:func:`~app.core.numcheck.period_label_spans`,
:func:`~app.core.numcheck.year_spans`), so the two checks cannot disagree
about what is a year and what is a quantity ("2000 employees" is not a year).

Pure: no I/O.
"""

from __future__ import annotations

import calendar as gregorian
import re
from collections.abc import Iterator, Sequence
from dataclasses import dataclass, field
from datetime import date, timedelta
from typing import Any, Literal

from ed_v14.core.facts import ANNUAL_FORMS, period_length
from ed_v14.core.metric_models import Metric
from ed_v14.core.numcheck import YEARS, date_spans, period_label_spans, year_spans

PeriodStatus = Literal["none", "passed", "unverified"]

# A 52/53-week fiscal year ends on a weekday near a nominal date, so its end moves by up to
# a week from year to year: a day this many days after the nominal end still belongs to the
# year ending there.
YEAR_END_DRIFT_DAYS = 10
# A label's offset from the calendar year its fiscal year ends in: 0 or -1 in practice; a
# filing whose ``fy`` is further off is not a usable calendar.
MAX_LABEL_OFFSET = 1
# The years an excerpt is taken to show (years_in): the years a statement can name, so that a
# year the number check reads in a statement can always be found in a quote that prints it.
EVIDENCE_YEARS = YEARS
# A year this much below the fiscal year of a filing or a figure is a comparison year.
COMPARATIVE_GAPS = (1, 2)

IN_QUOTE = "{raw} is in a quote"
FILING_FISCAL = "{raw} is the fiscal year of a filing quoted (period ended {end})"
FIGURE_FISCAL = "{raw} is the fiscal year of a cited figure (period ended {end})"
FILING_YEAR = "{raw} is the calendar year of a filing quoted (period ended {end})"
FIGURE_YEAR = "{raw} is the calendar year of a cited figure (period ended {end})"
NOT_FOUND = "is not in the quotes, the cited figures or the period of a filing quoted"
COMPARATIVE_NOTE = (
    "; it is a year or two before the fiscal year of a filing quoted or a cited figure, "
    "as a report's comparison year would be"
)
NO_CALENDAR = (
    "The company's fiscal calendar could not be read: each period end was taken to fall in "
    "the fiscal year of its own calendar year or of the next"
)


# The fiscal calendar


@dataclass(frozen=True)
class FiscalCalendar:
    """How a company labels its fiscal years.

    A fiscal year ends on about ``end_month``/``end_day`` each year.
    ``label_offset`` is the fiscal year's label minus the calendar year in which
    that fiscal year ends: 0 for a company whose fiscal 2026 ends in 2026, -1
    for one that names the year it begins in. ``year_end`` is the end of the
    year the calendar was read from, when known: around it the boundary is
    exact, not approximate.
    """

    end_month: int
    end_day: int
    label_offset: int
    year_end: date | None = None

    def _nominal_end(self, year: int) -> date:
        last = gregorian.monthrange(year, self.end_month)[1]
        return date(year, self.end_month, min(self.end_day, last))

    def fiscal_year(self, day: date) -> int:
        """The label of the fiscal year that contains ``day``.

        A day up to :data:`YEAR_END_DRIFT_DAYS` days after a nominal year end
        still belongs to the year ending there (a 52/53-week year ends up to a
        week late), except just after ``year_end``, where the year is known to
        have ended.
        """
        drift = timedelta(days=YEAR_END_DRIFT_DAYS)
        if self.year_end is not None and self.year_end < day <= self.year_end + drift:
            return self.year_end.year + self.label_offset + 1
        for year in (day.year - 1, day.year, day.year + 1):
            if day <= self._nominal_end(year) + drift:
                return year + self.label_offset
        raise AssertionError("unreachable: a day is never past the next year's end")

    def fiscal_quarter(self, day: date) -> int:
        """The quarter (1 to 4) of its fiscal year that a quarter ending ``day`` is.

        Counted back from the end of the fiscal year containing ``day`` in steps of
        about 91 days, so a 13- or 14-week quarter of a 52/53-week year is placed.
        """
        year = self.fiscal_year(day)
        end = self._nominal_end(year - self.label_offset)
        if self.year_end is not None and self.year_end.year + self.label_offset == year:
            end = self.year_end
        left = round((end - day).days / 91.3)
        return min(4, max(1, 4 - left))


def _iso_date(value: object) -> date | None:
    if not isinstance(value, str) or len(value) != 10:
        return None
    try:
        return date.fromisoformat(value)
    except ValueError:
        return None


@dataclass(frozen=True)
class _AnnualFact:
    """A year-long duration fact of an annual report: its filing, label and end."""

    filed: date
    accession: str
    fy: int
    end: date


def _annual_fact(raw: object) -> _AnnualFact | None:
    """``raw`` when it is a well-formed year-long fact of an annual report, else None."""
    if not isinstance(raw, dict):
        return None
    form, accession, fy = raw.get("form"), raw.get("accn"), raw.get("fy")
    if not isinstance(form, str) or not form.startswith(ANNUAL_FORMS):
        return None
    if not isinstance(accession, str) or isinstance(fy, bool) or not isinstance(fy, int):
        return None
    start, end = _iso_date(raw.get("start")), _iso_date(raw.get("end"))
    filed = _iso_date(raw.get("filed"))
    if start is None or end is None or filed is None or start > end:
        return None
    if period_length(start, end) != "annual":
        return None
    return _AnnualFact(filed, accession, fy, end)


def _entries(companyfacts: object) -> Iterator[object]:
    """Every raw fact of every taxonomy, concept and unit; nothing for a malformed level."""
    facts = companyfacts.get("facts") if isinstance(companyfacts, dict) else None
    if not isinstance(facts, dict):
        return
    for taxonomy in facts.values():
        if not isinstance(taxonomy, dict):
            continue
        for concept in taxonomy.values():
            units: Any = concept.get("units") if isinstance(concept, dict) else None
            if not isinstance(units, dict):
                continue
            for entries in units.values():
                if isinstance(entries, list):
                    yield from entries


def fiscal_calendar(companyfacts: object, *, as_of: date | None = None) -> FiscalCalendar | None:
    """The fiscal calendar of the newest annual report in an SEC company-facts body.

    Among year-long duration facts whose form starts with one of
    :data:`app.core.facts.ANNUAL_FORMS`, the newest accession (by filed date,
    then accession) is the newest annual report; its ``fy`` is the fiscal year
    it is for and the latest end among its year-long facts is the end of that
    year. An amendment that reports no year-long period (a cover page, Part III)
    is passed over. None when there is no such report, or its ``fy`` is more
    than :data:`MAX_LABEL_OFFSET` from the year its period ends in. Never
    raises on a malformed body: what cannot be read is skipped. With ``as_of``,
    only facts filed on or before that day are read.
    """
    annual = [
        found
        for raw in _entries(companyfacts)
        if (found := _annual_fact(raw)) and (as_of is None or found.filed <= as_of)
    ]
    if not annual:
        return None
    newest = max((fact.filed, fact.accession) for fact in annual)
    report = [fact for fact in annual if (fact.filed, fact.accession) == newest]
    last = max(report, key=lambda fact: (fact.end, fact.fy))
    offset = last.fy - last.end.year
    if abs(offset) > MAX_LABEL_OFFSET:
        return None
    return FiscalCalendar(last.end.month, last.end.day, offset, year_end=last.end)


# The years a statement names


@dataclass(frozen=True)
class PeriodMention:
    """One year a statement names: the words that name it, the year, and what kind it is.

    ``fiscal`` for a fiscal label ("fiscal 2026", "FY26"). ``dated`` for a year
    inside a date ("July 26, 2026", "June 2026", "2026-07-26"): that is a
    calendar year and nothing else. A bare year ("in 2026") is neither, and may
    be meant either way.
    """

    raw: str
    year: int
    fiscal: bool
    dated: bool = False


_LABEL = re.compile(r"(?i)(?P<prefix>fiscal(?:\s+years?)?|FY|CY)\s*(?P<mark>'?)(?P<digits>\d+)$")
_FOUR_DIGITS = re.compile(r"(?<!\d)\d{4}(?!\d)")
# What before a year makes it a fiscal label: "at fiscal year-end 2026" is the end of fiscal
# 2026. "the fiscal year ended 2026" is not: it names the calendar year the year ended in.
_FISCAL_END_BEFORE = re.compile(r"\bfiscal\s+(?:year|quarter)[-–\s]end\s*$", re.IGNORECASE)
# What joins a year to the fiscal label before it: "fiscal years 2025 and 2026".
_JOINED = re.compile(r"\s*(?:,\s*(?:and|or)?|and|or|to|through|[-–])\s*'?", re.IGNORECASE)


def _label_year(raw: str) -> tuple[int, bool] | None:
    """The year and fiscal flag of a period label, or None when its digits are no year.

    Four digits must be a year; two digits mean 20xx, but only after "FY", "CY"
    or an apostrophe ("fiscal 53 weeks" names no year).
    """
    match = _LABEL.search(raw)
    if match is None:
        return None
    digits, prefix = match.group("digits"), match.group("prefix").upper()
    fiscal = prefix != "CY"
    if len(digits) == 4 and int(digits) in YEARS:
        return int(digits), fiscal
    if len(digits) == 2 and (prefix in ("FY", "CY") or match.group("mark")):
        return 2000 + int(digits), fiscal
    return None


def _placed_mentions(text: str) -> list[tuple[int, int, PeriodMention]]:
    """Every year ``text`` names with the span of the words naming it, in order."""
    placed: list[tuple[int, int, PeriodMention]] = []

    def place(begin: int, end: int, mention: PeriodMention) -> None:
        """Keep ``mention`` unless its words overlap a mention already kept."""
        if not any(low < end and begin < high for low, high, _ in placed):
            placed.append((begin, end, mention))

    for begin, end in period_label_spans(text):
        raw = text[begin:end]
        label = _label_year(raw)
        if label is not None:
            place(begin, end, PeriodMention(raw, label[0], label[1]))
    for begin, end in sorted(date_spans(text), key=lambda span: (span[0], -span[1])):
        raw = text[begin:end]
        years = [int(m.group()) for m in _FOUR_DIGITS.finditer(raw) if int(m.group()) in YEARS]
        if years:
            place(begin, end, PeriodMention(raw, years[0], False, dated=True))
    for begin, end in year_spans(text):
        fiscal = _FISCAL_END_BEFORE.search(text, 0, begin) is not None
        place(begin, end, PeriodMention(text[begin:end], int(text[begin:end]), fiscal))
    placed.sort(key=lambda item: item[0])
    # A year joined to the fiscal label before it is fiscal too: "fiscal years 2025 and 2026".
    joined: list[tuple[int, int, PeriodMention]] = []
    for begin, end, mention in placed:
        if joined and not mention.fiscal and mention.raw.isdigit():
            _, previous_end, previous = joined[-1]
            if previous.fiscal and _JOINED.fullmatch(text, previous_end, begin):
                mention = PeriodMention(mention.raw, mention.year, True)
        joined.append((begin, end, mention))
    return joined


def period_mentions(text: str) -> list[PeriodMention]:
    """Every year ``text`` names, in order, each marked fiscal or not.

    Fiscal: "fiscal 2026", "fiscal year 2026", "fiscal years 2025 and 2026"
    (both), "FY2026", "FY 2026", "FY26", "fiscal '26" (two digits mean 20xx),
    "fiscal year-end 2026".
    Not fiscal: a year in a date-like context ("in 2025", "Q2 2026", "July
    2026", "January 25, 2026", "2026-01-25", "2024 and 2025", "CY2025"). What is
    a year is what the number check reads as one, never a quantity.
    """
    return [mention for _, _, mention in _placed_mentions(text)]


def shift_years(text: str, by: int) -> str:
    """``text`` with every year it names moved by ``by`` years, and nothing else changed.

    For planting a wrong period into a true statement, to measure what
    :func:`check_periods` catches. A four-digit year is replaced in place; a
    two-digit label ("FY26") keeps its two digits. What is not a year (a
    quantity, an amount) is left alone, because it is found the same way the
    check finds years.
    """
    pieces: list[str] = []
    cursor = 0
    for begin, end, mention in _placed_mentions(text):
        moved = _moved(text[begin:end], mention.year, by)
        if moved is None:
            continue
        pieces += [text[cursor:begin], moved]
        cursor = end
    return "".join(pieces) + text[cursor:]


def shift_each_year(text: str, by: int) -> list[tuple[PeriodMention, str]]:
    """One copy of ``text`` per year it names, with only that year moved by ``by`` years.

    For planting a single wrong year beside correct ones ("fiscal 2025, down
    from fiscal 2025" for "fiscal 2026, down from fiscal 2025"), which is how a
    real slip looks; :func:`shift_years` moves every year together. Each copy
    comes with the mention that was moved, in the order the text names them.
    A text naming no year gives an empty list. Years are found and moved as
    :func:`shift_years` finds and moves them.
    """
    planted: list[tuple[PeriodMention, str]] = []
    for begin, end, mention in _placed_mentions(text):
        moved = _moved(text[begin:end], mention.year, by)
        if moved is not None:
            planted.append((mention, text[:begin] + moved + text[end:]))
    return planted


def _moved(raw: str, year: int, by: int) -> str | None:
    """The words ``raw`` naming ``year`` with that year moved by ``by``; None if no digits are.

    A four-digit year is replaced in place; a two-digit label ("FY26") keeps two digits.
    """
    four = [m for m in _FOUR_DIGITS.finditer(raw) if int(m.group()) == year]
    if four:
        low, high = four[0].span()
        return raw[:low] + str(year + by) + raw[high:]
    two = re.search(r"\d{2}$", raw)
    if two is None:
        return None
    return raw[: two.start()] + f"{(year + by) % 100:02d}"


_EVIDENCE_YEAR = re.compile(r"(?<![\d,.$])(\d{4})(?![\d%]|[.,]\d)")
_EVIDENCE_LABEL = re.compile(r"(?i)\b(?:FY|CY)\s?'?(\d{2})\b|\bfiscal(?:\s+years?)?\s+'(\d{2})\b")


def years_in(text: str) -> set[int]:
    """Every year an excerpt shows, in any context: generous, for evidence.

    Any standalone four-digit number in :data:`EVIDENCE_YEARS` (1900 to 2100,
    the years :mod:`app.core.numcheck` reads in a statement) that is not part of
    a longer number, an amount or a percentage, plus two-digit fiscal labels
    ("FY26", "fiscal '26" give 2026).
    """
    years = {int(match.group(1)) for match in _EVIDENCE_YEAR.finditer(text)}
    years = {year for year in years if year in EVIDENCE_YEARS}
    for match in _EVIDENCE_LABEL.finditer(text):
        years.add(2000 + int(match.group(1) or match.group(2)))
    return years


# The check


@dataclass(frozen=True)
class UnplacedYear:
    """One year a statement names that its evidence does not carry.

    ``raw`` is the words that name it, ``comparative`` whether it is one or two
    years before the fiscal year of a filing quoted or a cited figure, and
    ``detail`` the sentence that says so (also in :attr:`PeriodCheck.details`).
    """

    raw: str
    comparative: bool
    detail: str


@dataclass(frozen=True)
class PeriodCheck:
    """The outcome of :func:`check_periods`.

    ``status`` is "none" when the statement names no year, "passed" when every
    year it names is in its evidence, "unverified" otherwise. ``details`` has
    one sentence per mention (and one when the fiscal calendar could not be
    read); ``checked`` counts mentions; ``unverified`` lists the words of each
    mention not found, and ``comparative`` those of them that are one or two
    years before the fiscal year of a filing quoted or a cited figure.
    ``unplaced`` holds the same mentions as records, in order, so that nothing
    downstream has to read a sentence back.
    """

    status: PeriodStatus
    details: list[str]
    checked: int
    unverified: list[str]
    comparative: list[str]
    unplaced: tuple[UnplacedYear, ...] = field(default=())


@dataclass
class _Evidence:
    """The years the evidence carries, each with the period end that gives it."""

    quoted: set[int]
    filing_fiscal: dict[int, date]
    filing_calendar: dict[int, date]
    figure_fiscal: dict[int, date]
    figure_calendar: dict[int, date]


def _fiscal_years(day: date, calendar: FiscalCalendar | None) -> list[int]:
    return [calendar.fiscal_year(day)] if calendar else [day.year, day.year + 1]


def _figure_ends(metrics: Sequence[Metric]) -> list[date]:
    """Each cited figure's period end and the end of each of its inputs, readable ones only."""
    ends = [_iso_date(metric.period_end) for metric in metrics]
    ends += [_iso_date(ref.end) for metric in metrics for ref in metric.inputs]
    return [end for end in ends if end is not None]


def _evidence(
    excerpts: Sequence[tuple[str, date | None]],
    metrics: Sequence[Metric],
    calendar: FiscalCalendar | None,
) -> _Evidence:
    found = _Evidence(set(), {}, {}, {}, {})
    for text, period_end in excerpts:
        found.quoted |= years_in(text)
        if period_end is not None:
            for year in _fiscal_years(period_end, calendar):
                found.filing_fiscal.setdefault(year, period_end)
            found.filing_calendar.setdefault(period_end.year, period_end)
    for end in _figure_ends(metrics):
        for year in _fiscal_years(end, calendar):
            found.figure_fiscal.setdefault(year, end)
        found.figure_calendar.setdefault(end.year, end)
    return found


def _passing(mention: PeriodMention, evidence: _Evidence) -> str | None:
    """The sentence saying where ``mention`` is in the evidence, or None when it is not."""
    year, raw = mention.year, mention.raw
    if year in evidence.quoted:
        return IN_QUOTE.format(raw=raw)
    fiscals = [(evidence.filing_fiscal, FILING_FISCAL), (evidence.figure_fiscal, FIGURE_FISCAL)]
    calendars = [(evidence.filing_calendar, FILING_YEAR), (evidence.figure_calendar, FIGURE_YEAR)]
    if mention.fiscal:
        candidates = fiscals
    elif mention.dated:
        candidates = calendars
    else:
        candidates = calendars + fiscals
    for years, sentence in candidates:
        if year in years:
            return sentence.format(raw=raw, end=years[year].isoformat())
    return None


def check_periods(
    statement: str,
    excerpts: Sequence[tuple[str, date | None]],
    metrics: Sequence[Metric],
    calendar: FiscalCalendar | None,
) -> PeriodCheck:
    """Check that every year ``statement`` names is in its evidence. See the module notes.

    ``excerpts`` are each quoted excerpt's text with the period end of the
    filing it is from (None for a source that is not a filing); ``metrics`` are
    the cited figures; ``calendar`` is the company's fiscal calendar, or None
    when it could not be read.
    """
    mentions = period_mentions(statement)
    if not mentions:
        return PeriodCheck("none", [], 0, [], [])
    evidence = _evidence(excerpts, metrics, calendar)
    fiscal_ends = set(evidence.filing_fiscal) | set(evidence.figure_fiscal)
    details: list[str] = [] if calendar else [NO_CALENDAR]
    unplaced: list[UnplacedYear] = []
    for mention in mentions:
        sentence = _passing(mention, evidence)
        if sentence is None:
            sentence = f"{mention.raw} {NOT_FOUND}"
            is_comparative = any(mention.year + gap in fiscal_ends for gap in COMPARATIVE_GAPS)
            if is_comparative:
                sentence += COMPARATIVE_NOTE
            unplaced.append(UnplacedYear(mention.raw, is_comparative, sentence))
        details.append(sentence)
    status: PeriodStatus = "unverified" if unplaced else "passed"
    return PeriodCheck(
        status,
        details,
        len(mentions),
        [year.raw for year in unplaced],
        [year.raw for year in unplaced if year.comparative],
        tuple(unplaced),
    )
