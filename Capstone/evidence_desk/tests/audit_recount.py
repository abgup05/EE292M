"""A recorded run's argued analysis, audited again by today's rule; nothing is written.

The audit of the argument (:mod:`app.core.analysis_audit`) changed in version 14.3: a
claim's own words and a corollary's model-written sentence no longer carry a number, and
a threshold a sentence restates is listed instead of passing unseen or failing. A record
of a real run keeps the audit of its day and is never edited. ``make audit-recount``
reads such records (by default the page's two live samples) and prints what today's rule
would say of each sentence the model wrote: how many are verified then and now, each
sentence whose mark would change, and each that would be listed as restating a threshold.
"""

from __future__ import annotations

import argparse
from collections.abc import Iterator
from pathlib import Path

from app.core.analysis_audit import AuditCounts, audit_sentence, citables
from app.core.analysis_models import ArgSentence
from app.core.models import Run

DEFAULT = ("src/web/sample-run-live.json", "src/web/sample-run-costco.json")


def written(run: Run) -> Iterator[tuple[str, ArgSentence]]:
    """Every sentence of the run's argued analysis, with where it stands."""
    for claim in run.claims:
        argument = claim.analysis.argument if claim.analysis else None
        if argument is None:
            continue
        for section in ("assessment", "case_for", "case_against", "decides", "would_change"):
            for number, sentence in enumerate(getattr(argument, section), start=1):
                yield f"{claim.id} {section} {number}", sentence
    thesis = run.analysis.thesis if run.analysis else None
    if thesis is None:
        return
    for section in ("weakest_why", "strongest_for", "strongest_against", "bottom_line"):
        for number, sentence in enumerate(getattr(thesis, section), start=1):
            yield f"thesis {section} {number}", sentence
    for scenario in thesis.scenarios:
        for number, sentence in enumerate(scenario.conditions, start=1):
            yield f"thesis scenario {scenario.name!r} {number}", sentence


def recount(run: Run) -> tuple[AuditCounts, int, list[str]]:
    """Today's counts for ``run``, how many sentences it recorded as verified, and a line
    for each sentence whose mark would change or that would be listed with a threshold."""
    analysis = run.analysis
    analytics = analysis.analytics if analysis else []
    per_claim = [claim.analysis for claim in run.claims if claim.analysis]
    corollaries = [corollary for mine in per_claim for corollary in mine.corollaries]
    odds = [mine.persistence for mine in per_claim if mine.persistence is not None]
    known = citables(run, analytics, corollaries, odds)
    withheld = {finding.id for finding in run.unsupported_findings}
    counts = AuditCounts()
    before = 0
    lines: list[str] = []
    for where, recorded in written(run):
        before += recorded.verified
        blank = recorded.model_copy(update={"verified": False, "problems": [], "thresholds": []})
        today = audit_sentence(blank, known, withheld, counts)
        restated = "; ".join(item.note for item in today.thresholds)
        if today.verified != recorded.verified:
            was = "verified" if recorded.verified else "marked: " + "; ".join(recorded.problems)
            now = "verified" if today.verified else "marked: " + "; ".join(today.problems)
            lines.append(f"  {where}: was {was}; now {now}{'; ' + restated if restated else ''}")
            lines.append(f"      {recorded.text!r} citing {', '.join(recorded.cites)}")
        elif restated:
            lines.append(f"  {where}: verified then and now; now {restated}")
    return counts, before, lines


def main(argv: list[str] | None = None) -> int:
    """Print the recount of each record named (default: the two live samples)."""
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("records", nargs="*", type=Path, default=[Path(p) for p in DEFAULT])
    for path in parser.parse_args(argv).records:
        run = Run.model_validate_json(path.read_text(encoding="utf-8"))
        counts, before, lines = recount(run)
        print(
            f"{path}: {counts.written} sentences; verified as recorded {before}, by today's "
            f"rule {counts.verified} ({counts.restating} of them restating a threshold); "
            f"marked as recorded {counts.written - before}, today {counts.unverified}"
        )
        print("\n".join(lines) if lines else "  no sentence's mark would change")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
