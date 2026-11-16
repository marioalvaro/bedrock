"""The structure rules (M7b S7) on the recorded development companies: their companyfacts and
the face lines of their recorded filings (docs/erd/data-coverage.md "Structure rules")."""

from decimal import Decimal

import pytest

from bedrock.statements.build import StatementTable
from tests.statements_pipeline import all_facts, run_pipeline

DEVELOPMENT = ("AAPL", "MSFT", "COST", "DE", "BA", "JNJ", "NFLX", "NKE", "ORCL", "WMT")


def _r9(formula: str | None) -> bool:
    return formula is not None and formula.startswith("no ") and " line on the " in formula


def _cells(table: StatementTable):  # type: ignore[no-untyped-def]
    for row in table.rows:
        for at, period in enumerate(table.periods):
            yield row, period, row.values[at], row.provenance[at]


def r9_zeros(ticker: str) -> list[tuple[str, str]]:
    """(code, period key) of every cell R9 inferred 0, in both frequencies."""
    from bedrock.statements.cells import solve_cells
    from bedrock.statements.imports import company_calendar

    pipeline = run_pipeline(ticker)
    calendar = company_calendar(pipeline.canonical, pipeline.rules.imported)
    cells = solve_cells(pipeline.canonical, pipeline.items, calendar, pipeline.rules).cells
    return sorted(
        key
        for key, cell in cells.items()
        if cell.provenance == "zero_inferred"
        and cell.derivation is not None
        and _r9(cell.derivation.formula)
    )


@pytest.mark.parametrize("ticker", DEVELOPMENT)
def test_no_inferred_zero_sits_in_a_year_with_a_non_zero_value(ticker: str) -> None:
    """A known non-zero line is never inferred 0: no R9 zero in a (code, fiscal year) where any
    vintage of a mapped concept, or any quarter of the year, has a non-zero value."""
    pipeline = run_pipeline(ticker)
    facts = all_facts(ticker)
    concepts: dict[str, set[tuple[str, str]]] = {}
    for code, taxonomy, concept in zip(
        pipeline.mappings["canonical_code"],
        pipeline.mappings["taxonomy"],
        pipeline.mappings["concept"],
        strict=True,
    ):
        concepts.setdefault(code, set()).add((taxonomy, concept))
    quarter_values = {
        (row.code, period.fiscal_year): value
        for table in pipeline.quarterly.values()
        for row, period, value, _ in _cells(table)
        if value is not None and value != 0
    }
    ends = {
        (row.code, period.fiscal_year): (period.start, period.end)
        for table in pipeline.annual.values()
        for row, period, _, _ in _cells(table)
    }
    wrong = []
    for code, key in r9_zeros(ticker):
        year = int(key[2:6])
        if (code, year) in quarter_values:
            wrong.append((code, key, "a quarter", quarter_values[(code, year)]))
            continue
        start, end = ends.get((code, year), (None, None))
        if end is None:
            continue
        mine = facts[
            [
                (t, c) in concepts.get(code, set()) and e == end and v != 0
                for t, c, e, v in zip(
                    facts["taxonomy"],
                    facts["concept"],
                    facts["period_end"],
                    facts["value"],
                    strict=True,
                )
            ]
        ]
        if not mine.empty:
            wrong.append((code, key, "a vintage", mine.iloc[0]["value"]))

    assert wrong == []


@pytest.mark.parametrize(
    ("ticker", "code", "key"),
    [
        ("AAPL", "short_term_debt", "FY2009"),  # no debt before the FY2013 notes (10-K FY2010)
        ("COST", "rnd", "FY2026"),  # a retailer without research and development
        ("NFLX", "dividends_paid", "FY2025"),  # Netflix pays no dividend
    ],
)
def test_a_known_true_zero_is_inferred(ticker: str, code: str, key: str) -> None:
    assert (code, key) in r9_zeros(ticker)


def test_dividends_per_share_follows_an_inferred_zero_of_dividends_paid() -> None:
    pipeline = run_pipeline("NFLX")
    row = next(r for r in pipeline.annual["IS"].rows if r.code == "dividends_per_share")
    at = next(i for i, p in enumerate(pipeline.annual["IS"].periods) if p.key == "FY2025")

    assert (row.values[at], row.provenance[at]) == (Decimal(0), "zero_inferred")


def test_msft_fy2024_d_and_a_comes_from_its_extension_line_and_equals_the_10k() -> None:
    # "Depreciation, amortization, and other", msft:DepreciationAmortizationAndOther: 22,287 in the
    # FY2024 10-K (0000950170-24-087843), restated to 20,958 in the FY2026 10-K, the newest vintage
    pipeline = run_pipeline("MSFT")
    table = pipeline.annual["CF"]
    row = next(r for r in table.rows if r.code == "d_and_a")
    at = next(i for i, p in enumerate(table.periods) if p.key == "FY2024")

    assert (row.values[at], row.provenance[at]) == (Decimal(20_958_000_000), "reported")


def test_apple_lists_only_the_extension_lines_nobody_classified() -> None:
    from bedrock.mapping.gaps import unclassified_lines

    pipeline = run_pipeline("AAPL")
    found = unclassified_lines(pipeline.rules.filing_lines, pipeline.items)

    # the FY2025 10-K has none; the newest 10-Q (Q3 FY2026) presents one Apple extension line
    assert [(u.statement, u.taxonomy, u.concept, u.filings) for u in found] == [
        ("BS", "aapl", "IntangibleAssetsNetExcludingGoodwillNoncurrent", ["0000320193-26-000020"])
    ]
