"""Q4 of the average items (docs/erd/data.md "R2"): weighted share counts and EPS, on synthetic
frames. A year's Q4 is not reported for an average, so it is rebuilt from the year and Q1-Q3."""

from collections.abc import Sequence
from datetime import date
from decimal import Decimal

from tests.average_data import JUNE, WEEKS, M, Row, eps, flow, income, q4, shares, solve

# --- shares ---------------------------------------------------------------------------------


def test_q4_shares_are_the_day_weighted_remainder_of_the_year() -> None:
    d1, d2, d3, d4 = JUNE.days()
    assert (d1, d2, d3, d4) == (92, 92, 90, 91)
    cells, warnings = solve(
        income(JUNE) + shares("shares_diluted", JUNE, 103 * M, (100 * M, 102 * M, 104 * M))
    )

    expected = Decimal(103 * M * 365 - 100 * M * 92 - 102 * M * 92 - 104 * M * 90) / 91
    cell = q4(cells, "shares_diluted")
    assert cell.value == expected.quantize(Decimal(1))  # 106,054,945: rounded to a share
    assert cell.value == Decimal(106_054_945)
    assert warnings == []


def test_q4_shares_are_approximated_and_explain_their_inputs() -> None:
    cells, _ = solve(
        income(JUNE) + shares("shares_basic", JUNE, 103 * M, (100 * M, 102 * M, 104 * M))
    )

    cell = q4(cells, "shares_basic")
    assert cell.provenance == "approximated"
    assert cell.source is None
    assert cell.derivation is not None
    assert cell.derivation.formula == "(FY × days FY - sum of Q × days Q) / days Q4"
    assert [(i.fiscal_period, i.value) for i in cell.derivation.inputs] == [
        ("FY", Decimal(103 * M)),
        ("Q1", Decimal(100 * M)),
        ("Q2", Decimal(102 * M)),
        ("Q3", Decimal(104 * M)),
    ]


def test_unequal_quarter_lengths_weight_the_fourth_quarter_by_its_sixteen_weeks() -> None:
    assert WEEKS.days() == [84, 84, 84, 112]
    # three quarters at 100 M and a Q4 of 115 M: the year is the 364-day weighted mean
    fiscal = round((100 * M * 252 + 115 * M * 112) / 364)
    cells, warnings = solve(
        income(WEEKS) + shares("shares_diluted", WEEKS, fiscal, (100 * M, 100 * M, 100 * M))
    )

    cell = cells[("shares_diluted", "FY2023Q4")]
    assert abs(cell.value - 115 * M) < 10  # equal weights would give about 118.5 M
    assert warnings == []


def test_q4_shares_are_rebuilt_from_split_adjusted_inputs() -> None:
    class Split:
        effective_date = date(2024, 1, 1)  # after every filing below
        ratio = Decimal(4)

    cells, _ = solve(
        income(JUNE) + shares("shares_diluted", JUNE, 103 * M, (100 * M, 102 * M, 104 * M)),
        splits=[Split()],
    )

    assert cells[("shares_diluted", "FY2023")].value == 412 * M
    assert q4(cells, "shares_diluted").value == Decimal(424_219_780)  # 4 x 106,054,945.05


def test_a_missing_quarter_leaves_q4_shares_empty_without_a_warning() -> None:
    cells, warnings = solve(
        income(JUNE) + shares("shares_diluted", JUNE, 103 * M, (100 * M, None, 104 * M))
    )

    assert q4(cells, "shares_diluted").value is None
    assert warnings == []


def test_a_year_without_a_fiscal_value_has_no_q4_shares() -> None:
    rows = income(JUNE) + shares("shares_diluted", JUNE, 103 * M, (100 * M, 102 * M, 104 * M))
    rows = [
        r
        for r in rows
        if not (
            r["concept"] == "WeightedAverageNumberOfDilutedSharesOutstanding"
            and r["form"] == "10-K"
        )
    ]
    cells, warnings = solve(rows)

    assert q4(cells, "shares_diluted").value is None
    assert warnings == []


def test_q4_shares_that_are_not_positive_are_refused_with_a_warning() -> None:
    cells, warnings = solve(
        income(JUNE) + shares("shares_diluted", JUNE, 50 * M, (100 * M, 102 * M, 104 * M))
    )

    assert q4(cells, "shares_diluted").value is None
    [warning] = warnings
    assert (warning.rule, warning.code, warning.period_key) == (
        "q4_shares",
        "shares_diluted",
        "FY2023Q4",
    )
    assert warning.value is not None and warning.value <= 0
    assert "positive" in warning.reason


def test_q4_shares_more_than_twenty_percent_from_q3_are_refused_with_a_warning() -> None:
    # Q4 would be about 150 M against a Q3 of 104 M
    fiscal = round((100 * M * 92 + 102 * M * 92 + 104 * M * 90 + 150 * M * 91) / 365)
    cells, warnings = solve(
        income(JUNE) + shares("shares_diluted", JUNE, fiscal, (100 * M, 102 * M, 104 * M))
    )

    assert q4(cells, "shares_diluted").value is None
    [warning] = warnings
    assert warning.rule == "q4_shares"
    assert warning.value is not None and abs(warning.value - 150 * M) < 10
    assert "20%" in warning.reason


def test_q4_shares_just_inside_twenty_percent_of_q3_are_accepted() -> None:
    target = 124 * M  # 19.2% above Q3
    fiscal = round((100 * M * 92 + 102 * M * 92 + 104 * M * 90 + target * 91) / 365)
    cells, warnings = solve(
        income(JUNE) + shares("shares_diluted", JUNE, fiscal, (100 * M, 102 * M, 104 * M))
    )

    assert q4(cells, "shares_diluted").value is not None
    assert warnings == []


def test_basic_and_diluted_shares_are_rebuilt_separately() -> None:
    cells, _ = solve(
        income(JUNE)
        + shares("shares_basic", JUNE, 103 * M, (100 * M, 102 * M, 104 * M))
        + shares("shares_diluted", JUNE, 105 * M, (102 * M, 104 * M, 106 * M))
    )

    assert q4(cells, "shares_basic").value != q4(cells, "shares_diluted").value
    assert q4(cells, "shares_diluted").value == Decimal(108_054_945)


# --- EPS ------------------------------------------------------------------------------------


def eps_case(
    fiscal: str,
    quarters: Sequence[str | None],
    *,
    net_income: tuple[int, Sequence[int | None]] = (400, (100, 100, 100)),
) -> list[Row]:
    """Shares of 100 M in every quarter (Q4 comes out at 100 M), so EPS = net income / 100 M."""
    return (
        income(JUNE, *net_income)
        + shares("shares_diluted", JUNE, 100 * M, (100 * M, 100 * M, 100 * M))
        + eps("eps_diluted", JUNE, fiscal, quarters)
    )


def test_q4_eps_is_q4_net_income_over_q4_shares() -> None:
    cells, warnings = solve(eps_case("4.00", ("1.00", "1.00", "1.00")))

    cell = q4(cells, "eps_diluted")
    assert cell.value == Decimal(1)  # 100 M / 100 M
    assert cell.provenance == "approximated"
    assert cell.source is None
    assert cell.derivation is not None
    assert cell.derivation.formula == "net_income_common / shares_diluted"
    assert [(i.code, i.fiscal_period, i.value) for i in cell.derivation.inputs] == [
        ("net_income_common", "Q4", Decimal(100 * M)),
        ("shares_diluted", "Q4", Decimal(100 * M)),
    ]
    assert warnings == []


def test_q4_eps_is_rounded_to_ten_places() -> None:
    cells, _ = solve(
        income(JUNE)
        + shares("shares_diluted", JUNE, 103 * M, (100 * M, 102 * M, 104 * M))
        + eps("eps_diluted", JUNE, "3.84", ("0.97", "0.98", "0.96"))
    )

    # Q4 net income 100 M over the 106,054,945 shares of the day-weighted Q4
    assert q4(cells, "eps_diluted").value == (Decimal(100 * M) / 106_054_945).quantize(
        Decimal("1e-10")
    )


def test_q4_eps_is_accepted_within_two_cents_of_the_year_less_the_quarters() -> None:
    # FY 3.99 - 3 x 1.00 = 0.99 against a computed 1.00: a cent apart
    cells, warnings = solve(eps_case("3.99", ("1.00", "1.00", "1.00")))

    assert q4(cells, "eps_diluted").value == Decimal(1)
    assert warnings == []


def test_q4_eps_is_refused_when_it_disagrees_with_the_year_less_the_quarters() -> None:
    # FY 3.50 - 3 x 1.00 = 0.50 against a computed 1.00
    cells, warnings = solve(eps_case("3.50", ("1.00", "1.00", "1.00")))

    assert q4(cells, "eps_diluted").value is None
    [warning] = warnings
    assert (warning.rule, warning.code, warning.period_key) == ("q4_eps", "eps_diluted", "FY2023Q4")
    assert warning.value == Decimal(1)
    assert "FY - Q1 - Q2 - Q3" in warning.reason


def test_the_eps_tolerance_is_three_percent_of_the_year_when_that_is_wider() -> None:
    # FY 102.00 - 3 x 25.00 = 27.00 against a computed 25.00: two dollars apart, within 3% of 102
    cells, warnings = solve(
        income(JUNE, 10_000, (2_500, 2_500, 2_500))
        + shares("shares_diluted", JUNE, 100 * M, (100 * M, 100 * M, 100 * M))
        + eps("eps_diluted", JUNE, "102.00", ("25.00", "25.00", "25.00"))
    )

    assert q4(cells, "eps_diluted").value == Decimal(25)
    assert warnings == []


def test_q4_eps_is_empty_without_q4_net_income() -> None:
    rows = [
        r for r in eps_case("4.00", ("1.00", "1.00", "1.00")) if r["concept"] != "NetIncomeLoss"
    ]
    # revenue keeps the calendar
    cells, _ = solve(rows + flow("Revenues", JUNE, 900 * M, [200 * M, 200 * M, 200 * M]))

    assert q4(cells, "eps_diluted").value is None


def test_q4_eps_is_empty_when_q4_shares_were_refused() -> None:
    rows = (
        income(JUNE)
        + shares("shares_diluted", JUNE, 50 * M, (100 * M, 102 * M, 104 * M))
        + eps("eps_diluted", JUNE, "4.00", ("1.00", "1.00", "1.00"))
    )
    cells, warnings = solve(rows)

    assert q4(cells, "eps_diluted").value is None
    assert [w.rule for w in warnings] == ["q4_shares"]


def test_q4_eps_is_empty_when_the_year_or_a_quarter_is_missing_so_it_cannot_be_checked() -> None:
    cells, warnings = solve(eps_case("4.00", ("1.00", None, "1.00")))

    assert q4(cells, "eps_diluted").value is None
    assert warnings == []


def test_basic_eps_uses_basic_shares() -> None:
    rows = (
        income(JUNE)
        + shares("shares_basic", JUNE, 100 * M, (100 * M, 100 * M, 100 * M))
        + shares("shares_diluted", JUNE, 200 * M, (200 * M, 200 * M, 200 * M))
        + eps("eps_basic", JUNE, "4.00", ("1.00", "1.00", "1.00"))
    )
    cells, _ = solve(rows)

    assert q4(cells, "eps_basic").value == Decimal(1)


def test_a_reported_year_and_quarters_never_change() -> None:
    cells, _ = solve(eps_case("4.00", ("1.00", "1.00", "1.00")))

    for period in ("FY2023", "FY2023Q1", "FY2023Q2", "FY2023Q3"):
        assert cells[("eps_diluted", period)].provenance == "reported"
        assert cells[("shares_diluted", period)].provenance == "reported"
