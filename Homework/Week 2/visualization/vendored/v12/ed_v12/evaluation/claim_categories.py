"""Score the claim-category rule against hand-labelled claims (``make event-categories``).

``python -m app.evaluation.claim_categories [--labels eval/claim-categories.json]``
runs :func:`app.core.events.claim_categories` on every labelled claim and prints,
for each substantive category, how many claims the rule gave it, how many are
labelled with it, how many of those agree, and the precision and recall that
follow; then the claims labelled with no category that the rule left alone, and
every disagreement. Offline and deterministic: no model, no network.
"""

from __future__ import annotations

import argparse
import json
import sys
from dataclasses import dataclass, field
from pathlib import Path

from ed_v12.core.events import SUBSTANTIVE, Category, claim_categories

DEFAULT_LABELS = Path("eval/claim-categories.json")


@dataclass(frozen=True)
class Labelled:
    """One claim and the categories a careful reader gives it."""

    text: str
    categories: frozenset[str]


@dataclass
class CategoryScore:
    """One category over the labelled set: claims predicted, labelled, and both."""

    category: str
    predicted: int = 0
    labelled: int = 0
    agreed: int = 0

    @property
    def precision(self) -> float | None:
        """Agreed over predicted; None when the rule gave the category to no claim."""
        return self.agreed / self.predicted if self.predicted else None

    @property
    def recall(self) -> float | None:
        """Agreed over labelled; None when no claim is labelled with the category."""
        return self.agreed / self.labelled if self.labelled else None


@dataclass
class Score:
    """The whole set: per category, the claims labelled with none, and every disagreement."""

    claims: int
    categories: list[CategoryScore]
    none_labelled: int
    none_kept: int
    exact: int
    disagreements: list[tuple[str, list[str], list[str]]] = field(default_factory=list)


def load_labels(path: Path) -> list[Labelled]:
    """The labelled claims; a category that is not substantive is a ValueError."""
    payload = json.loads(path.read_text(encoding="utf-8"))
    allowed = {category.value for category in SUBSTANTIVE}
    labelled: list[Labelled] = []
    for entry in payload["claims"]:
        categories = frozenset(entry["categories"])
        unknown = categories - allowed
        if unknown:
            raise ValueError(f"unknown categories {sorted(unknown)} for {entry['text']!r}")
        labelled.append(Labelled(text=entry["text"], categories=categories))
    return labelled


def score(labelled: list[Labelled]) -> Score:
    """Run the rule on every claim and count agreement category by category."""
    per = {category.value: CategoryScore(category.value) for category in SUBSTANTIVE}
    result = Score(
        claims=len(labelled), categories=list(per.values()), none_labelled=0, none_kept=0, exact=0
    )
    for claim in labelled:
        predicted = {category.value for category in claim_categories(claim.text)}
        for name, tally in per.items():
            tally.predicted += name in predicted
            tally.labelled += name in claim.categories
            tally.agreed += name in predicted and name in claim.categories
        if not claim.categories:
            result.none_labelled += 1
            result.none_kept += not predicted
        if predicted == set(claim.categories):
            result.exact += 1
        else:
            result.disagreements.append((claim.text, sorted(claim.categories), sorted(predicted)))
    return result


def _ratio(value: float | None) -> str:
    return "n/a" if value is None else f"{value:.2f}"


def render(result: Score, labels: Path) -> str:
    """The score as plain text: one row per category, then the disagreements."""
    lines = [
        f"Claim categories: the rule of app.core.events on {result.claims} labelled claims "
        f"({labels.as_posix()})",
        "",
        f"{'category':<14} {'predicted':>9} {'labelled':>8} {'agreed':>6} "
        f"{'precision':>9} {'recall':>6}",
    ]
    for tally in result.categories:
        lines.append(
            f"{tally.category:<14} {tally.predicted:>9} {tally.labelled:>8} {tally.agreed:>6} "
            f"{_ratio(tally.precision):>9} {_ratio(tally.recall):>6}"
        )
    predicted = sum(t.predicted for t in result.categories)
    labelled = sum(t.labelled for t in result.categories)
    agreed = sum(t.agreed for t in result.categories)
    lines += [
        f"{'all':<14} {predicted:>9} {labelled:>8} {agreed:>6} "
        f"{_ratio(agreed / predicted if predicted else None):>9} "
        f"{_ratio(agreed / labelled if labelled else None):>6}",
        "",
        f"Claims labelled with no category that the rule gave none: "
        f"{result.none_kept} of {result.none_labelled}.",
        f"Claims whose categories the rule gave exactly: {result.exact} of {result.claims}.",
        "",
        f"Disagreements ({len(result.disagreements)}): labelled -> rule",
    ]
    for text, wanted, got in result.disagreements:
        lines.append(f"  {text}  {wanted or '[]'} -> {got or '[]'}")
    return "\n".join(lines) + "\n"


def main(argv: list[str] | None = None) -> int:
    """Score the labelled claims and print the result."""
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--labels", type=Path, default=DEFAULT_LABELS)
    args = parser.parse_args(argv)
    print(render(score(load_labels(args.labels)), args.labels), end="")
    return 0


__all__ = ["Category", "CategoryScore", "Labelled", "Score", "load_labels", "main", "score"]

if __name__ == "__main__":
    sys.exit(main())
