"""The annual figure of a year built from quarters (FR-FCST-13; docs/erd/forecasting.md "Year
modes" → Roll-up): each driver's history rule run on the forecast statements."""

from decimal import Decimal

import pytest

from bedrock.forecast.drivers import segment_code
from bedrock.forecast.engines.driver import (
    FORECAST_HORIZON,
    DriverModel,
    ForecastStatements,
    Opening,
    forecast_quarters,
)
from bedrock.forecast.history import (
    Default,
    ForecastHistory,
    ScenarioSettings,
    SeriesHistory,
    default_drivers,
    forecast_years,
    scenario_drivers,
)
from bedrock.forecast.resolve import DriverRow, ResolvedDrivers, resolve_drivers
from bedrock.forecast.rollup import rollup
from bedrock.statements.fiscal_grid import period_dates
from bedrock.statements.periods import Period
from tests.forecast_data import FYE, fixture_history, make_history

D = Decimal
GROWTH = ScenarioSettings("growth")


def _year(fiscal_year: int) -> Period:
    start, end = period_dates(FYE, fiscal_year, "FY")
    return Period(f"FY{fiscal_year}", f"FY{fiscal_year % 100:02d}", fiscal_year, "FY", start, end)


def _statements(values: dict[tuple[str, int], int | None]) -> ForecastStatements:
    years = sorted({y for _, y in values})
    opening = Opening(_year(years[0] - 1), {}, {})
    return ForecastStatements(
        tuple(_year(y) for y in years),
        {(code, f"FY{y}"): None if v is None else D(v) for (code, y), v in values.items()},
        (),
        opening,
        frozenset(),
    )


def _resolved(
    rows: list[DriverRow],
    defaults: dict[str, Default],
    years: list[int],
    history: ForecastHistory | None = None,
    settings: ScenarioSettings = GROWTH,
) -> ResolvedDrivers:
    """A resolution of every driver of the scenario: `defaults` where given, else 0."""
    every = {d.code: D(0) for d in scenario_drivers(history or HISTORY, settings)}
    return resolve_drivers([], rows, {**every, **defaults}, years, True)


HISTORY = make_history(
    {
        2025: {
            "revenue": 1000,
            "gross_profit": 400,
            "receivables": 100,
            "cost_of_revenue": 600,
            "shares_diluted": 100,
            "total_debt": 200,
            "pretax_income": 100,
            "income_tax": 20,
        }
    }
)
FORECAST = _statements(
    {
        ("revenue", 2026): 1100,
        ("gross_profit", 2026): 495,
        ("receivables", 2026): 150,
        ("cost_of_revenue", 2026): 605,
        ("shares_diluted", 2026): 105,
        ("total_debt", 2026): 300,
        ("interest_expense", 2026): 20,
        ("debt_issued", 2026): 40,
        ("pretax_income", 2026): 200,
        ("income_tax", 2026): 30,
    }
)


def _figures(statements: ForecastStatements = FORECAST) -> dict[tuple[str, int], Decimal | None]:
    return rollup(HISTORY, GROWTH, statements, _resolved([], {}, [2026]), [2026])


def test_ratio_growth_and_share_figures_are_the_history_rules_on_the_forecast_year() -> None:
    figures = _figures()

    assert figures[("revenue_growth", 2026)] == D("0.1")  # 1100 / 1000 - 1
    assert figures[("gross_margin", 2026)] == D("0.45")  # 495 / 1100
    assert figures[("share_change", 2026)] == D("0.05")  # 105 / 100 - 1
    assert figures[("tax_rate", 2026)] == D("0.15")  # 30 / 200


def test_the_interest_rate_runs_on_the_mean_of_the_year_s_opening_and_closing_debt() -> None:
    assert _figures()[("interest_rate", 2026)] == D("0.08")  # 20 / ((200 + 300) / 2)


def test_days_use_the_days_of_the_year() -> None:
    assert _figures()[("receivable_days", 2026)] == D(150) / D(1100) * 365


def test_an_amount_is_the_year_s_cash_flow_line() -> None:
    assert _figures()[("debt_issued", 2026)] == D(40)


def test_a_figure_with_a_missing_input_is_none() -> None:
    figures = _figures()

    assert figures[("inventory_days", 2026)] is None  # no inventory in the forecast
    assert figures[("sga_pct_revenue", 2026)] is None


def test_a_year_the_statements_do_not_cover_has_no_figures() -> None:
    figures = rollup(HISTORY, GROWTH, FORECAST, _resolved([], {}, [2026]), [2026, 2027])

    assert {y for _, y in figures} == {2026}


def test_min_cash_is_the_floor_of_the_year_s_last_quarter() -> None:
    rows = [
        DriverRow("min_cash", 2026, "value", D(100)),
        DriverRow("min_cash", 2026, "value", D(900), "Q4"),
    ]
    resolved = _resolved(rows, {"min_cash": D(0)}, [2026])

    assert rollup(HISTORY, GROWTH, FORECAST, resolved, [2026])[("min_cash", 2026)] == D(900)


SEGMENTS = ScenarioSettings("segments", "business")
CLOUD = SeriesHistory(1, "business", "Cloud", "revenue", "USD", {2025: D(600)})
SEGMENT_HISTORY = make_history({2025: {"revenue": 1000}}, series=[CLOUD])


def _segment_figure(rows: list[DriverRow]) -> Decimal | None:
    code = segment_code(1)
    resolved = _resolved(
        [DriverRow(code, 2026, "value", D("0.1")), *rows],
        {code: D("0.05")},
        [2026],
        SEGMENT_HISTORY,
        SEGMENTS,
    )
    statements = _statements({("revenue", 2026): 1100})
    return rollup(SEGMENT_HISTORY, SEGMENTS, statements, resolved, [2026])[(code, 2026)]


def test_a_segment_growth_is_the_year_s_driver_while_its_quarters_agree_with_it() -> None:
    assert _segment_figure([]) == D("0.1")


def test_a_segment_growth_whose_quarters_differ_has_no_annual_figure() -> None:
    assert _segment_figure([DriverRow(segment_code(1), 2026, "value", D("0.2"), "Q2")]) is None


# -- on the recorded companies ---------------------------------------------------------------

TICKERS = ["AAPL", "MSFT", "COST", "DE"]


@pytest.mark.parametrize("ticker", TICKERS)
def test_with_no_quarter_driver_a_whole_forecast_year_rolls_up_to_its_annual_driver(
    ticker: str,
) -> None:
    h = fixture_history(ticker)
    years = forecast_years(h, FORECAST_HORIZON.years)
    base = (
        [DriverRow("gross_margin", y, "value", D("0.25")) for y in years] if ticker == "DE" else []
    )
    defaults = default_drivers(h, GROWTH)
    resolved = resolve_drivers(base, base, defaults, years, True)
    statements = DriverModel().run(h, resolved, FORECAST_HORIZON, GROWTH)
    span = sorted({y for y, _ in forecast_quarters(h)})
    whole = span[1]  # a year after one built from quarters: its previous year is a forecast too

    figures = rollup(h, GROWTH, statements, resolved, [whole])

    for code in ("revenue_growth", "tax_rate", "sga_pct_revenue"):
        annual = resolved.get(code, whole).value
        assert isinstance(annual, Decimal)
        assert figures[(code, whole)] == pytest.approx(annual, abs=D("1e-9")), code
