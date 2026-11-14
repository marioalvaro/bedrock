# ruff: noqa: E501 -- XBRL concept names and the XML fragments of the synthetic filing do not fit a line.
"""ingest/xbrl.py: the pure parser of one filing's XBRL files (docs/erd/data-coverage.md "Parser",
"Parity test"). Synthetic mini-filings pin each rule; the recorded filings prove it on real data."""

import gzip
from collections.abc import Sequence
from datetime import date
from decimal import Decimal
from functools import cache
from pathlib import Path

import pytest

from bedrock.ingest.parse import parse_companyfacts
from bedrock.ingest.xbrl import (
    XBRL_PARSER_VERSION,
    FilingLine,
    ParsedFiling,
    StatementAnchors,
    XbrlError,
    is_standard_taxonomy,
    parse_filing,
)
from bedrock.mapping.config import load_canonical_items

from .fakes import _companyfacts

FILINGS = Path(__file__).parent / "fixtures" / "edgar" / "filings"
RECORDED = [
    ("AAPL", "0000320193-24-000123"),
    ("AAPL", "0001193125-10-238044"),
    ("MSFT", "0000950170-24-087843"),
    ("MSFT", "0001193125-15-272806"),
    ("DE", "0001558370-23-019812"),
    ("COST", "0000909832-24-000017"),
]
STANDARD = {"us-gaap", "dei", "srt"}
# Companyfacts files these per-share prices of AAPL's FY2010 10-K under `USD`, although the
# instance's unit is a divide, USD per share (`iso4217_USD_per_shares`): the parser is right.
UNIT_EXCEPTIONS = {
    ("0001193125-10-238044", concept)
    for concept in (
        "ShareBasedCompensationArrangementByShareBasedPaymentAwardOptionsForfeituresInPeriodWeightedAverageExercisePrice",
        "ShareBasedCompensationArrangementByShareBasedPaymentAwardOptionsGrantsInPeriodWeightedAverageExercisePrice",
        "ShareBasedCompensationArrangementByShareBasedPaymentAwardEquityInstrumentsOtherThanOptionsForfeitedInPeriodWeightedAverageGrantDateFairValue",
        "ShareBasedCompensationArrangementByShareBasedPaymentAwardEquityInstrumentsOtherThanOptionsGrantsInPeriodWeightedAverageGrantDateFairValue",
        "ShareBasedCompensationArrangementByShareBasedPaymentAwardEquityInstrumentsOtherThanOptionsVestedInPeriodWeightedAverageGrantDateFairValue",
        "ShareBasedCompensationArrangementByShareBasedPaymentAwardOptionsExercisesInPeriodWeightedAverageExercisePrice",
    )
}


@cache
def _anchors() -> StatementAnchors:
    return StatementAnchors.from_concepts(
        {item.code: item.concepts for item in load_canonical_items()}
    )


@cache
def _recorded(ticker: str, accession: str) -> dict[str, bytes]:
    folder = FILINGS / ticker / accession
    return {p.name.removesuffix(".gz"): gzip.decompress(p.read_bytes()) for p in folder.iterdir()}


@cache
def _parsed(ticker: str, accession: str) -> ParsedFiling:
    return parse_filing(_recorded(ticker, accession), _anchors(), accession_no=accession)


# --- a synthetic filing -------------------------------------------------------------------------

NS = (
    'xmlns:xbrli="http://www.xbrl.org/2003/instance" '
    'xmlns:link="http://www.xbrl.org/2003/linkbase" '
    'xmlns:xlink="http://www.w3.org/1999/xlink" '
    'xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance" '
    'xmlns:xbrldi="http://xbrl.org/2006/xbrldi" '
    'xmlns:iso4217="http://www.xbrl.org/2003/iso4217" '
    'xmlns:us-gaap="http://fasb.org/us-gaap/2024" '
    'xmlns:dei="http://xbrl.sec.gov/dei/2024" '
    'xmlns:ACME="http://www.acme.com/20241231" '
    'xmlns:xsd="http://www.w3.org/2001/XMLSchema"'
)
GAAP = "https://xbrl.fasb.org/us-gaap/2024/elts/us-gaap-2024.xsd"
ROLE = "http://www.acme.com/role/"

CONTEXTS = """
<xbrli:context id="FY"><xbrli:entity><xbrli:identifier scheme="http://www.sec.gov/CIK">1</xbrli:identifier></xbrli:entity>
  <xbrli:period><xbrli:startDate>2024-01-01</xbrli:startDate><xbrli:endDate>2024-12-31</xbrli:endDate></xbrli:period></xbrli:context>
<xbrli:context id="END"><xbrli:entity><xbrli:identifier scheme="http://www.sec.gov/CIK">1</xbrli:identifier></xbrli:entity>
  <xbrli:period><xbrli:instant>2024-12-31</xbrli:instant></xbrli:period></xbrli:context>
<xbrli:context id="SEG"><xbrli:entity><xbrli:identifier scheme="http://www.sec.gov/CIK">1</xbrli:identifier>
  <xbrli:segment><xbrldi:explicitMember dimension="us-gaap:StatementBusinessSegmentsAxis">ACME:CloudMember</xbrldi:explicitMember></xbrli:segment></xbrli:entity>
  <xbrli:period><xbrli:startDate>2024-01-01</xbrli:startDate><xbrli:endDate>2024-12-31</xbrli:endDate></xbrli:period></xbrli:context>
<xbrli:context id="SCN"><xbrli:entity><xbrli:identifier scheme="http://www.sec.gov/CIK">1</xbrli:identifier></xbrli:entity>
  <xbrli:period><xbrli:instant>2024-12-31</xbrli:instant></xbrli:period>
  <xbrli:scenario><xbrldi:typedMember dimension="ACME:TrancheAxis"><ACME:Tranche>A</ACME:Tranche></xbrldi:typedMember></xbrli:scenario></xbrli:context>
<xbrli:unit id="USD"><xbrli:measure>iso4217:USD</xbrli:measure></xbrli:unit>
<xbrli:unit id="SH"><xbrli:measure>xbrli:shares</xbrli:measure></xbrli:unit>
<xbrli:unit id="EPS"><xbrli:divide><xbrli:unitNumerator><xbrli:measure>iso4217:USD</xbrli:measure></xbrli:unitNumerator>
  <xbrli:unitDenominator><xbrli:measure>xbrli:shares</xbrli:measure></xbrli:unitDenominator></xbrli:divide></xbrli:unit>
<xbrli:unit id="PURE"><xbrli:measure>xbrli:pure</xbrli:measure></xbrli:unit>
"""

FACTS = """
<us-gaap:Revenues contextRef="FY" unitRef="USD" decimals="0">1000</us-gaap:Revenues>
<us-gaap:Revenues contextRef="SEG" unitRef="USD" decimals="0">600</us-gaap:Revenues>
<us-gaap:Revenues contextRef="FY" unitRef="USD" decimals="0">999</us-gaap:Revenues>
<us-gaap:NetIncomeLoss contextRef="FY" unitRef="USD" decimals="0">100</us-gaap:NetIncomeLoss>
<us-gaap:EarningsPerShareBasic contextRef="FY" unitRef="EPS" decimals="2">1.25</us-gaap:EarningsPerShareBasic>
<us-gaap:EffectiveIncomeTaxRateContinuingOperations contextRef="FY" unitRef="PURE" decimals="3">0.21</us-gaap:EffectiveIncomeTaxRateContinuingOperations>
<us-gaap:Assets contextRef="END" unitRef="USD" decimals="0">5000</us-gaap:Assets>
<us-gaap:Assets contextRef="SCN" unitRef="USD" decimals="0">7</us-gaap:Assets>
<us-gaap:LiabilitiesAndStockholdersEquity contextRef="END" unitRef="USD" decimals="0">5000</us-gaap:LiabilitiesAndStockholdersEquity>
<us-gaap:Goodwill contextRef="END" unitRef="USD" xsi:nil="true"/>
<dei:EntityCommonStockSharesOutstanding contextRef="END" unitRef="SH" decimals="INF">42</dei:EntityCommonStockSharesOutstanding>
<dei:DocumentType contextRef="FY">10-K</dei:DocumentType>
<ACME:WidgetCosts contextRef="FY" unitRef="USD" decimals="0"> -30 </ACME:WidgetCosts>
<us-gaap:NetCashProvidedByUsedInOperatingActivities contextRef="FY" unitRef="USD" decimals="0">150</us-gaap:NetCashProvidedByUsedInOperatingActivities>
<us-gaap:DepreciationDepletionAndAmortization contextRef="FY" unitRef="USD" decimals="0">20</us-gaap:DepreciationDepletionAndAmortization>
"""


def _instance(facts: str = FACTS) -> bytes:
    return f'<?xml version="1.0"?><xbrli:xbrl {NS}>{CONTEXTS}{facts}</xbrli:xbrl>'.encode()


def _role_type(role_id: str, definition: str) -> str:
    return (
        f'<link:roleType roleURI="{ROLE}{role_id}" id="{role_id}">'
        f"<link:definition>{definition}</link:definition>"
        "<link:usedOn>link:presentationLink</link:usedOn></link:roleType>"
    )


def _href(concept: str) -> str:
    prefix, name = concept.split(":")
    if prefix == "ACME":
        return f"acme-20241231.xsd#ACME_{name}"
    return f"{GAAP}#{prefix}_{name}"


def _presentation(role_id: str, tree: Sequence[tuple[str, str, float, str | None]]) -> str:
    """tree: (parent, child, order, preferredLabel role or None)."""
    concepts = {c for parent, child, _, _ in tree for c in (parent, child)}
    locs = "".join(
        f'<link:loc xlink:type="locator" xlink:href="{_href(c)}" xlink:label="loc_{c.replace(":", "_")}"/>'
        for c in sorted(concepts)
    )
    arcs = "".join(
        '<link:presentationArc xlink:type="arc" '
        'xlink:arcrole="http://www.xbrl.org/2003/arcrole/parent-child" '
        f'xlink:from="loc_{p.replace(":", "_")}" xlink:to="loc_{c.replace(":", "_")}" order="{o}"'
        + (f' preferredLabel="{label}"' if label else "")
        + "/>"
        for p, c, o, label in tree
    )
    return (
        f'<link:presentationLink xlink:type="extended" xlink:role="{ROLE}{role_id}">'
        f"{locs}{arcs}</link:presentationLink>"
    )


def _calculation(role_id: str, edges: list[tuple[str, str, str]], arcrole: str) -> str:
    concepts = {c for parent, child, _ in edges for c in (parent, child)}
    locs = "".join(
        f'<link:loc xlink:type="locator" xlink:href="{_href(c)}" xlink:label="c_{c.replace(":", "_")}"/>'
        for c in sorted(concepts)
    )
    arcs = "".join(
        f'<link:calculationArc xlink:type="arc" xlink:arcrole="{arcrole}" '
        f'xlink:from="c_{p.replace(":", "_")}" xlink:to="c_{c.replace(":", "_")}" weight="{w}" order="1"/>'
        for p, c, w in edges
    )
    return (
        f'<link:calculationLink xlink:type="extended" xlink:role="{ROLE}{role_id}">'
        f"{locs}{arcs}</link:calculationLink>"
    )


def _labels(labels: list[tuple[str, str, str]]) -> str:
    """labels: (concept, label role, text)."""
    parts = []
    for i, (concept, role, text) in enumerate(labels):
        loc = f"lloc_{i}"
        parts.append(
            f'<link:loc xlink:type="locator" xlink:href="{_href(concept)}" xlink:label="{loc}"/>'
            f'<link:label xlink:type="resource" xlink:label="lab_{i}" xlink:role="{role}" '
            f'xml:lang="en-US">{text}</link:label>'
            '<link:labelArc xlink:type="arc" '
            'xlink:arcrole="http://www.xbrl.org/2003/arcrole/concept-label" '
            f'xlink:from="{loc}" xlink:to="lab_{i}"/>'
        )
    return f'<link:labelLink xlink:type="extended" xlink:role="http://www.xbrl.org/2003/role/link">{"".join(parts)}</link:labelLink>'


def _linkbase(body: str) -> bytes:
    return f'<?xml version="1.0"?><link:linkbase {NS}>{body}</link:linkbase>'.encode()


STD_LABEL = "http://www.xbrl.org/2003/role/label"
TOTAL_LABEL = "http://www.xbrl.org/2003/role/totalLabel"
SUMMATION = "http://www.xbrl.org/2003/arcrole/summation-item"
SUMMATION_2023 = "https://xbrl.org/2023/arcrole/summation-item"

IS_TREE = [
    ("us-gaap:IncomeStatementAbstract", "us-gaap:Revenues", 1, None),
    ("us-gaap:IncomeStatementAbstract", "ACME:WidgetCosts", 2, None),
    ("us-gaap:IncomeStatementAbstract", "us-gaap:NetIncomeLoss", 3, TOTAL_LABEL),
    ("us-gaap:IncomeStatementAbstract", "us-gaap:EarningsPerShareBasic", 4, None),
    ("us-gaap:IncomeStatementAbstract", "us-gaap:StatementBusinessSegmentsAxis", 5, None),
    ("us-gaap:StatementBusinessSegmentsAxis", "ACME:CloudMember", 1, None),
]
BS_TREE = [
    ("us-gaap:StatementOfFinancialPositionAbstract", "us-gaap:Assets", 2, None),
    (
        "us-gaap:StatementOfFinancialPositionAbstract",
        "us-gaap:LiabilitiesAndStockholdersEquity",
        3,
        None,
    ),
    ("us-gaap:StatementOfFinancialPositionAbstract", "us-gaap:AssetsAbstract", 1, None),
    ("us-gaap:AssetsAbstract", "us-gaap:Goodwill", 1, None),
]
CF_TREE = [
    ("us-gaap:StatementOfCashFlowsAbstract", "us-gaap:NetIncomeLoss", 1, None),
    (
        "us-gaap:StatementOfCashFlowsAbstract",
        "us-gaap:DepreciationDepletionAndAmortization",
        2,
        None,
    ),
    (
        "us-gaap:StatementOfCashFlowsAbstract",
        "us-gaap:NetCashProvidedByUsedInOperatingActivities",
        3,
        None,
    ),
]
CI_TREE = [
    ("us-gaap:StatementOfIncomeAndComprehensiveIncomeAbstract", "us-gaap:NetIncomeLoss", 1, None),
    (
        "us-gaap:StatementOfIncomeAndComprehensiveIncomeAbstract",
        "us-gaap:ComprehensiveIncomeNetOfTax",
        2,
        None,
    ),
]
PAREN_TREE = [
    ("us-gaap:StatementOfFinancialPositionAbstract", "us-gaap:Assets", 1, None),
    (
        "us-gaap:StatementOfFinancialPositionAbstract",
        "us-gaap:LiabilitiesAndStockholdersEquity",
        2,
        None,
    ),
    ("us-gaap:StatementOfFinancialPositionAbstract", "us-gaap:CommonStockSharesIssued", 3, None),
]

ROLE_TYPES = (
    _role_type("Cover", "0001 - Document - Cover")
    + _role_type("IS", "0002 - Statement - CONSOLIDATED STATEMENTS OF OPERATIONS")
    + _role_type("CI", "0003 - Statement - CONSOLIDATED STATEMENTS OF COMPREHENSIVE INCOME")
    + _role_type("BS", "0004 - Statement - CONSOLIDATED BALANCE SHEETS")
    + _role_type("BSP", "0005 - Statement - CONSOLIDATED BALANCE SHEETS (Parenthetical)")
    + _role_type("CF", "0006 - Statement - CONSOLIDATED STATEMENTS OF CASH FLOWS")
    + _role_type("Note", "0007 - Disclosure - Revenue")
)
ELEMENTS = (
    '<xsd:element id="ACME_WidgetCosts" name="WidgetCosts" type="xbrli:monetaryItemType" '
    'substitutionGroup="xbrli:item" abstract="false"/>'
    '<xsd:element id="ACME_CloudMember" name="CloudMember" type="nonnum:domainItemType" '
    'substitutionGroup="xbrli:item" abstract="true"/>'
)


def _schema(appinfo: str = ROLE_TYPES, extra: str = "") -> bytes:
    return (
        f'<?xml version="1.0"?><xsd:schema {NS} targetNamespace="http://www.acme.com/20241231">'
        f"<xsd:annotation><xsd:appinfo>{appinfo}{extra}</xsd:appinfo></xsd:annotation>"
        f"{ELEMENTS}</xsd:schema>"
    ).encode()


PRESENTATION = (
    _presentation("IS", IS_TREE)
    + _presentation("CI", CI_TREE)
    + _presentation("BS", BS_TREE)
    + _presentation("BSP", PAREN_TREE)
    + _presentation("CF", CF_TREE)
    + _presentation("Note", [("us-gaap:RevenueAbstract", "us-gaap:Revenues", 1, None)])
)
CALCULATION = _calculation(
    "IS",
    [
        ("us-gaap:NetIncomeLoss", "us-gaap:Revenues", "1"),
        ("us-gaap:NetIncomeLoss", "ACME:WidgetCosts", "-1"),
    ],
    SUMMATION,
) + _calculation(
    "CF",
    [
        (
            "us-gaap:NetCashProvidedByUsedInOperatingActivities",
            "us-gaap:DepreciationDepletionAndAmortization",
            "1.0",
        )
    ],
    SUMMATION_2023,
)
LABELS = _labels(
    [
        ("us-gaap:Revenues", STD_LABEL, "Net sales"),
        ("us-gaap:NetIncomeLoss", STD_LABEL, "Net income (loss)"),
        ("us-gaap:NetIncomeLoss", TOTAL_LABEL, "Net income"),
        ("ACME:WidgetCosts", STD_LABEL, "Widget costs"),
    ]
)


def _synthetic(*, embedded: bool = False, facts: str = FACTS) -> dict[str, bytes]:
    if embedded:
        linkbase = (
            '<link:linkbase id="lnk">' + PRESENTATION + CALCULATION + LABELS + "</link:linkbase>"
        )
        return {
            "acme-20241231_htm.xml": _instance(facts),
            "acme-20241231.xsd": _schema(extra=linkbase),
        }
    return {
        "acme-20241231_htm.xml": _instance(facts),
        "acme-20241231.xsd": _schema(),
        "acme-20241231_pre.xml": _linkbase(PRESENTATION),
        "acme-20241231_cal.xml": _linkbase(CALCULATION),
        "acme-20241231_lab.xml": _linkbase(LABELS),
    }


def _parse(files: dict[str, bytes]) -> ParsedFiling:
    return parse_filing(files, _anchors(), accession_no="0000000001-24-000001")


def _lines(parsed: ParsedFiling, statement: str) -> list[FilingLine]:
    return [line for line in parsed.lines if line.statement == statement]


def _fact_keys(
    parsed: ParsedFiling,
) -> dict[tuple[str, str], list[tuple[str, date | None, date, Decimal]]]:
    keys: dict[tuple[str, str], list[tuple[str, date | None, date, Decimal]]] = {}
    for f in parsed.facts:
        keys.setdefault((f.taxonomy, f.concept), []).append(
            (f.unit, f.period_start, f.period_end, f.value)
        )
    return keys


# --- facts ---------------------------------------------------------------------------------------


def test_the_parser_version_is_an_integer() -> None:
    assert isinstance(XBRL_PARSER_VERSION, int) and XBRL_PARSER_VERSION >= 1


def test_facts_carry_the_accession_and_no_frame() -> None:
    facts = _parse(_synthetic()).facts

    assert {f.accession_no for f in facts} == {"0000000001-24-000001"}
    assert {f.frame for f in facts} == {None}


def test_a_fact_in_a_dimensional_context_is_dropped() -> None:
    keys = _fact_keys(_parse(_synthetic()))

    # The segment fact (600) and the typed scenario fact (7) are dropped; the first plain
    # Revenues fact of a duplicate key wins over the second (999).
    assert keys["us-gaap", "Revenues"] == [
        ("USD", date(2024, 1, 1), date(2024, 12, 31), Decimal("1000"))
    ]
    assert keys["us-gaap", "Assets"] == [("USD", None, date(2024, 12, 31), Decimal("5000"))]


def test_of_two_facts_with_one_key_the_more_precise_wins_else_the_first() -> None:
    facts = (
        '<us-gaap:Revenues contextRef="FY" unitRef="USD" decimals="-8">22000000000</us-gaap:Revenues>'
        '<us-gaap:Revenues contextRef="FY" unitRef="USD" decimals="-6">22038000000</us-gaap:Revenues>'
        '<us-gaap:Revenues contextRef="FY" unitRef="USD" decimals="-6">22040000000</us-gaap:Revenues>'
        '<us-gaap:Assets contextRef="END" unitRef="USD" decimals="INF">5</us-gaap:Assets>'
        '<us-gaap:Assets contextRef="END" unitRef="USD" decimals="2">6</us-gaap:Assets>'
    )
    keys = _fact_keys(_parse(_synthetic(facts=facts)))

    assert keys["us-gaap", "Revenues"][0][3] == Decimal("22038000000")
    assert keys["us-gaap", "Assets"][0][3] == Decimal("5")


def test_a_value_is_kept_as_filed_whatever_its_decimals() -> None:
    facts = (
        '<dei:EntityListingParValuePerShare contextRef="FY" unitRef="EPS" decimals="INF">0.00000625</dei:EntityListingParValuePerShare>'
        '<us-gaap:EffectiveIncomeTaxRateContinuingOperations contextRef="FY" unitRef="PURE" decimals="0">2.73</us-gaap:EffectiveIncomeTaxRateContinuingOperations>'
    )
    keys = _fact_keys(_parse(_synthetic(facts=facts)))

    assert keys["dei", "EntityListingParValuePerShare"][0][3] == Decimal("0.00000625")
    assert keys["us-gaap", "EffectiveIncomeTaxRateContinuingOperations"][0][3] == Decimal("2.73")


def test_a_duration_that_starts_and_ends_on_one_day_is_an_instant() -> None:
    context = (
        '<xbrli:context id="DAY"><xbrli:entity><xbrli:identifier scheme="http://www.sec.gov/CIK">1'
        "</xbrli:identifier></xbrli:entity><xbrli:period><xbrli:startDate>2024-05-01"
        "</xbrli:startDate><xbrli:endDate>2024-05-01</xbrli:endDate></xbrli:period></xbrli:context>"
    )
    facts = context + (
        '<us-gaap:GoodwillImpairmentLoss contextRef="DAY" unitRef="USD" decimals="0">0'
        "</us-gaap:GoodwillImpairmentLoss>"
    )
    keys = _fact_keys(_parse(_synthetic(facts=facts)))

    assert keys["us-gaap", "GoodwillImpairmentLoss"] == [
        ("USD", None, date(2024, 5, 1), Decimal("0"))
    ]


def test_units_use_the_companyfacts_spellings() -> None:
    keys = _fact_keys(_parse(_synthetic()))

    assert keys["us-gaap", "EarningsPerShareBasic"][0][0] == "USD/shares"
    assert keys["dei", "EntityCommonStockSharesOutstanding"][0][0] == "shares"
    assert keys["us-gaap", "EffectiveIncomeTaxRateContinuingOperations"][0][0] == "pure"
    assert keys["us-gaap", "Revenues"][0][0] == "USD"


def test_nil_and_non_numeric_facts_are_skipped() -> None:
    keys = _fact_keys(_parse(_synthetic()))

    assert ("us-gaap", "Goodwill") not in keys
    assert ("dei", "DocumentType") not in keys


def test_an_extension_fact_takes_the_filers_prefix_lowercased_and_its_value_is_exact() -> None:
    keys = _fact_keys(_parse(_synthetic()))

    assert keys["acme", "WidgetCosts"] == [
        ("USD", date(2024, 1, 1), date(2024, 12, 31), Decimal("-30"))
    ]
    assert keys["us-gaap", "EarningsPerShareBasic"][0][3] == Decimal("1.25")
    assert all(isinstance(f.value, Decimal) for f in _parse(_synthetic()).facts)


def test_a_file_set_without_an_instance_is_an_error() -> None:
    files = _synthetic()
    del files["acme-20241231_htm.xml"]

    with pytest.raises(XbrlError, match="instance"):
        _parse(files)


def test_malformed_xml_is_an_error() -> None:
    files = _synthetic()
    files["acme-20241231_pre.xml"] = b"<link:linkbase"

    with pytest.raises(XbrlError):
        _parse(files)


# --- statements and lines ------------------------------------------------------------------------


def test_the_three_statements_are_found_and_the_other_roles_ignored() -> None:
    parsed = _parse(_synthetic())

    assert {line.statement for line in parsed.lines} == {"IS", "BS", "CF"}
    # The comprehensive-income role holds NetIncomeLoss but no revenue or EPS line; the
    # parenthetical balance sheet would otherwise qualify as a BS.
    assert "us-gaap:ComprehensiveIncomeNetOfTax" not in {
        f"{line.taxonomy}:{line.concept}" for line in parsed.lines
    }
    assert "us-gaap:CommonStockSharesIssued" not in {
        f"{line.taxonomy}:{line.concept}" for line in parsed.lines
    }


def test_lines_are_in_presentation_order_without_abstracts_axes_or_members() -> None:
    parsed = _parse(_synthetic())

    assert [(ln.position, ln.concept) for ln in _lines(parsed, "IS")] == [
        (1, "Revenues"),
        (2, "WidgetCosts"),
        (3, "NetIncomeLoss"),
        (4, "EarningsPerShareBasic"),
    ]
    # The arc order, not the document order, decides: AssetsAbstract (order 1) comes first.
    assert [ln.concept for ln in _lines(parsed, "BS")] == [
        "Goodwill",
        "Assets",
        "LiabilitiesAndStockholdersEquity",
    ]


def test_a_line_carries_its_calculation_parent_and_weight_in_the_same_role() -> None:
    lines = {ln.concept: ln for ln in _lines(_parse(_synthetic()), "IS")}

    assert (lines["Revenues"].calc_parent_taxonomy, lines["Revenues"].calc_parent_concept) == (
        "us-gaap",
        "NetIncomeLoss",
    )
    assert lines["Revenues"].calc_weight == Decimal("1")
    assert lines["WidgetCosts"].taxonomy == "acme"
    assert lines["WidgetCosts"].calc_weight == Decimal("-1")
    assert lines["NetIncomeLoss"].calc_parent_concept is None
    assert lines["NetIncomeLoss"].calc_weight is None
    # Revenues has no calculation parent in the note role; that does not leak into the IS.


def test_the_2023_calculation_arcrole_is_read_too() -> None:
    lines = {ln.concept: ln for ln in _lines(_parse(_synthetic()), "CF")}

    assert lines["DepreciationDepletionAndAmortization"].calc_parent_concept == (
        "NetCashProvidedByUsedInOperatingActivities"
    )
    assert lines["DepreciationDepletionAndAmortization"].calc_weight == Decimal("1")


def test_a_line_takes_its_preferred_label_else_the_standard_label_else_its_name() -> None:
    lines = {ln.concept: ln for ln in _lines(_parse(_synthetic()), "IS")}

    assert lines["NetIncomeLoss"].label == "Net income"  # the role's preferred (total) label
    assert lines["Revenues"].label == "Net sales"
    assert lines["EarningsPerShareBasic"].label == "EarningsPerShareBasic"


def test_linkbases_inside_the_schema_parse_like_separate_files() -> None:
    assert _parse(_synthetic(embedded=True)).lines == _parse(_synthetic()).lines


def test_of_two_roles_of_one_class_the_one_with_more_lines_wins() -> None:
    small_is = _presentation(
        "IS2",
        [
            ("us-gaap:IncomeStatementAbstract", "us-gaap:Revenues", 1, None),
            ("us-gaap:IncomeStatementAbstract", "us-gaap:NetIncomeLoss", 2, None),
        ],
    )
    files = _synthetic()
    files["acme-20241231.xsd"] = _schema(
        ROLE_TYPES + _role_type("IS2", "0008 - Statement - SEGMENT OPERATIONS")
    )
    files["acme-20241231_pre.xml"] = _linkbase(small_is + PRESENTATION)

    assert len(_lines(_parse(files), "IS")) == 4


def test_a_filing_without_statement_roles_has_facts_and_no_lines() -> None:
    files = _synthetic()
    del files["acme-20241231_pre.xml"]

    parsed = _parse(files)

    assert parsed.lines == []
    assert parsed.facts


def test_anchors_are_read_from_canonical_concept_entries() -> None:
    anchors = StatementAnchors.from_concepts(
        {
            "cfo": ("us-gaap:NetCashProvidedByUsedInOperatingActivities",),
            "revenue": ("us-gaap:Revenues", "us-gaap:SalesA+us-gaap:SalesB"),
            "other": ("us-gaap:Ignored",),
        }
    )

    assert anchors.cfo == frozenset({("us-gaap", "NetCashProvidedByUsedInOperatingActivities")})
    assert anchors.revenue_or_eps == frozenset(
        {("us-gaap", "Revenues"), ("us-gaap", "SalesA"), ("us-gaap", "SalesB")}
    )
    assert anchors.net_income == frozenset()


# --- the recorded filings -------------------------------------------------------------------------


@pytest.mark.parametrize(("ticker", "accession"), RECORDED)
def test_parity_with_companyfacts(ticker: str, accession: str) -> None:
    """Every non-dimensional standard fact the parser reads is the companyfacts fact of the same
    accession, concept, unit and period, and every such companyfacts fact is found."""
    parsed = {
        (f.taxonomy, f.concept, f.unit, f.period_start, f.period_end): f.value
        for f in _parsed(ticker, accession).facts
        if f.taxonomy in STANDARD
    }
    expected = {
        (
            f.taxonomy,
            f.concept,
            "USD/shares" if (accession, f.concept) in UNIT_EXCEPTIONS else f.unit,
            f.period_start,
            f.period_end,
        ): f.value
        for f in parse_companyfacts(_companyfacts(ticker)).facts
        if f.accession_no == accession and f.taxonomy in STANDARD
    }

    missing = sorted(set(expected) - set(parsed), key=str)
    extra = sorted(set(parsed) - set(expected), key=str)
    # Companyfacts keeps at most six decimal places (MSFT's par value of $0.00000625, tagged
    # decimals="INF", is 0.000006 there), so values are compared at six places.
    six = Decimal("0.000001")
    differ = sorted(
        (
            k
            for k in expected.keys() & parsed.keys()
            if expected[k].quantize(six) != parsed[k].quantize(six)
        ),
        key=str,
    )
    assert (missing[:5], extra[:5], differ[:5]) == ([], [], [])
    assert len(expected) > 100


@pytest.mark.parametrize(("ticker", "accession"), RECORDED)
def test_every_recorded_filing_has_the_three_statements(ticker: str, accession: str) -> None:
    lines = _parsed(ticker, accession).lines
    by_statement = {s: [ln for ln in lines if ln.statement == s] for s in ("IS", "BS", "CF")}

    assert all(len(group) >= 5 for group in by_statement.values())
    assert any(ln.concept == "Assets" for ln in by_statement["BS"])
    assert any(
        ln.concept.startswith("NetCashProvidedByUsedInOperatingActivities")
        for ln in by_statement["CF"]
    )
    for group in by_statement.values():
        assert [ln.position for ln in group] == list(range(1, len(group) + 1))
        assert len({(ln.taxonomy, ln.concept) for ln in group}) == len(group)


@pytest.mark.parametrize(("ticker", "accession"), RECORDED)
def test_every_recorded_filing_has_extension_facts(ticker: str, accession: str) -> None:
    prefix = ticker.lower()

    assert any(f.taxonomy == prefix for f in _parsed(ticker, accession).facts)
    assert all(f.taxonomy in STANDARD | {prefix} for f in _parsed(ticker, accession).facts)


def test_msft_2024_has_its_extension_d_and_a_line_on_the_cash_flow_with_a_parent() -> None:
    cf = [ln for ln in _parsed("MSFT", "0000950170-24-087843").lines if ln.statement == "CF"]
    line = next(ln for ln in cf if ln.concept == "DepreciationAmortizationAndOther")

    assert line.taxonomy == "msft"
    assert line.calc_parent_taxonomy == "us-gaap"
    assert line.calc_parent_concept == "NetCashProvidedByUsedInOperatingActivities"
    assert line.calc_weight == Decimal("1")
    assert "epreciation" in line.label
    fact = next(
        f
        for f in _parsed("MSFT", "0000950170-24-087843").facts
        if f.concept == "DepreciationAmortizationAndOther" and f.period_end == date(2024, 6, 30)
    )
    assert fact.value == Decimal("22287000000")


def test_msft_2024_comprehensive_income_role_is_not_the_income_statement() -> None:
    is_lines = [ln for ln in _parsed("MSFT", "0000950170-24-087843").lines if ln.statement == "IS"]

    assert any(
        ln.concept == "RevenueFromContractWithCustomerExcludingAssessedTax" for ln in is_lines
    )
    assert not any(ln.concept == "ComprehensiveIncomeNetOfTax" for ln in is_lines)


def test_the_standard_taxonomies_are_the_ones_companyfacts_carries() -> None:
    assert [
        is_standard_taxonomy(t) for t in ("us-gaap", "dei", "srt", "ifrs-full", "msft", "de")
    ] == [
        True,
        True,
        True,
        True,
        False,
        False,
    ]


def test_a_malformed_date_is_an_xbrl_error() -> None:
    files = _synthetic()
    files["acme-20241231_htm.xml"] = files["acme-20241231_htm.xml"].replace(
        b"<xbrli:instant>2024-12-31</xbrli:instant>",
        b"<xbrli:instant>2024-13-45</xbrli:instant>",
        1,
    )

    with pytest.raises(XbrlError, match="2024-13-45"):
        _parse(files)


def test_a_non_numeric_arc_order_is_an_xbrl_error() -> None:
    files = _synthetic()
    files["acme-20241231_pre.xml"] = files["acme-20241231_pre.xml"].replace(
        b'order="1"', b'order="first"', 1
    )

    with pytest.raises(XbrlError, match="first"):
        _parse(files)
