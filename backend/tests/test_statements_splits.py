from dataclasses import dataclass
from datetime import date
from decimal import Decimal

import pandas as pd

from bedrock.mapping.mapper import CANONICAL_COLUMNS, map_facts
from bedrock.mapping.vintage import select_vintage
from bedrock.statements.cells import DerivationInput, compute_cells
from bedrock.statements.explain import explain_cell
from bedrock.statements.periods import fiscal_calendar
from bedrock.statements.splits import split_adjust, split_factor
from tests.engine_data import canon, canon_frame, fact, facts, item, mappings

FILED = date(2015, 10, 28)
SPLIT_2014 = date(2014, 6, 9)
SPLIT_2020 = date(2020, 8, 31)


@dataclass(frozen=True)
class S:
    effective_date: date
    ratio: Decimal


S7 = S(SPLIT_2014, Decimal(7))
S4 = S(SPLIT_2020, Decimal(4))


def row(
    value: str = "100", unit: str = "shares", filed: date = FILED, code: str = "x"
) -> pd.DataFrame:
    return canon_frame(
        [canon(code, date(2014, 9, 28), date(2015, 9, 26), value, unit=unit, filed=filed)]
    )


def adjusted(frame: pd.DataFrame, *actions: S) -> pd.Series:
    return split_adjust(frame, list(actions)).iloc[0]


def test_factor_is_1_with_no_actions() -> None:
    out = adjusted(row())

    assert out["value"] == 100 and out["split_factor"] == 1
    assert out["split_dates"] == () and out["reported_value"] == 100


def test_factor_is_1_for_a_split_on_or_before_the_filing_date() -> None:
    assert adjusted(row(), S(FILED, Decimal(4)), S7)["split_factor"] == 1


def test_shares_are_multiplied_per_share_divided_and_usd_untouched() -> None:
    assert adjusted(row("100", "shares"), S4)["value"] == 400
    assert adjusted(row("8", "USD/shares"), S4)["value"] == 2
    usd = adjusted(row("8", "USD"), S4)
    assert usd["value"] == 8 and usd["split_factor"] == 1 and usd["split_dates"] == ()


def test_two_later_splits_multiply_and_list_dates_oldest_first() -> None:
    out = adjusted(row("100", "shares", date(2013, 10, 30)), S4, S7)

    assert out["split_factor"] == 28 and out["value"] == 2800
    assert out["split_dates"] == (SPLIT_2014, SPLIT_2020)
    assert out["reported_value"] == 100


def test_a_split_between_period_end_and_filing_is_not_applied() -> None:
    frame = row(filed=date(2015, 11, 20))  # period ends 2015-09-26
    assert adjusted(frame, S(date(2015, 10, 1), Decimal(2)))["split_factor"] == 1


def test_aapl_fy2013_eps_from_the_fy2015_10k() -> None:
    out = adjusted(row("5.68", "USD/shares", FILED), S7, S4)
    assert out["split_factor"] == 4 and out["value"] == Decimal("1.42")


def test_a_non_terminating_division_is_quantized() -> None:
    out = adjusted(row("1", "USD/shares", date(2013, 1, 1)), S7)

    assert out["value"] == Decimal("0.1428571429")
    assert str(adjusted(row("7", "USD/shares", date(2013, 1, 1)), S7)["value"]) == "1"


def test_an_empty_frame_gets_the_new_columns() -> None:
    out = split_adjust(canon_frame([]), [S4])

    assert out.empty
    assert list(out.columns) == [
        *CANONICAL_COLUMNS,
        "split_factor",
        "split_dates",
        "reported_value",
    ]


def test_the_input_frame_is_unchanged() -> None:
    frame = row("100", "shares", date(2013, 1, 1))
    split_adjust(frame, [S4])

    assert list(frame.columns) == CANONICAL_COLUMNS and frame.iloc[0]["value"] == 100


def test_split_factor_is_the_product_of_ratios_effective_after_the_filing() -> None:
    assert split_factor(date(2013, 1, 1), [S4, S7]) == 28
    assert split_factor(FILED, [S4, S7]) == 4
    assert split_factor(SPLIT_2020, [S4]) == 1  # on the filing date: already restated
    assert split_factor(FILED, []) == 1


# --- provenance ----------------------------------------------------------------------------

ITEMS = [item("shares_x", "IS", unit="shares"), item("eps_x", "IS", unit="USD/shares")]
FY_START, FY_END = date(2014, 7, 1), date(2015, 6, 30)


def split_frame(filed: date = FILED) -> pd.DataFrame:
    return canon_frame(
        [
            canon("shares_x", FY_START, FY_END, 100, unit="shares", filed=filed),
            canon("eps_x", FY_START, FY_END, "5.60", unit="USD/shares", filed=filed),
        ]
    )


def fy_cell(frame: pd.DataFrame, code: str, *actions: S):  # type: ignore[no-untyped-def]
    adj = split_adjust(frame, list(actions))
    return compute_cells(adj, ITEMS, fiscal_calendar(adj))[(code, "FY2015")]


def test_a_split_adjusted_shares_cell_is_derived_with_a_multiply_formula() -> None:
    cell = fy_cell(split_frame(), "shares_x", S4)

    assert cell.value == 400 and cell.provenance == "derived"
    assert cell.source is not None and cell.source.filed_at == FILED
    assert cell.derivation is not None
    assert cell.derivation.formula == "as reported × 4 (split 2020-08-31)"
    assert cell.derivation.inputs == (DerivationInput("shares_x", "FY", Decimal(100)),)


def test_a_per_share_cell_divides_and_multiple_splits_are_listed() -> None:
    cell = fy_cell(split_frame(date(2013, 8, 1)), "eps_x", S7, S4)

    assert cell.value == Decimal("0.2")
    assert cell.derivation is not None
    assert cell.derivation.formula == "as reported ÷ 28 (splits 2014-06-09, 2020-08-31)"
    assert cell.derivation.inputs == (DerivationInput("eps_x", "FY", Decimal("5.60")),)


def test_a_fractional_factor_prints_plainly() -> None:
    cell = fy_cell(split_frame(), "shares_x", S(SPLIT_2020, Decimal("0.1")))

    assert cell.derivation is not None
    assert cell.derivation.formula == "as reported × 0.1 (split 2020-08-31)"


def test_factor_1_stays_reported() -> None:
    cell = fy_cell(split_frame(), "shares_x", S7)  # 2014 split is before the filing
    assert cell.provenance == "reported" and cell.value == 100 and cell.derivation is None


def test_frames_without_split_columns_are_unchanged() -> None:
    frame = split_frame()
    cell = compute_cells(frame, ITEMS, fiscal_calendar(frame))[("shares_x", "FY2015")]
    assert cell.provenance == "reported" and cell.value == 100


def test_explain_shows_the_derivation_and_unadjusted_vintages() -> None:
    raw = facts(
        [
            fact("Shr", FY_START, FY_END, 100, unit="shares", accession="K-1", filed=FILED),
            fact(
                "Shr", FY_START, FY_END, 100, unit="shares", accession="K-0", filed=date(2015, 8, 1)
            ),
        ]
    )
    canonical = split_adjust(
        map_facts(select_vintage(raw), mappings(("shares_x", "Shr", 0)), ITEMS), [S4]
    )
    out = explain_cell(canonical, raw, ITEMS, "shares_x", 2015, "FY")

    assert out.value == 400 and out.provenance == "derived"
    assert out.derivation is not None
    assert out.derivation.formula == "as reported × 4 (split 2020-08-31)"
    assert out.filing is not None and out.filing.filed_at == FILED
    assert [v.value for v in out.vintages] == [100, 100]


def test_quarterly_q4_over_adjusted_values_still_sums() -> None:
    q_ends = [date(2014, 9, 30), date(2014, 12, 31), date(2015, 3, 31)]
    rows = [canon("shares_x", FY_START, FY_END, 400, unit="shares", filed=FILED)]
    rows += [
        canon("shares_x", FY_START, e, v, unit="shares", filed=FILED)
        for e, v in zip(q_ends, (100, 200, 300), strict=True)
    ]
    frame = canon_frame(rows)
    adj = split_adjust(frame, [S4])
    cells = compute_cells(adj, ITEMS, fiscal_calendar(adj))

    assert cells[("shares_x", "FY2015")].value == 1600
    q4 = cells[("shares_x", "FY2015Q4")]
    assert q4.value == 1600 - 1200 and q4.provenance == "derived"
