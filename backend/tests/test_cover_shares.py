"""The cover-page share count rule (docs/erd/data.md "R7"): an empty `shares_outstanding` instant
takes the cover-page count of the filing that reports the period, marked `approximated`."""

from datetime import date, timedelta
from decimal import Decimal

import pandas as pd

from bedrock.mapping.config import IdentityDef, SolveRule
from bedrock.mapping.mapper import map_facts
from bedrock.mapping.vintage import select_vintage
from bedrock.statements.cells import Cell, solve_cells
from bedrock.statements.periods import fiscal_calendar
from bedrock.statements.rules import Rules
from bedrock.statements.splits import split_adjust
from tests.engine_data import canon, canon_frame, facts, flow_facts, instant_facts, item, mappings

M = 1_000_000
ITEMS = [
    item("revenue"),
    item("shares_outstanding", "BS", kind="instant", unit="shares"),
    item("shares_issued", "BS", kind="instant", unit="shares"),
    item("treasury_shares", "BS", kind="instant", unit="shares"),
]
MAPS = mappings(
    ("revenue", "Revenues", 0),
    ("shares_outstanding", "CommonStockSharesOutstanding", 0),
    ("shares_issued", "CommonStockSharesIssued", 0),
    ("treasury_shares", "TreasuryStockCommonShares", 0),
)
COUNT = IdentityDef(
    "shares_outstanding_count",
    "shares_outstanding = shares_issued - treasury_shares",
    ((1, "shares_outstanding"), (-1, "shares_issued"), (1, "treasury_shares")),
    {"shares_outstanding": SolveRule("exact", None)},
)
Q1, Q2, Q3, FY = date(2022, 9, 30), date(2022, 12, 31), date(2023, 3, 31), date(2023, 6, 30)


def cover(
    period_end: date,
    value: int,
    *,
    accession: str | None = None,
    filed: date | None = None,
    form: str = "10-Q",
) -> dict[str, object]:
    """The cover-page count of the filing whose report period ends on `period_end`: its fact is
    dated a few weeks later, which the repository replaces by the report period end."""
    return canon(
        "shares_outstanding",
        None,
        period_end,
        value,
        kind="instant",
        concept="EntityCommonStockSharesOutstanding",
        unit="shares",
        accession=accession or f"C-{period_end.isoformat()}",
        form=form,
        filed=filed or period_end + timedelta(days=30),
    ) | {"taxonomy": "dei"}


def solve(
    covers: list[dict[str, object]] | None,
    rows: list[dict[str, object]] | None = None,
    identities: tuple[IdentityDef, ...] = (),
    splits: tuple[object, ...] = (),
) -> dict[tuple[str, str], Cell]:
    calendar_rows = flow_facts("Revenues", {2023: (1, 1, 1, 1)}) + (rows or [])
    canonical = map_facts(select_vintage(facts(calendar_rows)), MAPS, ITEMS)  # type: ignore[arg-type]
    frame: pd.DataFrame | None = None
    if covers is not None:
        frame = canon_frame(covers)
        if splits:
            frame = split_adjust(frame, splits)  # type: ignore[arg-type]
    return solve_cells(
        canonical, ITEMS, fiscal_calendar(canonical), Rules(identities, None, frame)
    ).cells


def test_an_empty_quarter_end_takes_the_cover_page_count_as_approximated() -> None:
    cells = solve([cover(Q1, 100 * M), cover(Q2, 101 * M), cover(Q3, 102 * M), cover(FY, 103 * M)])

    q1 = cells[("shares_outstanding", "FY2023Q1")]
    assert (q1.value, q1.provenance) == (Decimal(100 * M), "approximated")
    assert q1.source is not None
    assert (q1.source.taxonomy, q1.source.concept) == ("dei", "EntityCommonStockSharesOutstanding")
    assert q1.source.accession_no == f"C-{Q1.isoformat()}"
    assert q1.derivation is not None
    assert q1.derivation.formula == f"cover-page shares outstanding of 10-Q C-{Q1.isoformat()}"
    assert cells[("shares_outstanding", "FY2023")].value == 103 * M
    assert cells[("shares_outstanding", "FY2023Q3")].value == 102 * M


def test_q4_is_the_year_end_count() -> None:
    cells = solve([cover(FY, 103 * M, form="10-K")])

    q4 = cells[("shares_outstanding", "FY2023Q4")]
    assert (q4.value, q4.provenance) == (Decimal(103 * M), "approximated")


def test_a_period_without_a_cover_page_count_stays_empty() -> None:
    cells = solve([cover(Q1, 100 * M)])

    assert cells[("shares_outstanding", "FY2023Q2")].value is None
    assert cells[("shares_outstanding", "FY2023")].value is None


def test_a_report_period_end_a_few_days_off_still_matches_and_a_week_and_a_day_does_not() -> None:
    near = solve([cover(Q1 + timedelta(days=3), 100 * M)])
    far = solve([cover(Q1 + timedelta(days=8), 100 * M)])

    assert near[("shares_outstanding", "FY2023Q1")].value == 100 * M
    assert far[("shares_outstanding", "FY2023Q1")].value is None


def test_the_latest_filed_count_of_a_period_wins() -> None:
    cells = solve(
        [
            cover(FY, 103 * M, accession="K", filed=date(2023, 8, 1), form="10-K"),
            cover(FY, 104 * M, accession="K/A", filed=date(2023, 9, 1), form="10-K/A"),
        ]
    )

    assert cells[("shares_outstanding", "FY2023")].value == 104 * M
    assert cells[("shares_outstanding", "FY2023")].source is not None


def test_a_reported_count_is_never_replaced() -> None:
    reported = instant_facts(
        "CommonStockSharesOutstanding", {2023: (90 * M, None, None, None)}, unit="shares"
    )
    cells = solve([cover(Q1, 100 * M)], reported)

    q1 = cells[("shares_outstanding", "FY2023Q1")]
    assert (q1.value, q1.provenance) == (Decimal(90 * M), "reported")


def test_issued_less_treasury_beats_the_cover_page_count() -> None:
    rows = instant_facts(
        "CommonStockSharesIssued", {2023: (None, None, None, 120 * M)}, unit="shares"
    ) + instant_facts(
        "TreasuryStockCommonShares", {2023: (None, None, None, 20 * M)}, unit="shares"
    )
    cells = solve([cover(FY, 103 * M, form="10-K")], rows, (COUNT,))

    year = cells[("shares_outstanding", "FY2023")]
    assert (year.value, year.provenance) == (Decimal(100 * M), "derived")
    assert year.solved_by == "shares_outstanding_count"
    assert cells[("shares_outstanding", "FY2023Q4")].provenance == "derived"


def test_a_missing_treasury_count_is_not_an_identity_so_the_cover_page_count_fills() -> None:
    rows = instant_facts(
        "CommonStockSharesIssued", {2023: (None, None, None, 120 * M)}, unit="shares"
    )
    cells = solve([cover(FY, 103 * M, form="10-K")], rows, (COUNT,))

    assert cells[("shares_outstanding", "FY2023")].provenance == "approximated"


def test_a_later_split_adjusts_the_cover_page_count_and_says_so() -> None:
    class Split:
        effective_date = date(2024, 1, 1)
        ratio = Decimal(4)

    cells = solve([cover(Q1, 100 * M)], splits=(Split(),))

    q1 = cells[("shares_outstanding", "FY2023Q1")]
    assert q1.value == 400 * M
    assert q1.derivation is not None
    assert "split 2024-01-01" in q1.derivation.formula


def test_without_cover_page_counts_the_rule_is_off() -> None:
    cells = solve(None)

    assert cells[("shares_outstanding", "FY2023Q1")].value is None
