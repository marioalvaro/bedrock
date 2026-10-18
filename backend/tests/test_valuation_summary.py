"""valuation_summary: own-history range and percentile of the current multiple (FR-ANL-07)."""

from datetime import date
from decimal import Decimal

from bedrock.analysis.multiples import MultipleSummary, valuation_summary
from bedrock.ratios.calculator import RatioRow, RatioTable
from bedrock.ratios.registry import RATIOS
from bedrock.statements.periods import Period

D = Decimal
VALUATION = [r for r in RATIOS if r.category == "Valuation"]


def period(year: int) -> Period:
    return Period(f"FY{year}", f"FY{year}", year, "FY", date(year - 1, 1, 1), date(year, 1, 1))


def table(freq: str, per_code: dict[str, list[int | str | None]], n: int) -> RatioTable:
    rows = [
        RatioRow(
            code=r.code,
            label=r.label,
            category=r.category,
            unit=r.unit,
            definition=r.definition,
            caveat="careful" if r.code == "ev_sales" else None,
            values=[None if v is None else D(v) for v in per_code.get(r.code, [None] * n)],
        )
        for r in RATIOS
    ]
    return RatioTable(freq=freq, periods=[period(2020 + i) for i in range(n)], rows=rows)  # type: ignore[arg-type]


def summary(code: str, history: list[int | str | None], current: int | None) -> MultipleSummary:
    annual = table("annual", {code: history}, len(history))
    now = table("ttm", {code: [current]}, 1)
    return next(s for s in valuation_summary(annual, now) if s.code == code)


def test_one_summary_per_valuation_ratio_in_registry_order() -> None:
    result = valuation_summary(table("annual", {}, 1), table("ttm", {}, 1))
    assert [s.code for s in result] == [r.code for r in VALUATION]


def test_range_median_and_percentile() -> None:
    s = summary("pe", [10, 20, 30, 40], 25)
    assert (s.current, s.min, s.median, s.max, s.n) == (D(25), D(10), D(25), D(40), 4)
    assert s.percentile == D("0.5")  # 10 and 20 are <= 25 -> 2 of 4


def test_percentile_counts_equal_values_and_spans_zero_to_one() -> None:
    assert summary("pe", [10, 20, 30], 30).percentile == D(1)
    assert summary("pe", [10, 20, 30], 5).percentile == D(0)


def test_negative_and_null_values_are_left_out_of_the_range() -> None:
    s = summary("pe", [None, -5, 10, 20, 30], 20)
    assert (s.min, s.max, s.n) == (D(10), D(30), 3)


def test_fewer_than_three_values_give_no_range_but_keep_the_current() -> None:
    s = summary("pe", [10, 20], 15)
    assert s.current == D(15)
    assert (s.min, s.median, s.max, s.percentile) == (None, None, None, None)
    assert s.n == 2


def test_a_null_current_has_no_percentile_but_keeps_the_range() -> None:
    s = summary("pe", [10, 20, 30], None)
    assert (s.current, s.percentile) == (None, None)
    assert s.min == D(10)


def test_unit_label_and_caveat_come_from_the_ratio_rows() -> None:
    s = summary("ev_sales", [1, 2, 3], 2)
    assert (s.label, s.unit, s.caveat) == ("EV/Sales", "x", "careful")
    assert summary("fcf_yield", [1, 2, 3], 2).unit == "pct"
