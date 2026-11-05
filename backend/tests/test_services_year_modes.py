"""Year modes of a scenario (FR-FCST-13; docs/erd/forecasting.md "Year modes"), on the recorded
AAPL fixtures: the modes of the forecast years, the switch with its fill and clear across the three
cases, the write rules of a driver PUT and a case reset."""

from collections.abc import Iterator
from datetime import UTC, datetime
from decimal import Decimal

import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session

from bedrock.forecast.drivers import QUARTERS
from bedrock.forecast.engines.driver import FORECAST_HORIZON, forecast_quarters
from bedrock.forecast.errors import ForecastUnavailable
from bedrock.forecast.history import forecast_years
from bedrock.models.company import Company
from bedrock.models.driver_value import DriverValue
from bedrock.models.scenario import Scenario, ScenarioCase
from bedrock.repositories import scenarios as repo
from bedrock.services import forecasts as forecasts_service
from bedrock.services.errors import InvalidDrivers, InvalidScenario, ScenarioNotFound
from bedrock.services.refresh import refresh_company
from bedrock.services.scenarios import (
    DriverRowInput,
    SettingsInput,
    create_scenario,
    delete_scenario,
    driver_grid,
    list_scenarios,
    load_history,
    put_drivers,
    reset_case,
    set_year_mode,
    year_modes,
)

from .seed import fake_sources, follow

NOW = datetime(2026, 11, 3, 9, 0, tzinfo=UTC)
D = Decimal


@pytest.fixture
def aapl(db_session: Session) -> Iterator[Company]:
    sources = fake_sources()
    company = follow(db_session, sources.edgar, "AAPL")
    refresh_company(db_session, sources, "AAPL", NOW)
    yield company


@pytest.fixture
def empty(db_session: Session) -> Company:
    return follow(db_session, fake_sources().edgar, "MSFT")


def _main(session: Session, company: Company) -> Scenario:
    return list_scenarios(session, company, NOW)[0]


def _years(session: Session, company: Company) -> tuple[list[int], list[int]]:
    """(the forecast years, the years of the quarterly span)."""
    history = load_history(session, company)
    return (
        forecast_years(history, FORECAST_HORIZON.years),
        sorted({y for y, _ in forecast_quarters(history)}),
    )


def _rows(
    session: Session, scenario: Scenario, case: str
) -> dict[tuple[str, int, str], tuple[str, Decimal]]:
    stmt = (
        select(DriverValue)
        .join(ScenarioCase, ScenarioCase.id == DriverValue.case_id)
        .where(ScenarioCase.scenario_id == scenario.id, ScenarioCase.case == case)
    )
    return {
        (r.driver_code, r.fiscal_year, r.fiscal_period): (r.kind, Decimal(str(r.value)))
        for r in session.execute(stmt).scalars()
    }


def _forecast_quarters(session: Session, company: Company, year: int) -> list[str]:
    return [q for y, q in forecast_quarters(load_history(session, company)) if y == year]


def _quarter_rows(
    session: Session, scenario: Scenario, case: str, year: int | None = None
) -> dict[tuple[str, int, str], tuple[str, Decimal]]:
    return {
        k: v
        for k, v in _rows(session, scenario, case).items()
        if k[2] != "FY" and (year is None or k[1] == year)
    }


def _numbers(session: Session, company: Company, scenario: Scenario) -> list[float]:
    """Every compared forecast value of the scenario's three cases, annual and quarterly."""
    found: list[float] = []
    for freq in ("annual", "quarterly"):
        comparison = forecasts_service.compare(session, company, scenario.id, freq, None)
        for case in comparison.cases:
            assert case.error is None
            found.extend(float(v) for vs in case.values.values() for v in vs if v is not None)
    return found


def _same_numbers(after: list[float], before: list[float]) -> None:
    """Equal up to the 10 decimals a stored driver keeps (`driver_value.value`)."""
    assert len(after) == len(before) > 0
    assert after == pytest.approx(before, rel=1e-8, abs=1e-6)


# --- the modes of the forecast years ----------------------------------------------------------


def test_every_forecast_year_is_annual_until_switched(db_session: Session, aapl: Company) -> None:
    main = _main(db_session, aapl)
    years, span = _years(db_session, aapl)

    modes = year_modes(db_session, aapl, main.id)

    assert [m.fiscal_year for m in modes] == years
    assert {m.mode for m in modes} == {"annual"}
    assert [m.in_span for m in modes] == [y in span for y in years]
    assert modes[0].label == f"FY{years[0] % 100:02d}E"
    assert not modes[-1].in_span  # the last years have no quarters


def test_modes_of_an_unknown_scenario_are_not_found(db_session: Session, aapl: Company) -> None:
    with pytest.raises(ScenarioNotFound):
        year_modes(db_session, aapl, 999)


# --- switching to by quarter ----------------------------------------------------------------


def test_switching_a_year_to_quarterly_fills_base_and_the_drivers_bull_and_bear_override(
    db_session: Session, aapl: Company
) -> None:
    main = _main(db_session, aapl)
    _, span = _years(db_session, aapl)
    year = span[1]

    modes = set_year_mode(db_session, aapl, main.id, year, "quarterly", NOW)

    assert {m.fiscal_year: m.mode for m in modes}[year] == "quarterly"
    assert {m.mode for m in modes if m.fiscal_year != year} == {"annual"}
    base = _quarter_rows(db_session, main, "base", year)
    assert {k[2] for k in base} == set(QUARTERS)
    assert {v[0] for v in base.values()} == {"value"}
    assert ("gross_margin", year, "Q1") in base
    for case, sign in (("bull", 1), ("bear", -1)):
        rows = _quarter_rows(db_session, main, case, year)
        assert {k[0] for k in rows} == {"revenue_growth", "gross_margin"}  # the default offsets
        assert rows[("revenue_growth", year, "Q3")] == ("offset", sign * D("0.03"))
    assert _quarter_rows(db_session, main, "base") == base  # no other year


def test_switching_to_quarterly_changes_no_forecast_number(
    db_session: Session, aapl: Company
) -> None:
    main = _main(db_session, aapl)
    _, span = _years(db_session, aapl)
    before = _numbers(db_session, aapl, main)

    for year in span:
        set_year_mode(db_session, aapl, main.id, year, "quarterly", NOW)

    _same_numbers(_numbers(db_session, aapl, main), before)


def test_switching_to_quarterly_twice_is_the_same_as_once(
    db_session: Session, aapl: Company
) -> None:
    main = _main(db_session, aapl)
    _, span = _years(db_session, aapl)
    set_year_mode(db_session, aapl, main.id, span[0], "quarterly", NOW)
    once = {c: _rows(db_session, main, c) for c in ("base", "bull", "bear")}

    set_year_mode(db_session, aapl, main.id, span[0], "quarterly", NOW)

    assert {c: _rows(db_session, main, c) for c in ("base", "bull", "bear")} == once


def test_a_value_the_user_set_in_a_quarter_survives_a_second_switch(
    db_session: Session, aapl: Company
) -> None:
    main = _main(db_session, aapl)
    _, span = _years(db_session, aapl)
    year = span[1]
    set_year_mode(db_session, aapl, main.id, year, "quarterly", NOW)
    all_quarters = [(year, q, D("0.5") if q == "Q2" else D("0.4")) for q in QUARTERS]
    put_drivers(
        db_session,
        aapl,
        main.id,
        "base",
        [DriverRowInput("gross_margin", "value", freq="quarterly", quarters=all_quarters)],
        NOW,
    )

    set_year_mode(db_session, aapl, main.id, year, "quarterly", NOW)

    assert _rows(db_session, main, "base")[("gross_margin", year, "Q2")] == ("value", D("0.5"))


def test_a_year_in_progress_is_filled_for_its_forecast_quarters_only(
    db_session: Session, aapl: Company
) -> None:
    main = _main(db_session, aapl)
    _, span = _years(db_session, aapl)
    year = span[0]
    forecast = _forecast_quarters(db_session, aapl, year)
    assert len(forecast) < 4  # AAPL's opening is inside this year

    set_year_mode(db_session, aapl, main.id, year, "quarterly", NOW)

    assert {k[2] for k in _quarter_rows(db_session, main, "base", year)} == set(forecast)


# --- switching back to annual -------------------------------------------------------------------


def test_switching_back_deletes_the_year_s_quarter_rows_in_the_three_cases_only(
    db_session: Session, aapl: Company
) -> None:
    main = _main(db_session, aapl)
    _, span = _years(db_session, aapl)
    first, second = span[0], span[1]
    for year in (first, second):
        set_year_mode(db_session, aapl, main.id, year, "quarterly", NOW)
    annual = {
        c: {k: v for k, v in _rows(db_session, main, c).items() if k[2] == "FY"}
        for c in ("base", "bull", "bear")
    }

    modes = set_year_mode(db_session, aapl, main.id, first, "annual", NOW)

    assert {m.fiscal_year: m.mode for m in modes}[first] == "annual"
    assert {m.fiscal_year: m.mode for m in modes}[second] == "quarterly"
    for case in ("base", "bull", "bear"):
        assert _quarter_rows(db_session, main, case, first) == {}
        assert _quarter_rows(db_session, main, case, second) != {}
        now = {k: v for k, v in _rows(db_session, main, case).items() if k[2] == "FY"}
        assert now == annual[case]  # the annual rows return as they were


def test_a_year_that_was_never_switched_can_be_switched_to_annual_as_a_no_op(
    db_session: Session, aapl: Company
) -> None:
    main = _main(db_session, aapl)
    _, span = _years(db_session, aapl)
    before = {c: _rows(db_session, main, c) for c in ("base", "bull", "bear")}

    set_year_mode(db_session, aapl, main.id, span[0], "annual", NOW)

    assert {c: _rows(db_session, main, c) for c in ("base", "bull", "bear")} == before


# --- refusals ---------------------------------------------------------------------------------


def test_a_year_after_the_quarterly_span_cannot_be_switched(
    db_session: Session, aapl: Company
) -> None:
    main = _main(db_session, aapl)
    years, span = _years(db_session, aapl)
    after = next(y for y in years if y not in span)

    with pytest.raises(InvalidScenario, match=f"FY{after} is not in the quarterly span"):
        set_year_mode(db_session, aapl, main.id, after, "quarterly", NOW)
    assert _quarter_rows(db_session, main, "base") == {}


def test_a_year_outside_the_forecast_years_and_an_unknown_mode_are_refused(
    db_session: Session, aapl: Company
) -> None:
    main = _main(db_session, aapl)
    _, span = _years(db_session, aapl)

    with pytest.raises(InvalidScenario, match="FY1999 is not a forecast year"):
        set_year_mode(db_session, aapl, main.id, 1999, "quarterly", NOW)
    with pytest.raises(InvalidScenario, match="mode must be annual or quarterly"):
        set_year_mode(db_session, aapl, main.id, span[0], "weekly", NOW)
    with pytest.raises(ScenarioNotFound):
        set_year_mode(db_session, aapl, 999, span[0], "quarterly", NOW)


def test_a_company_without_data_cannot_be_switched(db_session: Session, empty: Company) -> None:
    main = _main(db_session, empty)

    with pytest.raises(ForecastUnavailable):
        set_year_mode(db_session, empty, main.id, 2027, "quarterly", NOW)


def test_the_mode_belongs_to_its_scenario(db_session: Session, aapl: Company) -> None:
    main = _main(db_session, aapl)
    other = create_scenario(db_session, aapl, SettingsInput(name="Other"), NOW)
    _, span = _years(db_session, aapl)

    set_year_mode(db_session, aapl, main.id, span[0], "quarterly", NOW)

    assert {m.mode for m in year_modes(db_session, aapl, other.id)} == {"annual"}
    assert _quarter_rows(db_session, other, "base") == {}


def test_deleting_a_scenario_deletes_its_modes(db_session: Session, aapl: Company) -> None:
    other = create_scenario(db_session, aapl, SettingsInput(name="Other"), NOW)
    _, span = _years(db_session, aapl)
    set_year_mode(db_session, aapl, other.id, span[0], "quarterly", NOW)

    delete_scenario(db_session, aapl, other.id)

    from bedrock.models.scenario import ScenarioYearMode

    assert db_session.query(ScenarioYearMode).count() == 0


# --- write rules of a driver PUT ------------------------------------------------------------------


def _quarters(
    session: Session, company: Company, year: int, value: str | None
) -> list[tuple[int, str, Decimal | None]]:
    """The year's forecast quarters, all at `value`."""
    return [
        (year, q, None if value is None else D(value))
        for q in _forecast_quarters(session, company, year)
    ]


def test_a_quarter_value_in_an_annual_year_is_refused(db_session: Session, aapl: Company) -> None:
    main = _main(db_session, aapl)
    _, span = _years(db_session, aapl)
    quarters = _quarters(db_session, aapl, span[1], "0.2")
    row = DriverRowInput("tax_rate", "value", freq="quarterly", quarters=quarters)

    with pytest.raises(InvalidDrivers, match=f"FY{span[1]} is set annually"):
        put_drivers(db_session, aapl, main.id, "base", [row], NOW)
    assert _quarter_rows(db_session, main, "base") == {}


def test_a_quarterly_row_with_no_value_for_an_annual_year_is_a_no_op(
    db_session: Session, aapl: Company
) -> None:
    main = _main(db_session, aapl)
    _, span = _years(db_session, aapl)
    quarters = _quarters(db_session, aapl, span[1], None)
    row = DriverRowInput("tax_rate", "value", freq="quarterly", quarters=quarters)

    put_drivers(db_session, aapl, main.id, "base", [row], NOW)

    assert _quarter_rows(db_session, main, "base") == {}


def test_an_annual_value_in_a_quarterly_year_is_refused(db_session: Session, aapl: Company) -> None:
    main = _main(db_session, aapl)
    _, span = _years(db_session, aapl)
    set_year_mode(db_session, aapl, main.id, span[0], "quarterly", NOW)

    with pytest.raises(InvalidDrivers, match=f"FY{span[0]} is set by quarter"):
        put_drivers(
            db_session,
            aapl,
            main.id,
            "base",
            [DriverRowInput("tax_rate", "value", [(span[0], D("0.2"))])],
            NOW,
        )


def _quarter_cells(
    session: Session, company: Company, scenario: Scenario, case: str, code: str, year: int
) -> dict[str, tuple[Decimal | None, str | None]]:
    """(value, source) of each forecast quarter of `year` of `code` in the quarterly grid."""
    grid = driver_grid(session, company, scenario.id, case, "quarterly")
    row = next(r for r in grid.rows if r.code == code)
    return {
        p.fiscal_period: (row.values[i], row.sources[i])
        for i, p in enumerate(grid.forecast_periods)
        if p.fiscal_year == year
    }


def test_a_quarterly_row_may_set_some_quarters_and_the_others_take_the_default(
    db_session: Session, aapl: Company
) -> None:
    """A quarter with no row of a year set by quarter does not fall back to the year's hidden
    annual value: a cleared or left-out quarter takes the default."""
    main = _main(db_session, aapl)
    _, span = _years(db_session, aapl)
    year = span[1]
    put_drivers(
        db_session,
        aapl,
        main.id,
        "base",
        [DriverRowInput("tax_rate", "value", [(year, D("0.31"))])],
        NOW,
    )
    set_year_mode(db_session, aapl, main.id, year, "quarterly", NOW)
    quarters = _forecast_quarters(db_session, aapl, year)

    put_drivers(
        db_session,
        aapl,
        main.id,
        "base",
        [
            DriverRowInput(
                "tax_rate",
                "value",
                freq="quarterly",
                quarters=[(year, quarters[0], D("0.2")), (year, quarters[1], None)],
            )
        ],
        NOW,
    )

    assert {k[2] for k in _quarter_rows(db_session, main, "base", year) if k[0] == "tax_rate"} == {
        quarters[0]
    }
    cells = _quarter_cells(db_session, aapl, main, "base", "tax_rate", year)
    assert cells[quarters[0]] == (D("0.2"), "own")
    assert all(cells[q][1] == "default" and cells[q][0] != D("0.31") for q in quarters[1:])


def test_editing_one_quarter_in_bull_keeps_the_other_quarters_following_base(
    db_session: Session, aapl: Company
) -> None:
    main = _main(db_session, aapl)
    _, span = _years(db_session, aapl)
    year = span[1]
    set_year_mode(db_session, aapl, main.id, year, "quarterly", NOW)
    quarters = _forecast_quarters(db_session, aapl, year)

    put_drivers(
        db_session,
        aapl,
        main.id,
        "bull",
        [
            DriverRowInput(
                "tax_rate", "value", freq="quarterly", quarters=[(year, quarters[0], D("0.2"))]
            )
        ],
        NOW,
    )

    cells = _quarter_cells(db_session, aapl, main, "bull", "tax_rate", year)
    assert cells[quarters[0]] == (D("0.2"), "own")
    base = _quarter_cells(db_session, aapl, main, "base", "tax_rate", year)
    assert all(cells[q] == (base[q][0], "base") for q in quarters[1:])


def test_switching_a_year_already_set_by_quarter_again_writes_nothing(
    db_session: Session, aapl: Company
) -> None:
    main = _main(db_session, aapl)
    _, span = _years(db_session, aapl)
    year = span[1]
    set_year_mode(db_session, aapl, main.id, year, "quarterly", NOW)
    put_drivers(
        db_session,
        aapl,
        main.id,
        "base",
        [DriverRowInput("tax_rate", "value", freq="quarterly", quarters=[])],
        NOW,
    )
    before = _rows(db_session, main, "base")

    set_year_mode(db_session, aapl, main.id, year, "quarterly", NOW)

    assert _rows(db_session, main, "base") == before


def test_a_full_quarterly_row_of_a_quarterly_year_replaces_its_quarters(
    db_session: Session, aapl: Company
) -> None:
    main = _main(db_session, aapl)
    _, span = _years(db_session, aapl)
    year = span[1]
    set_year_mode(db_session, aapl, main.id, year, "quarterly", NOW)
    values = ("0.18", "0.19", "0.2", "0.21")
    quarters = [(year, q, D(v)) for q, v in zip(QUARTERS, values, strict=True)]

    put_drivers(
        db_session,
        aapl,
        main.id,
        "base",
        [DriverRowInput("tax_rate", "value", freq="quarterly", quarters=quarters)],
        NOW,
    )

    rows = _rows(db_session, main, "base")
    assert [rows[("tax_rate", year, q)][1] for q in QUARTERS] == [D(v) for v in values]


def test_an_annual_row_leaves_the_stored_annual_value_of_a_quarterly_year_alone(
    db_session: Session, aapl: Company
) -> None:
    main = _main(db_session, aapl)
    _, span = _years(db_session, aapl)
    hidden, other = span[0], span[1]
    put_drivers(
        db_session,
        aapl,
        main.id,
        "base",
        [DriverRowInput("tax_rate", "value", [(hidden, D("0.15")), (other, D("0.16"))])],
        NOW,
    )
    set_year_mode(db_session, aapl, main.id, hidden, "quarterly", NOW)

    put_drivers(
        db_session,
        aapl,
        main.id,
        "base",
        [DriverRowInput("tax_rate", "value", [(other, D("0.17"))])],
        NOW,
    )

    rows = _rows(db_session, main, "base")
    assert rows[("tax_rate", hidden, "FY")] == ("value", D("0.15"))  # still stored, not shown
    assert rows[("tax_rate", other, "FY")] == ("value", D("0.17"))


def test_a_new_kind_for_the_annual_rows_drops_the_quarters_of_a_year_set_by_quarter(
    db_session: Session, aapl: Company
) -> None:
    """Changing a driver between value and offset starts it over: its quarters of a year set by
    quarter go too, and those quarters then follow Base."""
    main = _main(db_session, aapl)
    _, span = _years(db_session, aapl)
    year = span[1]
    set_year_mode(db_session, aapl, main.id, year, "quarterly", NOW)
    assert any(k[0] == "gross_margin" for k in _quarter_rows(db_session, main, "bull", year))

    put_drivers(
        db_session,
        aapl,
        main.id,
        "bull",
        [DriverRowInput("gross_margin", "value", [(span[2], D("0.5"))])],
        NOW,
    )

    assert not any(k[0] == "gross_margin" for k in _quarter_rows(db_session, main, "bull", year))
    cells = _quarter_cells(db_session, aapl, main, "bull", "gross_margin", year)
    assert {source for _, source in cells.values()} == {"base"}


# --- reset ----------------------------------------------------------------------------------------


def test_resetting_a_case_keeps_the_quarters_of_its_quarterly_years_filled(
    db_session: Session, aapl: Company
) -> None:
    main = _main(db_session, aapl)
    _, span = _years(db_session, aapl)
    year = span[1]
    set_year_mode(db_session, aapl, main.id, year, "quarterly", NOW)
    before = _numbers(db_session, aapl, main)

    for case in ("base", "bull", "bear"):
        reset_case(db_session, aapl, main.id, case, NOW)

    assert {k[2] for k in _quarter_rows(db_session, main, "bull", year)} == set(QUARTERS)
    assert {k[2] for k in _quarter_rows(db_session, main, "base", year)} == set(QUARTERS)
    _same_numbers(_numbers(db_session, aapl, main), before)  # the defaults the fill started from


def test_a_stored_mode_for_a_year_after_the_span_is_annual_for_every_write(
    db_session: Session, aapl: Company
) -> None:
    """A `quarterly` row left for a year the quarterly span no longer covers reads as annual in
    the grid; the PUT and the reset treat it the same way (one definition of the modes)."""
    main = _main(db_session, aapl)
    years, span = _years(db_session, aapl)
    after = next(y for y in years if y not in span)
    repo.set_quarterly(db_session, main.id, after, True)
    db_session.commit()
    assert {m.fiscal_year: m.mode for m in year_modes(db_session, aapl, main.id)}[after] == "annual"

    put_drivers(
        db_session,
        aapl,
        main.id,
        "base",
        [DriverRowInput("tax_rate", "value", [(after, D("0.2"))])],
        NOW,
    )
    assert _rows(db_session, main, "base")[("tax_rate", after, "FY")] == ("value", D("0.2"))

    reset_case(db_session, aapl, main.id, "base", NOW)
    assert _quarter_rows(db_session, main, "base", after) == {}
