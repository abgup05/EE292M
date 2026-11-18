"""The measure catalogue: every company-level measure a claim test can name, and how it is computed.

Pure data. A claim test (:mod:`app.core.claimtest`) names one of these measures by its key;
the evaluator (:mod:`app.core.claim_eval`) computes it from one company's dated facts
(:class:`~app.core.facts.FactBook`); the model readers' prompt and schema
(:mod:`app.engines.claim_reader`, :mod:`app.core.claim_reading`) are written from it, so a
reader can name exactly what the evaluator can compute.

A measure is one of:

- ``metrics``: one of the reported-figures panel's own measures (:mod:`app.core.metrics`),
  computed by that module's functions, exactly as before the catalogue;
- ``group``: one concept group of :data:`app.core.facts.BOOK_GROUPS`, read as reported,
  with ``fallback`` (a sum of other measures) where the group has no value for a period;
- ``sum``: other measures added (``plus``) and subtracted (``minus``) for the same period;
  a part in ``optional`` counts as zero when the company does not report it for that
  period (a company with no commercial paper tags none), and the arithmetic says so;
- ``ratio``: ``plus[0]`` as a percent of ``over``, which must be positive.

The measures this catalogue adds are measures a claim test can use and nothing else: they
are not on the metrics panel, so the reported-figures report, the tripwire's figures stage
and every recording stay as they were. ``definition`` writes a derived measure's formula
out in words, as the panel writes free cash flow's; it is shown in the operand's note.

A part of the company (a segment, a product, a geography) has measures too, read from the
newest filing's tagged breakdowns (:data:`PART_MEASURES`): its revenue, that revenue's
change on a year earlier when the filing tags both years, and a segment's operating income.
They have no history: one filing tags them, and the company facts do not.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

MeasureKind = Literal["flow", "ratio", "per_share", "instant", "shares"]
Computed = Literal["metrics", "group", "sum", "ratio"]


@dataclass(frozen=True)
class Measure:
    """One measure: its key, label, kind, how a claim names it and how it is computed.

    ``names`` is a regular expression (lower case) for the words a claim names it by;
    ``also`` the further words it explains in a claim ("to shareholders" after
    "returned"). ``note`` says what a reader should know of its availability.
    """

    key: str
    label: str
    kind: MeasureKind
    computed: Computed
    names: str
    group: str = ""
    plus: tuple[str, ...] = ()
    minus: tuple[str, ...] = ()
    optional: tuple[str, ...] = ()
    over: str = ""
    fallback: tuple[str, ...] = ()
    definition: str = ""
    also: str = ""
    note: str = ""


def _ratio_names(base: str) -> str:
    return rf"(?:{base}) (?:as a (?:share|percent(?:age)?) of (?:revenues?|sales)|intensity)"


SGA_NAMES = (
    r"sg&a(?: expenses?)?|selling, general(?:,)? and administrative(?: expenses?)?|"
    r"selling, general & administrative(?: expenses?)?"
)
SM_NAMES = r"sales and marketing(?: expenses?| spending| spend)?|s&m(?: expenses?)?"
OPEX_TOTAL_NAMES = r"total operating expenses|total opex"
CAPEX_NAMES = r"capital expenditures?|capex|capital spending"
SBC_NAMES = r"stock-based compensation|share-based compensation|stock compensation|sbc"

# The measures this catalogue adds, in the order the claim compiler tries their names:
# longer names first, so that "cash and marketable securities" is not read as "cash".
ADDED: tuple[Measure, ...] = (
    Measure(
        "sga_ratio",
        "SG&A as a share of revenue",
        "ratio",
        "ratio",
        _ratio_names(SGA_NAMES),
        plus=("sga",),
        over="revenue",
        definition="SG&A as a share of revenue is SG&A ÷ revenue.",
    ),
    Measure(
        "sales_marketing_ratio",
        "Sales and marketing as a share of revenue",
        "ratio",
        "ratio",
        _ratio_names(SM_NAMES),
        plus=("sales_marketing",),
        over="revenue",
        definition="Sales and marketing as a share of revenue is that expense ÷ revenue.",
    ),
    Measure(
        "opex_ratio",
        "Operating expenses as a share of revenue",
        "ratio",
        "ratio",
        _ratio_names(rf"{OPEX_TOTAL_NAMES}|operating expenses|opex"),
        plus=("total_operating_expenses",),
        over="revenue",
        definition=(
            "Operating expenses as a share of revenue is total operating expenses (as "
            "reported, OperatingExpenses; else gross profit less operating income) ÷ revenue."
        ),
    ),
    Measure(
        "capex_ratio",
        "Capital expenditure as a share of revenue",
        "ratio",
        "ratio",
        _ratio_names(CAPEX_NAMES),
        plus=("capex",),
        over="revenue",
        definition="Capital expenditure as a share of revenue is capex ÷ revenue.",
    ),
    Measure(
        "sbc_ratio",
        "Stock-based compensation as a share of revenue",
        "ratio",
        "ratio",
        _ratio_names(SBC_NAMES),
        plus=("sbc",),
        over="revenue",
        definition="Stock-based compensation as a share of revenue is that expense ÷ revenue.",
    ),
    Measure(
        "effective_tax_rate",
        "Effective tax rate",
        "ratio",
        "ratio",
        r"effective (?:income )?tax rate|tax rate",
        plus=("income_tax",),
        over="pretax_income",
        definition=(
            "The effective tax rate here is income tax expense ÷ income before income taxes."
        ),
    ),
    Measure(
        "cash_and_securities",
        "Cash, cash equivalents and marketable securities",
        "instant",
        "sum",
        r"cash(?:,? (?:cash )?equivalents)?(?: and cash equivalents)?,? (?:and|plus) "
        r"(?:current |short-term )?(?:marketable securities|short-term investments|investments)",
        plus=("cash", "marketable_securities"),
        optional=("marketable_securities",),
        definition=(
            "Cash and marketable securities here is cash and cash equivalents + current "
            "marketable securities (short-term investments); non-current securities are left "
            "out."
        ),
    ),
    Measure(
        "net_cash",
        "Net cash",
        "instant",
        "sum",
        r"net cash(?: position)?",
        plus=("cash_and_securities",),
        minus=("total_debt",),
        definition=("Net cash here is cash and marketable securities − total debt (see each)."),
    ),
    Measure(
        "net_debt",
        "Net debt",
        "instant",
        "sum",
        r"net debt",
        plus=("total_debt",),
        minus=("cash_and_securities",),
        definition="Net debt here is total debt − cash and marketable securities (see each).",
    ),
    Measure(
        "long_term_debt",
        "Long-term debt",
        "instant",
        "group",
        r"long-term debt|long term debt",
        group="long_term_debt",
        note="The non-current part only; total debt adds the current part and commercial paper.",
    ),
    Measure(
        "commercial_paper",
        "Commercial paper",
        "instant",
        "group",
        r"commercial paper(?: outstanding)?",
        group="commercial_paper",
        note="Tagged only by a company that has issued commercial paper.",
    ),
    Measure(
        "total_debt",
        "Total debt",
        "instant",
        "sum",
        r"total debt|total borrowings|debt|borrowings",
        plus=("long_term_debt", "current_debt", "commercial_paper"),
        optional=("current_debt", "commercial_paper"),
        definition=(
            "Total debt here is long-term debt (non-current) + its current portion + "
            "commercial paper; a part the company does not report on that balance sheet counts "
            "as zero. Leases are left out."
        ),
    ),
    Measure(
        "marketable_securities",
        "Marketable securities (current)",
        "instant",
        "group",
        r"(?:current )?marketable securities|short-term investments",
        group="marketable_securities",
        note="Current marketable securities only (short-term investments).",
    ),
    Measure(
        "shareholder_returns",
        "Buybacks and dividends",
        "flow",
        "sum",
        r"shareholder returns|capital returned(?: to shareholders)?|"
        r"(?:buybacks|share repurchases|repurchases) and dividends|"
        r"dividends and (?:buybacks|share repurchases|repurchases)|"
        r"returned\b(?=.*\bto shareholders\b)",
        plus=("share_repurchases", "dividends_paid"),
        optional=("dividends_paid",),
        definition=(
            "Returned to shareholders here is share repurchases + dividends paid (cash flow "
            "statement); a company that pays no dividend counts zero for it."
        ),
        also=(
            r"\bto shareholders\b|"
            r"\bthrough\b(?= (?:buybacks|share repurchases|repurchases|dividends))"
        ),
    ),
    Measure(
        "share_repurchases",
        "Share repurchases",
        "flow",
        "group",
        r"(?:share |stock )?(?:buybacks?|repurchases?)(?: of (?:common )?stock)?|"
        r"(?:common )?stock repurchased|repurchased|bought back|buys back",
        group="share_repurchases",
        also=r"\b(?:spent|bought back|repurchased)\b|"
        r"\bof (?:its |our |the company's )?(?:common )?(?:stock|shares)\b",
        note="Cash paid for repurchases of common stock, from the cash flow statement.",
    ),
    Measure(
        "dividends_paid",
        "Dividends paid",
        "flow",
        "group",
        r"dividends?(?: paid| payments?)?",
        group="dividends_paid",
        also=r"\bpaid\b",
        note="Cash dividends paid, from the cash flow statement.",
    ),
    Measure(
        "diluted_shares",
        "Diluted share count",
        "shares",
        "group",
        r"diluted (?:share count|shares(?: outstanding)?|weighted[- ]average shares)|"
        r"share count",
        group="diluted_shares",
        note=(
            "The weighted-average diluted share count of the period; it is never differenced, "
            "so a fourth quarter needs its own fact, and it has no four-quarter total."
        ),
    ),
    Measure(
        "total_operating_expenses",
        "Total operating expenses",
        "flow",
        "group",
        OPEX_TOTAL_NAMES,
        group="reported_operating_expenses",
        fallback=("operating_expenses",),
        definition=(
            "Total operating expenses as reported (OperatingExpenses); where a company does "
            "not tag them, gross profit less operating income."
        ),
    ),
    Measure(
        "sga",
        "SG&A",
        "flow",
        "group",
        SGA_NAMES,
        group="reported_sga",
        fallback=("sales_marketing", "general_admin"),
        definition=(
            "SG&A as reported (SellingGeneralAndAdministrativeExpense); where a company tags "
            "only its parts, sales and marketing + general and administrative."
        ),
    ),
    Measure(
        "sales_marketing",
        "Sales and marketing",
        "flow",
        "group",
        SM_NAMES,
        group="sales_marketing",
        note="Tagged only by a company that reports sales and marketing on its own line.",
    ),
    Measure(
        "general_admin",
        "General and administrative",
        "flow",
        "group",
        r"general and administrative(?: expenses?)?|g&a(?: expenses?)?",
        group="general_admin",
        note="Tagged only by a company that reports G&A on its own line.",
    ),
    Measure(
        "sbc",
        "Stock-based compensation",
        "flow",
        "group",
        SBC_NAMES + r"(?: expenses?)?",
        group="sbc",
    ),
    Measure(
        "pretax_income",
        "Income before income taxes",
        "flow",
        "group",
        r"income before (?:income )?taxes|pre-?tax income|pretax profits?|"
        r"earnings before (?:income )?taxes",
        group="pretax_income",
    ),
    Measure(
        "income_tax",
        "Income tax expense",
        "flow",
        "group",
        r"income tax(?:es)?(?: expenses?| provision)?|tax (?:expense|provision)s?|"
        r"provision for income taxes|taxes",
        group="income_tax",
    ),
    Measure(
        "interest_expense",
        "Interest expense",
        "flow",
        "group",
        r"interest expenses?",
        group="interest_expense",
    ),
    Measure(
        "interest_income",
        "Interest income",
        "flow",
        "group",
        r"interest income",
        group="interest_income",
    ),
    Measure(
        "other_income",
        "Other income and expense",
        "flow",
        "group",
        r"other income(?: and expenses?)?(?:,? net| \(expense\))?|non-?operating income",
        group="other_income",
    ),
    Measure(
        "d_and_a",
        "Depreciation and amortization",
        "flow",
        "group",
        r"depreciation(?: and amortization)?|d&a",
        group="d_and_a",
    ),
    Measure(
        "deferred_revenue",
        "Deferred revenue",
        "instant",
        "sum",
        r"deferred revenues?|unearned revenues?|contract liabilities",
        plus=("deferred_revenue_current", "deferred_revenue_noncurrent"),
        optional=("deferred_revenue_noncurrent",),
        definition=(
            "Deferred revenue here is the current + non-current contract liabilities (deferred "
            "or unearned revenue); a non-current part not reported counts as zero."
        ),
    ),
    Measure(
        "deferred_revenue_current",
        "Deferred revenue (current)",
        "instant",
        "group",
        r"current deferred revenues?|current unearned revenues?",
        group="deferred_revenue_current",
    ),
    Measure(
        "deferred_revenue_noncurrent",
        "Deferred revenue (non-current)",
        "instant",
        "group",
        r"non-?current deferred revenues?|long-term deferred revenues?|"
        r"non-?current unearned revenues?",
        group="deferred_revenue_noncurrent",
    ),
    Measure(
        "current_debt",
        "Current portion of debt",
        "instant",
        "group",
        r"current (?:portion of )?(?:long-term )?debt|short-term debt",
        group="current_debt",
    ),
    Measure(
        "total_assets",
        "Total assets",
        "instant",
        "group",
        r"total assets",
        group="total_assets",
    ),
    Measure(
        "total_liabilities",
        "Total liabilities",
        "instant",
        "group",
        r"total liabilities|liabilities",
        group="total_liabilities",
    ),
    Measure(
        "equity",
        "Shareholders' equity",
        "instant",
        "group",
        r"(?:total )?(?:shareholders'?|stockholders'?) equity|book value|total equity",
        group="equity",
    ),
    Measure("goodwill", "Goodwill", "instant", "group", r"goodwill", group="goodwill"),
    Measure(
        "ppe",
        "Property and equipment, net",
        "instant",
        "group",
        r"property(?:,)? (?:plant )?and equipment|pp&e",
        group="ppe",
    ),
    Measure(
        "accounts_payable",
        "Accounts payable",
        "instant",
        "group",
        r"accounts payables?|payables",
        group="accounts_payable",
    ),
    Measure(
        "cost_of_revenue",
        "Cost of revenue",
        "flow",
        "group",
        r"cost of (?:revenues?|sales|goods sold)|cogs",
        group="cost_of_revenue",
    ),
)

# The panel's own measures, computed by app.core.metrics as before; their names are the
# claim compiler's, unchanged, and are tried after the added ones.
PANEL: tuple[Measure, ...] = (
    Measure(
        "fcf_margin",
        "Free cash flow margin",
        "ratio",
        "metrics",
        r"free cash flow margins?|fcf margins?",
    ),
    Measure(
        "rnd_ratio",
        "R&D as a share of revenue",
        "ratio",
        "metrics",
        r"(?:r&d|research and development|research)(?: spending| expenses?)?"
        r" (?:as a (?:share|percent(?:age)?) of (?:revenues?|sales)|intensity)",
    ),
    Measure("gross_margin", "Gross margin", "ratio", "metrics", r"gross margins?"),
    Measure("operating_margin", "Operating margin", "ratio", "metrics", r"operating margins?"),
    Measure("net_margin", "Net margin", "ratio", "metrics", r"net (?:profit )?margins?"),
    Measure("free_cash_flow", "Free cash flow", "flow", "metrics", r"free cash flows?|\bfcf"),
    Measure(
        "operating_cash_flow",
        "Operating cash flow",
        "flow",
        "metrics",
        r"operating cash flows?|cash flows? from operations|cash from operations",
    ),
    Measure("capex", "Capital expenditure", "flow", "metrics", CAPEX_NAMES),
    Measure(
        "cash",
        "Cash and cash equivalents",
        "instant",
        "metrics",
        r"cash and cash equivalents|cash on hand|cash balances?|cash",
    ),
    Measure("inventory", "Inventory", "instant", "metrics", r"inventor(?:y|ies)"),
    Measure(
        "receivables",
        "Accounts receivable",
        "instant",
        "metrics",
        r"accounts receivables?|receivables",
    ),
    Measure(
        "eps_diluted",
        "Diluted EPS",
        "per_share",
        "metrics",
        r"diluted (?:eps|earnings per share)|eps|earnings per share",
    ),
    Measure("gross_profit", "Gross profit", "flow", "metrics", r"gross profits?"),
    Measure(
        "operating_income",
        "Operating income",
        "flow",
        "metrics",
        r"operating (?:income|profits?)",
    ),
    Measure(
        "operating_expenses",
        "Operating expenses",
        "flow",
        "metrics",
        r"operating expenses|opex",
    ),
    Measure(
        "net_income",
        "Net income",
        "flow",
        "metrics",
        r"net (?:income|profits?|earnings)|earnings|profits",
    ),
    Measure(
        "rnd",
        "Research and development",
        "flow",
        "metrics",
        r"(?:r&d|research and development|research)(?: spending| expenses?)?",
    ),
    Measure("revenue", "Revenue", "flow", "metrics", r"(?:net )?(?:revenues?|sales)"),
)

# Every measure, in the order the claim compiler tries their names.
CATALOGUE: dict[str, Measure] = {measure.key: measure for measure in (*ADDED, *PANEL)}
# A measure "as a share of revenue" is its ratio.
RATIO_OF: dict[str, str] = {
    "gross_profit": "gross_margin",
    "operating_income": "operating_margin",
    "net_income": "net_margin",
    "rnd": "rnd_ratio",
    "free_cash_flow": "fcf_margin",
    "sga": "sga_ratio",
    "sales_marketing": "sales_marketing_ratio",
    "total_operating_expenses": "opex_ratio",
    "operating_expenses": "opex_ratio",
    "capex": "capex_ratio",
    "sbc": "sbc_ratio",
}

# A part of the company: its measures, read from the newest filing's tagged breakdowns.
PART_AXES: tuple[str, ...] = ("segment", "geography")
PART_MEASURES: dict[str, str] = {
    "revenue": "Revenue",
    "operating_income": "Operating income",
}
PART_NOTE = (
    "A part's figures come from the newest filing's tagged breakdowns: one filing, so they "
    "have no history, and a change is on a year earlier only when that filing tags both years."
)
