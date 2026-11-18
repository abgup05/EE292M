"""Current reports (8-K): what each item is, which claims it bears on, and what it postdates.

Pure rules, no network, store or clock. :mod:`app.services.events` lists a
company's 8-Ks, reads some of them and hands the records here.

- **Items.** :data:`ITEMS` is SEC's list of Form 8-K items, 1.01 to 9.01, with
  SEC's own titles, each in one :class:`Category`. A number not in the list is
  kept, with category "other", and labelled unknown.
- **Claims.** :func:`claim_categories` gives a claim the categories whose
  lexicon (:data:`CLAIM_LEXICON`) it matches as whole words, and leadership also
  when a capitalised name is followed within a few words by a word of leaving
  ("Jensen is gone"). Only the :data:`SUBSTANTIVE` categories have a lexicon: the
  others (results, disclosure, governance, exhibits, other) are boilerplate that
  points at an exhibit.
- **Supersession.** An event is later than a finding when it was filed after
  every filing the finding cites; :func:`predating` marks a finding with each
  later event of one of its claim's categories. It is reported, never withheld:
  the verdict rule (:mod:`app.core.policy`) does not read it.
- **The honest negative.** :func:`events_note` says, for a claim with a
  substantive category, that no 8-K since the annual report reports it, and how
  far the record goes; it never says the claim is false.
"""

from __future__ import annotations

import re
from collections.abc import Iterable, Sequence
from datetime import date
from enum import StrEnum

from app.core import limits, policy
from app.core.documents import Document, Section
from app.core.event_models import AsOf, Event, EventCounts, EventItem, EventStatus, Predating
from app.core.text import STOPWORDS, sentence_spans


class Category(StrEnum):
    """What an 8-K item is about. The order is the order categories are listed in."""

    leadership = "leadership"
    accounting = "accounting"
    deal = "deal"
    restructuring = "restructuring"
    incident = "incident"
    financing = "financing"
    control = "control"
    listing = "listing"
    results = "results"
    governance = "governance"
    disclosure = "disclosure"
    exhibits = "exhibits"
    other = "other"


_C = Category
# SEC's list of Form 8-K items (General Instructions B and the form itself), with SEC's titles.
ITEMS: dict[str, tuple[str, Category]] = {
    "1.01": ("Entry into a Material Definitive Agreement", _C.deal),
    "1.02": ("Termination of a Material Definitive Agreement", _C.deal),
    "1.03": ("Bankruptcy or Receivership", _C.control),
    "1.04": ("Mine Safety - Reporting of Shutdowns and Patterns of Violations", _C.other),
    "1.05": ("Material Cybersecurity Incidents", _C.incident),
    "2.01": ("Completion of Acquisition or Disposition of Assets", _C.deal),
    "2.02": ("Results of Operations and Financial Condition", _C.results),
    "2.03": (
        "Creation of a Direct Financial Obligation or an Obligation under an Off-Balance Sheet "
        "Arrangement of a Registrant",
        _C.financing,
    ),
    "2.04": (
        "Triggering Events That Accelerate or Increase a Direct Financial Obligation or an "
        "Obligation under an Off-Balance Sheet Arrangement",
        _C.financing,
    ),
    "2.05": ("Costs Associated with Exit or Disposal Activities", _C.restructuring),
    "2.06": ("Material Impairments", _C.restructuring),
    "3.01": (
        "Notice of Delisting or Failure to Satisfy a Continued Listing Rule or Standard; "
        "Transfer of Listing",
        _C.listing,
    ),
    "3.02": ("Unregistered Sales of Equity Securities", _C.financing),
    "3.03": ("Material Modification to Rights of Security Holders", _C.governance),
    "4.01": ("Changes in Registrant's Certifying Accountant", _C.accounting),
    "4.02": (
        "Non-Reliance on Previously Issued Financial Statements or a Related Audit Report or "
        "Completed Interim Review",
        _C.accounting,
    ),
    "5.01": ("Changes in Control of Registrant", _C.control),
    "5.02": (
        "Departure of Directors or Certain Officers; Election of Directors; Appointment of "
        "Certain Officers; Compensatory Arrangements of Certain Officers",
        _C.leadership,
    ),
    "5.03": (
        "Amendments to Articles of Incorporation or Bylaws; Change in Fiscal Year",
        _C.governance,
    ),
    "5.04": (
        "Temporary Suspension of Trading Under Registrant's Employee Benefit Plans",
        _C.other,
    ),
    "5.05": (
        "Amendment to Registrant's Code of Ethics, or Waiver of a Provision of the Code of Ethics",
        _C.governance,
    ),
    "5.06": ("Change in Shell Company Status", _C.other),
    "5.07": ("Submission of Matters to a Vote of Security Holders", _C.governance),
    "5.08": ("Shareholder Director Nominations", _C.governance),
    "6.01": ("ABS Informational and Computational Material", _C.other),
    "6.02": ("Change of Servicer or Trustee", _C.other),
    "6.03": ("Change in Credit Enhancement or Other External Support", _C.other),
    "6.04": ("Failure to Make a Required Distribution", _C.other),
    "6.05": ("Securities Act Updating Disclosure", _C.other),
    "6.06": ("Static Pool", _C.other),
    "6.10": ("Alternative Filings of Asset-Backed Issuers", _C.other),
    "7.01": ("Regulation FD Disclosure", _C.disclosure),
    "8.01": ("Other Events", _C.disclosure),
    "9.01": ("Financial Statements and Exhibits", _C.exhibits),
}
UNKNOWN_ITEM_TITLE = "Not an item number in SEC's list of Form 8-K items"

# The categories with a claim lexicon: an 8-K of one of these can bear on a claim.
SUBSTANTIVE: tuple[Category, ...] = (
    _C.leadership,
    _C.accounting,
    _C.deal,
    _C.restructuring,
    _C.incident,
    _C.financing,
    _C.control,
    _C.listing,
)
CATEGORY_LABELS: dict[Category, str] = {
    _C.leadership: "Leadership",
    _C.accounting: "Accounting",
    _C.deal: "Deal",
    _C.restructuring: "Restructuring",
    _C.incident: "Incident",
    _C.financing: "Financing",
    _C.control: "Control",
    _C.listing: "Listing",
    _C.results: "Results",
    _C.governance: "Governance",
    _C.disclosure: "Disclosure",
    _C.exhibits: "Exhibits",
    _C.other: "Other",
}
# What an 8-K of a substantive category reports, in words a sentence can carry.
CATEGORY_WORDS: dict[Category, str] = {
    _C.leadership: "a change of directors or officers",
    _C.accounting: "a change of auditor or a restatement",
    _C.deal: "an acquisition, a disposal or a material agreement",
    _C.restructuring: "a restructuring or a material impairment",
    _C.incident: "a material cybersecurity incident",
    _C.financing: "a new or accelerated debt obligation or an unregistered sale of shares",
    _C.control: "a bankruptcy or a change in control",
    _C.listing: "a delisting notice or a transfer of listing",
}

_ORDER = {category: position for position, category in enumerate(Category)}
MONTHS = ("Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec")


def describe_item(number: str) -> EventItem:
    """The item record for ``number``: SEC's title and its category, or unknown."""
    entry = ITEMS.get(number)
    if entry is None:
        return EventItem(
            number=number, title=UNKNOWN_ITEM_TITLE, category=_C.other.value, known=False
        )
    title, category = entry
    return EventItem(number=number, title=title, category=category.value)


def items_of(category: Category) -> list[str]:
    """The item numbers of ``category``, in numeric order."""
    return [number for number, (_, owner) in ITEMS.items() if owner == category]


def _category_of(number: str) -> Category:
    entry = ITEMS.get(number)
    return entry[1] if entry else _C.other


def event_categories(numbers: Iterable[str]) -> list[Category]:
    """The categories of these item numbers, each once, in :class:`Category` order."""
    return sorted({_category_of(number) for number in numbers}, key=_ORDER.__getitem__)


def is_substantive(categories: Iterable[str]) -> bool:
    """True when one of ``categories`` is one of :data:`SUBSTANTIVE`."""
    return any(category in SUBSTANTIVE for category in categories)


def _item_label(numbers: Sequence[str]) -> str:
    """ "Item 5.02", "Items 1.01 and 2.03", "Items 1.01, 1.02 and 2.01"."""
    if len(numbers) == 1:
        return f"Item {numbers[0]}"
    return f"Items {', '.join(numbers[:-1])} and {numbers[-1]}"


def day_label(value: str | None) -> str:
    """A ``YYYY-MM-DD`` date as "12 Nov 2026"; anything else unchanged, None as ""."""
    if not value:
        return ""
    try:
        day = date.fromisoformat(value)
    except ValueError:
        return value
    return f"{day.day} {MONTHS[day.month - 1]} {day.year}"


# Reading a split 8-K

_SECTION_ITEMS = re.compile(r"^Items? (\d{1,2}\.\d{2}(?:(?:, | and )\d{1,2}\.\d{2})*)\.")
_ITEM_NUMBER = re.compile(r"\d{1,2}\.\d{2}")


def section_numbers(heading: str) -> tuple[str, ...]:
    """The item numbers a section heading written by :mod:`app.sources.current_report` names."""
    match = _SECTION_ITEMS.match(heading)
    return tuple(_ITEM_NUMBER.findall(match.group(1))) if match else ()


def item_sections(document: Document) -> dict[str, Section]:
    """Each item number of a split 8-K and the section under it (the first, if two name it)."""
    found: dict[str, Section] = {}
    for section in document.sections:
        for number in section_numbers(section.heading):
            found.setdefault(number, section)
    return found


_SENTENCE_END = re.compile(r"[.!?][\"'”’)\]]*$")
MIN_OPENING_WORDS = 4


def opening_sentences(text: str, limit: int = limits.EVENT_OPENING_SENTENCES) -> list[str]:
    """The first ``limit`` sentences of an item's text, each an exact slice of it.

    A line that is no sentence is passed over: a sub-item marker such as "(b)", a
    sub-heading with no closing full stop, a table cell, anything under
    :data:`MIN_OPENING_WORDS` words.
    """
    kept: list[str] = []
    for start, end in sentence_spans(text):
        sentence = text[start:end]
        if len(sentence.split()) < MIN_OPENING_WORDS or not _SENTENCE_END.search(sentence):
            continue
        kept.append(sentence)
        if len(kept) >= limit:
            break
    return kept


def _whole(pattern: str) -> str:
    """``pattern`` as whole words: no letter, digit or hyphen joined on either side."""
    return rf"(?<![\w-])(?:{pattern})(?![\w-])"


# Officer roles an Item 5.02 names: (canonical role, pattern). A blocked phrase ("Board of
# Directors") is consumed and names no role; earlier patterns win where two overlap.
_ROLE_PATTERNS: tuple[tuple[str | None, str], ...] = (
    (None, r"board of directors|board of director"),
    ("Principal Executive Officer", r"principal executive officer"),
    ("Principal Financial Officer", r"principal financial officer"),
    ("Principal Accounting Officer", r"principal accounting officer"),
    ("Chief Executive Officer", r"chief executive officer|ceo"),
    ("Chief Financial Officer", r"chief financial officer|cfo"),
    ("Chief Operating Officer", r"chief operating officer|coo"),
    ("Chief Accounting Officer", r"chief accounting officer|cao"),
    ("Chief Technology Officer", r"chief technology officer|cto"),
    ("Chief Legal Officer", r"chief legal officer|clo"),
    ("General Counsel", r"general counsel"),
    ("Lead Independent Director", r"lead independent director"),
    ("Executive Vice President", r"executive vice president|evp"),
    ("Senior Vice President", r"senior vice president|senior vp|svp"),
    ("Vice President", r"vice president|vp"),
    ("President", r"president"),
    ("Chair", r"executive chair(?:man|woman|person)?|chair(?:man|woman|person)?(?: of the board)?"),
    ("Director", r"directors?|member of the board|board members?"),
    ("Treasurer", r"treasurer"),
    ("Secretary", r"secretary"),
    ("Controller", r"controller"),
)
_ROLES = [(role, re.compile(_whole(pattern), re.IGNORECASE)) for role, pattern in _ROLE_PATTERNS]


def officer_roles(text: str) -> list[str]:
    """The officer roles ``text`` names, as whole words, each once, in order of first mention."""
    claimed: list[tuple[int, int]] = []
    named: list[tuple[int, str]] = []
    for role, pattern in _ROLES:
        for match in pattern.finditer(text):
            start, end = match.span()
            if any(start < taken_end and taken_start < end for taken_start, taken_end in claimed):
                continue
            claimed.append((start, end))
            if role is not None:
                named.append((start, role))
    return list(dict.fromkeys(role for _, role in sorted(named)))


# The categories of a claim

CLAIM_LEXICON: dict[Category, tuple[str, ...]] = {
    _C.leadership: (
        r"ceo|cfo|coo|cto",
        r"chief \w+ officer|chief executive",
        r"chair(?:man|woman)?(?: of the board)?",
        r"board of directors|board members?|board seats?",
        r"directors",
        r"(?:senior |top )?executives|executive team|management team|leadership team",
        r"leadership (?:change|changes|transition|turnover)|management (?:change|changes|turnover)",
        r"founder|succession|successor",
        r"resign(?:s|ed|ing|ation|ations)?",
        r"step(?:s|ped|ping)? down",
        r"departure|departed|ousted|fired",
    ),
    _C.accounting: (
        r"restat(?:e|es|ed|ing|ement|ements)",
        r"auditors?|audit firm|accounting firm|certifying accountant",
        r"non-reliance|no longer (?:be )?rel(?:y|ied) (?:up)?on",
        r"material weakness(?:es)?",
        r"accounting (?:errors?|irregularit(?:y|ies)|fraud|scandal|problems?)",
        r"misstat(?:ed|ement|ements)",
    ),
    _C.deal: (
        r"acquir(?:e|es|ed|ing)|acquisitions?",
        r"merg(?:e|es|ed|er|ers|ing)",
        r"takeover|take-over|buyout",
        r"divest(?:s|ed|ing|iture|itures)?",
        r"spin-off|spinoff|spin off|spun off",
        r"joint venture|definitive agreement|material agreement|merger agreement",
        r"agreements? (?:\w+ ){0,3}(?:terminated|cancell?ed)",
        r"terminat(?:e|es|ed|ing|ion) (?:of )?(?:the |a |an |its )?(?:\w+ ){0,2}agreements?",
        r"deal",
    ),
    _C.restructuring: (
        r"restructur(?:e|es|ed|ing)",
        r"reorgani[sz](?:e|es|ed|ing|ation|ations)",
        r"layoffs?|laid off|lay(?:s|ing)? off",
        r"job cuts|headcount reductions?|workforce reductions?|reductions? in force",
        r"impair(?:ed|ment|ments)",
        r"write-?downs?|write-?offs?|written (?:off|down)",
        r"plant closures?|facility closures?|exit costs",
        r"clos(?:e|es|ed|ing) (?:\w+ ){0,2}(?:factories|plants|facilities|stores|offices|sites)",
        r"exit(?:s|ed|ing)? (?:the |a |its |from )?(?:\w+ ){0,2}"
        r"(?:business|businesses|markets?|segments?|operations)",
    ),
    _C.incident: (
        r"cyber ?attacks?|cybersecurity incidents?|cyber incidents?|security incidents?",
        r"data breach(?:es)?|security breach(?:es)?",
        r"ransomware|malware|hack(?:ed|ers?|ing)?",
        r"unauthori[sz]ed access",
    ),
    _C.financing: (
        r"debt",
        r"borrow(?:s|ed|ing|ings)?|loans?|term loan",
        r"credit facilit(?:y|ies)|revolving credit|revolver",
        r"bonds?",
        r"(?:senior|convertible|unsecured|secured) notes|notes offering",
        r"(?:issu|retir|redeem|repa|repurchas)(?:e|es|ed|ing|id|ys)? (?:\S+ ){0,5}notes",
        r"covenants?|default(?:s|ed)?",
        r"dilut(?:e|es|ed|ing|ion|ive)",
        r"private placement|equity offering|share issuance",
        r"refinanc(?:e|es|ed|ing)",
        r"financing",
    ),
    _C.control: (
        r"bankrupt(?:cy)?|chapter 7|chapter 11|receivership",
        r"insolven(?:t|cy)",
        r"change (?:in|of) control",
        r"takeover|take-over",
        r"controlling (?:stake|interest|shareholder)|majority stake",
        r"go(?:es|ing)? private|taken private",
    ),
    _C.listing: (
        r"delist(?:s|ed|ing)?",
        r"listing (?:rules?|standards?|requirements?)",
        r"minimum bid price|deficiency notice",
        r"transfer (?:of |its )?listing",
    ),
}
_LEXICON = {
    category: re.compile(_whole("|".join(patterns)), re.IGNORECASE)
    for category, patterns in CLAIM_LEXICON.items()
}

# A name and a word of leaving after it: "Jensen is gone", "Lisa Su stepped down".
# "replaced" only as the passive ("was replaced"): "Apple replaced Intel chips" names no departure.
_LEAVING = (
    r"gone|left|leaving|leaves|departed|departing|resigned|resigns|resigning|retired|retires|"
    r"retiring|stepped down|steps down|stepping down|fired|ousted|out as|"
    r"(?:was|has been|had been|is being|will be|been) replaced"
)
_BETWEEN = r"is|has|was|had|have|been|just|finally|now|already|officially|reportedly|will|be|being"
_NAME_LEAVING = re.compile(
    rf"(?<![\w-])(?P<name>[A-Z][a-z]+(?:[-'’][A-Za-z]+)?(?: [A-Z][a-z]+(?:[-'’][A-Za-z]+)?)*)"
    rf"(?:'s|’s)? (?:(?:{_BETWEEN}) ){{0,3}}(?:{_LEAVING})(?![\w-])"
)
# An auditor that resigns or is dismissed is Item 4.01 (accounting), not an officer's departure.
_AUDITOR_LEAVING = re.compile(
    _whole(
        r"(?:auditors?|accountants?|audit firm|accounting firm) (?:\w+ ){0,2}"
        r"(?:resign(?:s|ed|ing)?|quit|dismissed|fired|departed|stepped down)"
    ),
    re.IGNORECASE,
)
# The leadership words that are only a leaving, with no officer named.
_LEAVING_ONLY = re.compile(
    _whole(
        r"resign(?:s|ed|ing|ation|ations)?|step(?:s|ped|ping)? down|departure|departed|"
        r"ousted|fired"
    ),
    re.IGNORECASE,
)
# Capitalised words that start a sentence and are no name: "Growth is gone".
_NOT_NAMES = frozenset(STOPWORDS) | frozenset(
    """
    growth demand supply revenue revenues sales margin margins profit profits earnings momentum
    pricing competition inventory guidance cash debt share shares stock market moat lead edge
    advantage valuation upside hype risk volume capacity backlog business segment customer
    customers gaming data everything nothing something buy sell hold
    """.split()
)


def _names_leaving(text: str) -> bool:
    for match in _NAME_LEAVING.finditer(text):
        first = match.group("name").split()[0].casefold()
        if first not in _NOT_NAMES:
            return True
    return False


def claim_categories(text: str) -> list[Category]:
    """The substantive categories ``text`` bears on, by rule, in :class:`Category` order."""
    found = {category for category, pattern in _LEXICON.items() if pattern.search(text)}
    if _C.leadership in found and _AUDITOR_LEAVING.search(text):
        # Leadership only because an auditor leaves: drop it unless an officer word is there too.
        rest = _LEAVING_ONLY.sub(" ", _AUDITOR_LEAVING.sub(" ", text))
        if not _LEXICON[_C.leadership].search(rest):
            found.discard(_C.leadership)
    if _names_leaving(text):
        found.add(_C.leadership)
    return sorted(found, key=_ORDER.__getitem__)


# Which 8-Ks are read, and how many


def choose_reads(timeline: Sequence[Event], newest_periodic_filed: str, cap: int) -> list[Event]:
    """The events whose documents are read, newest first; marks the rest of ``timeline``.

    An event filed after ``newest_periodic_filed`` is read, and so is one of a
    substantive category since the annual report; the newest ``cap`` of these are
    read and the others marked ``capped``. Everything else is ``index_only``. Each
    event's ``after_periodic`` is set.
    """
    ordered = sorted(timeline, key=lambda e: (e.filed_date, e.accession), reverse=True)
    wanted: list[Event] = []
    for item in ordered:
        item.after_periodic = item.filed_date > newest_periodic_filed
        if item.after_periodic or item.substantive:
            if len(wanted) < cap:
                wanted.append(item)
            else:
                item.status = EventStatus.capped
        else:
            item.status = EventStatus.index_only
    return wanted


def count_events(timeline: Sequence[Event], cap: int, annual_filed: str | None) -> EventCounts:
    """How many events were listed and what became of each, and the sentence that says so."""
    tally = {status: 0 for status in EventStatus}
    for item in timeline:
        tally[item.status] += 1
    counts = EventCounts(
        listed=len(timeline),
        wanted=len(timeline) - tally[EventStatus.index_only],
        read=tally[EventStatus.read],
        failed=tally[EventStatus.failed],
        capped=tally[EventStatus.capped],
        out_of_time=tally[EventStatus.out_of_time],
        index_only=tally[EventStatus.index_only],
        cap=cap,
    )
    line = policy.EVENT_COUNTS.format(
        listed=counts.listed,
        annual=day_label(annual_filed),
        read=counts.read,
        failed=counts.failed,
        capped=counts.capped,
        cap=cap,
        index_only=counts.index_only,
    )
    if counts.out_of_time:
        line += policy.EVENT_COUNTS_TIME.format(out_of_time=counts.out_of_time)
    counts.line = line
    return counts


def pinned_items(
    categories: Sequence[str], timeline: Sequence[Event], cap: int
) -> list[tuple[Event, EventItem]]:
    """The item sections offered to a claim: of its categories, from events read, newest first.

    At most ``cap``; an item whose section was not found in its document is passed over.
    """
    wanted = set(categories)
    ordered = sorted(timeline, key=lambda e: (e.filed_date, e.accession), reverse=True)
    chosen: list[tuple[Event, EventItem]] = []
    for item_event in ordered:
        if item_event.status != EventStatus.read:
            continue
        for item in item_event.items:
            if item.category in wanted and item.found and len(chosen) < cap:
                chosen.append((item_event, item))
    return chosen


# Supersession


def predating(
    cited_filed: Sequence[str], categories: Sequence[str], timeline: Sequence[Event]
) -> list[Predating]:
    """The events later than a finding on one of its claim's categories, newest first.

    ``cited_filed`` are the filing dates of every filing the finding cites; an event
    is later when it was filed after all of them. A finding that cites no dated
    filing is never marked. The event's items in the index decide its category, so
    an 8-K listed but not read still counts.
    """
    if not cited_filed or not categories:
        return []
    newest_cited = max(cited_filed)
    wanted = set(categories)
    marks: list[Predating] = []
    for item_event in sorted(timeline, key=lambda e: (e.filed_date, e.accession), reverse=True):
        if item_event.filed_date <= newest_cited:
            continue
        numbers = [item.number for item in item_event.items if item.category in wanted]
        if not numbers:
            continue
        marks.append(
            Predating(
                event_id=item_event.id,
                filed_date=item_event.filed_date,
                items=numbers,
                label=policy.PREDATES_LABEL.format(
                    form=item_event.form,
                    date=day_label(item_event.filed_date),
                    items=_item_label(numbers),
                ),
            )
        )
    return marks


def _words(categories: Iterable[str]) -> str:
    phrases = [CATEGORY_WORDS[Category(c)] for c in categories if Category(c) in CATEGORY_WORDS]
    return " or ".join(phrases)


def claim_caution(marks: Sequence[Sequence[Predating]], timeline: Sequence[Event]) -> str:
    """The caution of a claim whose verdict rests on a predated finding, else "".

    ``marks`` are the :func:`predating` marks of each of the claim's verified
    findings. The caution names the newest event among them.
    """
    newest = max(
        (mark for finding_marks in marks for mark in finding_marks),
        key=lambda mark: mark.filed_date,
        default=None,
    )
    if newest is None:
        return ""
    by_id = {item.id: item for item in timeline}
    item_event = by_id[newest.event_id]
    categories = event_categories(newest.items)
    return policy.EVENT_CAUTION.format(
        form=item_event.form,
        date=day_label(item_event.filed_date),
        items=_item_label(newest.items),
        words=_words(categories),
    )


def _subjects(categories: Sequence[Category]) -> str:
    """Each category's words and its items: "a change of directors or officers (Item 5.02)"."""
    return " or ".join(
        f"{CATEGORY_WORDS[category]} ({_item_label(items_of(category))})" for category in categories
    )


def events_note(
    categories: Sequence[str],
    timeline: Sequence[Event],
    annual_filed: str | None,
    newest_filed: str | None,
    index_error: str,
) -> str:
    """What the timeline says, and does not say, about a claim's substantive categories.

    For a category with no event since the annual report: that none is reported,
    and the date of the newest filing read, after which nothing is in the record.
    For a category whose events were listed and none read: the newest of them and
    why it was not read. With the index unread: that the answer is not known.
    Never a verdict; "" for a claim with no substantive category.
    """
    substantive = [Category(c) for c in categories if Category(c) in SUBSTANTIVE]
    if not substantive:
        return ""
    if index_error:
        return policy.EVENT_INDEX_UNREAD.format(
            error=index_error,
            annual=day_label(annual_filed) or "the annual report",
            subjects=_subjects(substantive),
        )
    sentences: list[str] = []
    missing = [c for c in substantive if not any(c.value in e.categories for e in timeline)]
    if missing:
        sentences.append(
            policy.EVENT_ABSENT.format(
                annual=day_label(annual_filed),
                subjects=_subjects(missing),
                newest=day_label(newest_filed),
            )
        )
    for category in substantive:
        if category in missing:
            continue
        of_category = sorted(
            (e for e in timeline if category.value in e.categories),
            key=lambda e: (e.filed_date, e.accession),
            reverse=True,
        )
        if any(e.status == EventStatus.read for e in of_category):
            continue
        newest = of_category[0]
        numbers = [item.number for item in newest.items if item.category == category.value]
        sentences.append(
            policy.EVENT_NOT_READ.format(
                form=newest.form,
                date=day_label(newest.filed_date),
                items=_item_label(numbers),
                reason=(newest.reason or newest.status.value).rstrip("."),
            )
        )
    return " ".join(dict.fromkeys(sentences))


# How old the evidence is


def _days(count: int) -> str:
    return f"{count} day{'s' if count != 1 else ''}"


PERIODIC_FORMS = ("10-K", "10-Q")


def build_as_of(
    *,
    filings: Sequence[tuple[str, str, str]],
    annual_filed: str | None,
    started: date,
    counts: EventCounts,
    index_error: str,
    in_run: bool = True,
) -> AsOf:
    """The as-of block from every filing read, as (form, filing date, URL).

    The newest of any form, the newest periodic report (10-K or 10-Q), and the
    days from the newest to ``started``: the start of the run, or today outside one
    (``in_run`` False), which the line says.
    """
    when = policy.AS_OF_RUN if in_run else policy.AS_OF_TODAY
    dated = sorted((filing for filing in filings if filing[1]), key=lambda f: f[1], reverse=True)
    periodic = [filing for filing in dated if filing[0] in PERIODIC_FORMS]
    as_of = AsOf(annual_filed=annual_filed, counts=counts, index_error=index_error)
    if not dated:
        as_of.line = policy.AS_OF_NOTHING_READ
        return as_of
    form, filed, url = dated[0]
    as_of.newest_form, as_of.newest_filed, as_of.newest_url = form, filed, url
    try:
        as_of.days_since_newest = (started - date.fromisoformat(filed)).days
    except ValueError:
        as_of.days_since_newest = None
    days = _days(as_of.days_since_newest) if as_of.days_since_newest is not None else "some days"
    if periodic:
        as_of.periodic_form, as_of.periodic_filed = periodic[0][0], periodic[0][1]
        as_of.line = policy.AS_OF_LINE.format(
            date=day_label(filed),
            form=form,
            days=days,
            when=when,
            periodic_form=as_of.periodic_form,
            periodic_date=day_label(as_of.periodic_filed),
        )
    else:
        as_of.line = policy.AS_OF_NO_PERIODIC.format(
            date=day_label(filed), form=form, days=days, when=when
        )
    return as_of
