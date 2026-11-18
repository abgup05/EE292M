"""The example thesis offered by the page, the command line and the demonstration."""

from __future__ import annotations

from ed_v8.core.models import ThesisRequest

EXAMPLE_THESIS = ThesisRequest(
    ticker="NVDA",
    decision="Whether to keep an overweight position in NVIDIA into the next earnings report",
    filings=3,
    claims=[
        "Data center revenue is still growing year over year.",
        "A small number of customers account for a large share of revenue.",
        "Export controls on sales to China are restricting revenue.",
        "Gross margin is expanding.",
        "The company depends on a limited number of suppliers to manufacture its products.",
    ],
)
