"""Triage: does one new filing bear on any claim of a watched thesis, and why?

Pure and deterministic: claims and one filing (and, for a 10-K or 10-Q, its comparison
with the filing of its form before it) in, a :class:`~app.core.watch_models.Triage` out.
No network, store, clock or model. It reuses the rules of version 12 and milestone 8:

- **An 8-K** (or 8-K/A) bears on a claim when one of its items is of a category of the
  claim (:func:`app.core.events.claim_categories`, the item's category from
  :data:`app.core.events.ITEMS`, as the index lists the items).
- **Item 2.02** (results of operations) bears on every claim: new results are announced,
  and the figures arrive with the quarterly report.
- **An 8-K whose items are all routine** (exhibits, a vote, Regulation FD, other events)
  and match no claim bears on nothing; so does a substantive 8-K on no claim's subject.
  Each says so in the summary, which the inbox shows.
- **An 8-K whose index lists no items** cannot be ruled out, so it bears on every claim.
- **A 10-K or 10-Q** always bears on every claim (new reported figures). The changed
  paragraphs that share words with each claim are named by the rule of
  :mod:`app.core.claim_changes` (two shared content terms, best BM25 first).

**Extension point.** ``extra_rules`` are further rules, each a function of the claims
and the filing returning (claim id, reason) pairs; any pair makes that claim bear. The
watch passes :data:`app.watch.service.EXTRA_TRIAGE_RULES`, empty in version 13; version 14
adds "a compiled claim's computed outcome flipped" there.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence

from ed_v13.core import watch_policy as wording
from ed_v13.core.change_models import FilingChanges
from ed_v13.core.claim_change_models import RelevantChange
from ed_v13.core.claim_changes import relevant_changes
from ed_v13.core.documents import FilingRef
from ed_v13.core.events import (
    CATEGORY_WORDS,
    Category,
    claim_categories,
    day_label,
    describe_item,
)
from ed_v13.core.models import Claim
from ed_v13.core.watch_models import (
    ClaimTriage,
    FilingItem,
    NamedParagraph,
    Triage,
    TriageRule,
    WatchedFiling,
)

# A further triage rule: the claims and the filing in, (claim id, reason) pairs out.
ExtraRule = Callable[[Sequence[Claim], WatchedFiling], Sequence[tuple[str, str]]]

CURRENT_FORMS = ("8-K", "8-K/A")


def _item_label(numbers: Sequence[str]) -> str:
    """ "Item 5.02", "Items 1.01 and 2.03", "Items 1.01, 1.02 and 2.01"."""
    if len(numbers) == 1:
        return f"Item {numbers[0]}"
    return f"Items {', '.join(numbers[:-1])} and {numbers[-1]}"


def thesis_claims(
    texts: Sequence[str], queries: Mapping[str, Sequence[str]] | None = None
) -> list[Claim]:
    """The thesis's claims as triage reads them: ids c1, c2, ... and categories by rule.

    ``queries`` maps a claim's text, case folded, to the search queries a run wrote for
    it, which the paragraph rule also matches on (as :mod:`app.core.claim_changes` does).
    """
    found = queries or {}
    return [
        Claim(
            id=f"c{number}",
            text=text,
            queries=list(found.get(text.casefold(), ())),
            categories=[category.value for category in claim_categories(text)],
        )
        for number, text in enumerate(texts, start=1)
    ]


def watched_filing(ref: FilingRef) -> WatchedFiling:
    """What the watch keeps of one filing EDGAR's index lists, with the line a page shows."""
    items = [describe_item(number) for number in ref.items]
    label = f"{ref.form} of {day_label(ref.filed_date)}"
    if ref.items:
        label += f", {_item_label(list(ref.items))}"
    return WatchedFiling(
        accession=ref.accession,
        form=ref.form,
        filed_date=ref.filed_date,
        report_date=ref.period_end,
        url=ref.url,
        items=[FilingItem(number=i.number, title=i.title, category=i.category) for i in items],
        label=label,
    )


def _words(category: str) -> str:
    """What an item of ``category`` reports, in words a sentence can carry."""
    try:
        known = Category(category)
    except ValueError:
        known = Category.other
    return CATEGORY_WORDS.get(known) or wording.ROUTINE_WORDS.get(known.value, "")


def _named(change: RelevantChange) -> NamedParagraph:
    paragraph = change.paragraph if change.paragraph is not None else change.pair.after  # type: ignore[union-attr]
    return NamedParagraph(
        kind=change.kind,
        item=change.item,
        text=paragraph.text,
        link=paragraph.link,
        matched_terms=list(change.matched_terms),
    )


def _periodic(
    claims: Sequence[Claim], filing: WatchedFiling, comparison: FilingChanges | None
) -> list[ClaimTriage]:
    """Every claim bears; each names the changed paragraphs that share its words."""
    ranked = relevant_changes(claims, [comparison]) if comparison is not None else None
    out: list[ClaimTriage] = []
    for position, claim in enumerate(claims):
        reasons = [wording.REASON_PERIODIC.format(form=filing.form)]
        paragraphs: list[NamedParagraph] = []
        if ranked is not None:
            paragraphs = [
                _named(change)
                for change in ranked[position].changes[: wording.PARAGRAPHS_PER_CLAIM]
            ]
            if paragraphs:
                count = len(paragraphs)
                reasons.append(
                    wording.REASON_PARAGRAPHS.format(
                        count=count,
                        plural="" if count == 1 else "s",
                        verb="s" if count == 1 else "",
                    )
                )
            else:
                reasons.append(wording.REASON_NO_PARAGRAPHS)
        out.append(
            ClaimTriage(
                claim_id=claim.id,
                claim=claim.text,
                categories=list(claim.categories),
                bears=True,
                reasons=reasons,
                paragraphs=paragraphs,
            )
        )
    return out


def _current(
    claims: Sequence[Claim], filing: WatchedFiling
) -> tuple[list[ClaimTriage], list[TriageRule], str]:
    """The claims an 8-K bears on, the rules that decided it and the summary when none."""
    numbers = [item.number for item in filing.items]
    if not numbers:
        return (
            [
                ClaimTriage(
                    claim_id=claim.id,
                    claim=claim.text,
                    categories=list(claim.categories),
                    bears=True,
                    reasons=[wording.REASON_NO_ITEMS],
                )
                for claim in claims
            ],
            [TriageRule.no_items],
            "",
        )
    results = wording.RESULTS_ITEM in numbers
    matched_any = False
    out: list[ClaimTriage] = []
    for claim in claims:
        wanted = set(claim.categories)
        reasons: list[str] = []
        if results:
            reasons.append(wording.REASON_RESULTS)
        for category in dict.fromkeys(item.category for item in filing.items):
            if category not in wanted:
                continue
            on_subject = [item.number for item in filing.items if item.category == category]
            matched_any = True
            reasons.append(
                wording.REASON_CATEGORY.format(
                    items=_item_label(on_subject),
                    words=_words(category),
                    categories=", ".join(claim.categories),
                )
            )
        out.append(
            ClaimTriage(
                claim_id=claim.id,
                claim=claim.text,
                categories=list(claim.categories),
                bears=bool(reasons),
                reasons=reasons,
            )
        )
    rules: list[TriageRule] = []
    if results:
        rules.append(TriageRule.results_announced)
    if matched_any:
        rules.append(TriageRule.event_category)
    if rules:
        return out, rules, ""
    substantive = [item for item in filing.items if Category(item.category) in CATEGORY_WORDS]
    if substantive:
        words = "; ".join(dict.fromkeys(_words(item.category) for item in substantive))
        summary = wording.SUMMARY_NO_MATCH.format(
            items=_item_label([item.number for item in substantive]), words=words
        )
        return out, [TriageRule.no_match], summary
    words = "; ".join(dict.fromkeys(_words(item.category) for item in filing.items))
    summary = wording.SUMMARY_ROUTINE.format(items=_item_label(numbers), words=words)
    return out, [TriageRule.routine], summary


def triage(
    claims: Sequence[Claim],
    filing: WatchedFiling,
    comparison: FilingChanges | None = None,
    *,
    notes: Sequence[str] = (),
    extra_rules: Sequence[ExtraRule] = (),
) -> Triage:
    """Decide, by rule, whether ``filing`` bears on any of ``claims``, claim by claim.

    ``comparison`` is the new 10-K or 10-Q compared with the filing of its form before
    it, listing every changed paragraph; None when it could not be made, and then
    ``notes`` say why (each becomes "The changed paragraphs could not be named: ...").
    ``extra_rules`` is the extension point described at the top of this module.
    """
    kept_notes = [wording.NOTE_NO_COMPARISON.format(reason=note) for note in notes]
    summary = ""
    if filing.form in wording.PERIODIC_FORMS:
        claim_results = _periodic(claims, filing, comparison)
        rules = [TriageRule.periodic_report]
    elif filing.form in CURRENT_FORMS:
        claim_results, rules, summary = _current(claims, filing)
    else:
        raise ValueError(f"the watch triages 10-K, 10-Q and 8-K filings, not {filing.form!r}")

    # EXTENSION POINT (version 14): further rules add a reason to a claim and make it bear.
    by_id = {result.claim_id: result for result in claim_results}
    extended = False
    for rule in extra_rules:
        for claim_id, reason in rule(claims, filing):
            target = by_id.get(claim_id)
            if target is None:
                continue
            target.reasons.append(reason)
            target.bears = True
            extended = True
    if extended:
        rules.append(TriageRule.extension)

    bearing = sum(1 for result in claim_results if result.bears)
    if filing.form in wording.PERIODIC_FORMS:
        summary = wording.SUMMARY_PERIODIC.format(form=filing.form, claims=len(claims))
    elif bearing:
        summary = wording.SUMMARY_BEARS.format(count=bearing, claims=len(claims))
    return Triage(
        bears=bearing > 0,
        rules=rules,
        summary=summary,
        claims=claim_results,
        notes=kept_notes,
    )
