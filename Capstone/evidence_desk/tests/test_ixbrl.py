"""Reading a filing's inline XBRL: contexts, units and numeric facts (no network)."""

from __future__ import annotations

from datetime import date

import pytest

from app.sources.ixbrl import read_tagged_facts
from tests.fakes import recorded_html

UNITS = (
    '<xbrli:unit id="usd"><xbrli:measure>iso4217:USD</xbrli:measure></xbrli:unit>'
    '<xbrli:unit id="number"><xbrli:measure>xbrli:pure</xbrli:measure></xbrli:unit>'
    '<xbrli:unit id="usdPerShare"><xbrli:divide><xbrli:unitNumerator>'
    "<xbrli:measure>iso4217:USD</xbrli:measure></xbrli:unitNumerator><xbrli:unitDenominator>"
    "<xbrli:measure>xbrli:shares</xbrli:measure></xbrli:unitDenominator></xbrli:divide>"
    "</xbrli:unit>"
)


def context(
    context_id: str,
    *,
    end: str,
    start: str | None = None,
    dims: dict[str, str] | None = None,
    typed: str | None = None,
) -> str:
    """One ``xbrli:context``: a duration when ``start`` is given, else an instant."""
    members = "".join(
        f'<xbrldi:explicitMember dimension="{axis}">{member}</xbrldi:explicitMember>'
        for axis, member in (dims or {}).items()
    )
    if typed:
        members += f'<xbrldi:typedMember dimension="{typed}"><x:id>7</x:id></xbrldi:typedMember>'
    segment = f"<xbrli:segment>{members}</xbrli:segment>" if members else ""
    period = (
        f"<xbrli:startDate>{start}</xbrli:startDate><xbrli:endDate>{end}</xbrli:endDate>"
        if start
        else f"<xbrli:instant>{end}</xbrli:instant>"
    )
    return (
        f'<xbrli:context id="{context_id}"><xbrli:entity><xbrli:identifier '
        f'scheme="http://www.sec.gov/CIK">0000000001</xbrli:identifier>{segment}'
        f"</xbrli:entity><xbrli:period>{period}</xbrli:period></xbrli:context>"
    )


def fact(
    name: str,
    context_ref: str,
    text: str,
    *,
    unit: str = "usd",
    scale: str | None = "6",
    decimals: str = "-6",
    fmt: str | None = "ixt:num-dot-decimal",
    sign: str | None = None,
) -> str:
    """One ``ix:nonFraction`` fact as a filing writes it inside a table cell."""
    attrs = f'unitRef="{unit}" contextRef="{context_ref}" decimals="{decimals}" name="{name}"'
    if fmt:
        attrs += f' format="{fmt}"'
    if scale is not None:
        attrs += f' scale="{scale}"'
    if sign:
        attrs += f' sign="{sign}"'
    return f"<td><ix:nonFraction {attrs}>{text}</ix:nonFraction></td>"


def document(contexts: str, *facts: str) -> str:
    """A minimal inline-XBRL document: a hidden header with the contexts, then the facts."""
    return (
        '<html xmlns:ix="http://www.xbrl.org/2013/inlineXBRL"><body>'
        '<div style="display:none"><ix:header><ix:resources>'
        f"{contexts}{UNITS}</ix:resources></ix:header></div>"
        f"<table><tr>{''.join(facts)}</tr></table></body></html>"
    )


FY = context("c-1", start="2025-01-27", end="2026-01-25")


def only_value(html: str) -> float:
    result = read_tagged_facts(html)
    assert result.unparsed == [], result.unparsed
    assert len(result.facts) == 1
    return result.facts[0].value


def test_scale_multiplies_the_number_as_shown() -> None:
    assert only_value(document(FY, fact("us-gaap:Revenues", "c-1", "215,938"))) == 215_938e6
    assert only_value(document(FY, fact("us-gaap:Revenues", "c-1", "1.6", scale="9"))) == 1.6e9
    assert only_value(document(FY, fact("us-gaap:Revenues", "c-1", "4.90", scale="0"))) == 4.9


def test_a_negative_scale_turns_a_percentage_into_a_fraction() -> None:
    percent = fact(
        "us-gaap:ConcentrationRiskPercentage1", "c-1", "22", unit="number", scale="-2", fmt=None
    )
    assert only_value(document(FY, percent)) == pytest.approx(0.22)


def test_a_missing_scale_means_none() -> None:
    assert only_value(document(FY, fact("us-gaap:Revenues", "c-1", "259", scale=None))) == 259


def test_the_sign_attribute_makes_the_value_negative() -> None:
    html = document(FY, fact("us-gaap:IncomeTaxExpenseBenefit", "c-1", "1,234", sign="-"))
    result = read_tagged_facts(html)
    assert result.facts[0].value == -1_234e6
    assert result.facts[0].shown == "1,234"
    assert result.facts[0].negative is True


@pytest.mark.parametrize("fmt", ["ixt:fixed-zero", "ixt:zerodash"])
@pytest.mark.parametrize("dash", ["—", "-", "–", "&#8212;"])
def test_the_zero_dash_forms_are_zero(fmt: str, dash: str) -> None:
    html = document(FY, fact("us-gaap:Revenues", "c-1", dash, fmt=fmt))
    result = read_tagged_facts(html)
    assert result.unparsed == []
    assert result.facts[0].value == 0.0
    assert result.facts[0].shown in ("—", "-", "–")


@pytest.mark.parametrize("fmt", ["ixt:num-comma-decimal", "ixt:numcommadecimal"])
def test_comma_decimal_numbers(fmt: str) -> None:
    html = document(FY, fact("us-gaap:Revenues", "c-1", "1.234,5", fmt=fmt, scale="3"))
    assert only_value(html) == 1_234_500


@pytest.mark.parametrize("fmt", ["ixt:num-dot-decimal", "ixt:numdotdecimal"])
def test_dot_decimal_numbers_with_spaces_and_entities(fmt: str) -> None:
    html = document(FY, fact("us-gaap:Revenues", "c-1", "<span>1,234</span>&#160;.5", fmt=fmt))
    result = read_tagged_facts(html)
    assert result.facts[0].value == 1_234.5e6
    assert result.facts[0].shown == "1,234 .5"


def test_text_that_is_not_a_number_is_counted_not_guessed() -> None:
    html = document(
        FY,
        fact("us-gaap:Revenues", "c-1", "n/a"),
        fact("us-gaap:Revenues", "c-1", "1,234", fmt=None),  # no format: commas not allowed
        fact("us-gaap:Revenues", "c-1", "3", fmt="ixt-sec:duryear"),
        fact("us-gaap:Revenues", "c-1", "12", scale="six"),
        fact("us-gaap:Revenues", "c-9", "12"),
        fact("us-gaap:Revenues", "c-1", "7"),
    )
    result = read_tagged_facts(html)
    assert [f.value for f in result.facts] == [7e6]
    reasons = [u.reason for u in result.unparsed]
    assert len(reasons) == 5
    assert "not a number" in reasons[0]
    assert "not a number" in reasons[1]
    assert "ixt-sec:duryear" in reasons[2]
    assert "scale" in reasons[3]
    assert "c-9" in reasons[4]
    assert result.facts_read == 6


def test_a_nil_fact_is_counted_as_unread() -> None:
    nil = '<ix:nonFraction unitRef="usd" contextRef="c-1" name="us-gaap:Revenues" xsi:nil="true"/>'
    result = read_tagged_facts(document(FY, nil))
    assert result.facts == []
    assert [u.reason for u in result.unparsed] == ["nil: the fact has no value"]


def test_a_nested_fact_is_read_once_each() -> None:
    attrs = 'unitRef="usd" contextRef="c-1"'
    inner = f'<ix:nonFraction {attrs} name="a:Inner" scale="3">5</ix:nonFraction>'
    outer = f'<ix:nonFraction {attrs} name="a:Outer" scale="6">{inner}</ix:nonFraction>'
    result = read_tagged_facts(document(FY, outer))
    assert {(f.concept, f.value) for f in result.facts} == {("a:Inner", 5e3), ("a:Outer", 5e6)}


def test_contexts_carry_their_dates_and_explicit_members() -> None:
    contexts = (
        FY
        + context("c-2", end="2026-01-25")
        + context(
            "c-3",
            start="2025-01-27",
            end="2026-01-25",
            dims={
                "srt:ProductOrServiceAxis": "nvda:DataCenterMember",
                "us-gaap:StatementBusinessSegmentsAxis": "nvda:GraphicsSegmentMember",
            },
        )
        + context("c-4", end="2026-01-25", typed="us-gaap:LoanAxis")
    )
    result = read_tagged_facts(document(contexts, fact("us-gaap:Revenues", "c-3", "1")))
    first, instant, dimensional, typed = (result.contexts[f"c-{n}"] for n in (1, 2, 3, 4))
    assert (first.start, first.end, first.dimensions) == (date(2025, 1, 27), date(2026, 1, 25), {})
    assert (instant.start, instant.end) == (None, date(2026, 1, 25))
    assert dimensional.dimensions == {
        "srt:ProductOrServiceAxis": "nvda:DataCenterMember",
        "us-gaap:StatementBusinessSegmentsAxis": "nvda:GraphicsSegmentMember",
    }
    assert typed.typed_axes == ("us-gaap:LoanAxis",)


def test_units_are_named_by_their_measures() -> None:
    result = read_tagged_facts(document(FY))
    assert result.units == {"usd": "USD", "number": "pure", "usdPerShare": "USD/shares"}


def test_a_document_without_inline_xbrl_gives_an_empty_result_with_a_reason() -> None:
    result = read_tagged_facts("<html><body><p>Annual report</p></body></html>")
    assert result.facts == [] and result.unparsed == [] and result.contexts == {}
    assert result.reason is not None and "no inline XBRL" in result.reason


def test_the_recorded_nvidia_annual_report() -> None:
    html = recorded_html("nvda-10k-20260125.htm.gz")
    result = read_tagged_facts(html)
    assert result.reason is None
    assert len(result.contexts) == html.count("<xbrli:context ")
    assert result.facts_read == html.count("<ix:nonFraction ")
    # Durations written as words or years are the only formats not read.
    assert {u.format for u in result.unparsed} <= {
        "ixt-sec:durwordsen",
        "ixt-sec:duryear",
        "ixt-sec:durmonth",
        "ixt-sec:durday",
    }
    revenue = {
        f.value for f in result.facts if f.concept == "us-gaap:Revenues" and f.context_ref == "c-1"
    }
    assert revenue == {215_938e6}
    assert result.contexts["c-1"].end == date(2026, 1, 25)


# Filing text is untrusted: a malformed document must not make the scan quadratic.


def _scan_seconds(openings: int) -> float:
    """Best of three timings of reading a document with ``openings`` unclosed context tags."""
    import time

    filler = "<p>" + "x" * 200 + "</p>"
    text = "".join(f'<xbrli:context id="c{n}">{filler}' for n in range(openings))
    best = float("inf")
    for _ in range(3):
        started = time.perf_counter()
        result = read_tagged_facts(text)
        best = min(best, time.perf_counter() - started)
        assert result.facts == []
    return best


def test_unclosed_context_tags_do_not_make_the_scan_quadratic() -> None:
    # Eight times the unclosed openings costs about eight times as much when the scan is
    # linear and sixty-four times when each opening searches to the end of the document.
    small, large = _scan_seconds(500), _scan_seconds(4000)
    assert large < 20 * max(small, 1e-4), f"8x the openings took {large / small:.1f}x as long"
