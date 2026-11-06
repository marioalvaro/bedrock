"""Scenarios of a followed company and their cases (docs/erd/forecasting.md "Scenarios and
cases"), on the recorded AAPL fixtures: the default "Main", CRUD, settings validation, reset, the
driver grid and its PUT per case."""

from collections.abc import Callable
from dataclasses import replace
from datetime import UTC, datetime
from decimal import Decimal

import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session

from bedrock.forecast.drivers import drivers_for
from bedrock.forecast.errors import ForecastUnavailable
from bedrock.forecast.history import (
    ForecastHistory,
    ScenarioSettings,
    default_drivers,
    forecast_years,
    history_years,
)
from bedrock.models.company import Company
from bedrock.models.driver_value import DriverValue
from bedrock.models.scenario import Scenario, ScenarioCase
from bedrock.models.segment_series import SegmentSeries
from bedrock.models.segment_value import SegmentValue
from bedrock.repositories import companies as companies_repo
from bedrock.repositories import scenarios as scenarios_repo
from bedrock.services import scenarios as scenarios_service
from bedrock.services.errors import (
    InvalidDrivers,
    InvalidScenario,
    ScenarioConflict,
    ScenarioNotFound,
)
from bedrock.services.scenarios import (
    DriverGrid,
    DriverRowInput,
    GridRow,
    SettingsInput,
    create_scenario,
    delete_scenario,
    driver_grid,
    ensure_defaults,
    export_drivers,
    import_drivers,
    list_scenarios,
    load_history,
    put_drivers,
    reset_case,
    set_year_mode,
    update_scenario,
)
from tests.forecast_data import choose_engines

from .seed import fake_sources, follow

NOW = datetime(2026, 10, 31, 9, 0, tzinfo=UTC)
D = Decimal


@pytest.fixture
def aapl_db(seed_db: Callable[..., None]) -> None:
    seed_db("AAPL")


@pytest.fixture
def aapl(aapl_db: None, db_session: Session) -> Company:
    company = companies_repo.get_by_ticker(db_session, "AAPL")
    assert company is not None
    return company


@pytest.fixture
def empty(db_session: Session) -> Company:
    """A followed company with no data: no opening balance sheet."""
    return follow(db_session, fake_sources().edgar, "MSFT")


def _rows(
    session: Session, scenario: Scenario, case: str = "base"
) -> dict[tuple[str, int], tuple[str, Decimal]]:
    stmt = (
        select(DriverValue)
        .join(ScenarioCase, ScenarioCase.id == DriverValue.case_id)
        .where(ScenarioCase.scenario_id == scenario.id, ScenarioCase.case == case)
    )
    return {
        (r.driver_code, r.fiscal_year): (r.kind, Decimal(str(r.value)).normalize())
        for r in session.execute(stmt).scalars()
    }


def _main(session: Session, company: Company) -> Scenario:
    return list_scenarios(session, company, NOW)[0]


def _case_names(session: Session, scenario: Scenario) -> set[str]:
    return set(scenarios_repo.cases_of(session, scenario.id))


def _series(
    session: Session,
    company: Company,
    name: str,
    dimension: str = "business",
    metric: str = "revenue",
    unit: str = "USD",
    fy_values: dict[int, int] | None = None,
) -> SegmentSeries:
    series = SegmentSeries(
        company_id=company.id,
        dimension=dimension,
        name=name,
        metric=metric,
        unit=unit,
        display_order=0,
    )
    session.add(series)
    session.flush()
    for year, value in (fy_values or {}).items():
        session.add(
            SegmentValue(series_id=series.id, fiscal_year=year, fiscal_period="FY", value=value)
        )
    session.commit()
    return series


# --- defaults -------------------------------------------------------------------------------


def test_the_first_list_creates_main_with_three_cases_once(
    db_session: Session, aapl: Company
) -> None:
    first = list_scenarios(db_session, aapl, NOW)
    ensure_defaults(db_session, aapl, NOW)
    second = list_scenarios(db_session, aapl, NOW)

    assert [s.name for s in first] == ["Main"]
    assert [s.id for s in second] == [s.id for s in first]
    (main,) = first
    assert (main.is_default, main.revenue_method) == (True, "growth")
    assert main.created_at == datetime(2026, 10, 31, 9, 0)  # naive UTC from the clock
    assert _case_names(db_session, main) == {"base", "bull", "bear"}
    assert db_session.query(ScenarioCase).count() == 3


def test_bull_and_bear_hold_offsets_for_the_five_forecast_years_and_base_holds_none(
    db_session: Session, aapl: Company
) -> None:
    """The horizon is fixed at 5 years (user, 2026-10-31): no offset lies beyond it."""
    main = _main(db_session, aapl)
    years = forecast_years(load_history(db_session, aapl), 5)

    assert _rows(db_session, main, "base") == {}
    assert _rows(db_session, main, "bull") == {
        **{("revenue_growth", y): ("offset", D("0.03")) for y in years},
        **{("gross_margin", y): ("offset", D("0.01")) for y in years},
    }
    assert _rows(db_session, main, "bear") == {
        **{("revenue_growth", y): ("offset", D("-0.03")) for y in years},
        **{("gross_margin", y): ("offset", D("-0.01")) for y in years},
    }


def test_a_company_without_an_opening_gets_main_without_offsets(
    db_session: Session, empty: Company
) -> None:
    (main,) = list_scenarios(db_session, empty, NOW)

    assert _case_names(db_session, main) == {"base", "bull", "bear"}
    assert all(_rows(db_session, main, c) == {} for c in ("base", "bull", "bear"))


def test_scenarios_are_listed_default_first_then_by_id(db_session: Session, aapl: Company) -> None:
    list_scenarios(db_session, aapl, NOW)
    create_scenario(db_session, aapl, SettingsInput(name="Aardvark"), NOW)
    create_scenario(db_session, aapl, SettingsInput(name="Zebra"), NOW)

    assert [s.name for s in list_scenarios(db_session, aapl, NOW)] == ["Main", "Aardvark", "Zebra"]


# --- create, update, delete -----------------------------------------------------------------


def test_a_new_scenario_takes_the_default_s_settings_and_fresh_default_cases(
    db_session: Session, aapl: Company
) -> None:
    main = _main(db_session, aapl)
    _series(db_session, aapl, "Americas", dimension="geo")
    geo = SettingsInput(revenue_method="segments", segment_dimension="geo")
    update_scenario(db_session, aapl, main.id, geo, NOW)
    years = forecast_years(load_history(db_session, aapl), 5)
    y = years[0]
    _put(db_session, aapl, main, "base", DriverRowInput("tax_rate", "value", [(y, D("0.2"))]))

    created = create_scenario(db_session, aapl, SettingsInput(name="  Mine  "), NOW)

    assert created.name == "Mine"
    assert created.is_default is False
    assert (created.revenue_method, created.segment_dimension) == ("segments", "geo")
    assert _case_names(db_session, created) == {"base", "bull", "bear"}
    assert _rows(db_session, created, "base") == {}  # no copy of Main's edits
    assert _rows(db_session, created, "bull")[("revenue_growth", y)] == ("offset", D("0.03"))
    assert _rows(db_session, created, "bear")[("gross_margin", y)] == ("offset", D("-0.01"))


def test_a_scenario_created_on_segments_has_segment_offsets_by_case(
    db_session: Session, aapl: Company
) -> None:
    iphone = _series(db_session, aapl, "iPhone", fy_values={2024: 200})
    years = forecast_years(load_history(db_session, aapl), 5)
    segments = SettingsInput(name="Seg", revenue_method="segments", segment_dimension="business")

    created = create_scenario(db_session, aapl, segments, NOW)

    code = f"segment_growth:{iphone.id}"
    assert _rows(db_session, created, "base") == {}
    assert {k: v for k, v in _rows(db_session, created, "bull").items() if k[0] == code} == {
        (code, y): ("offset", D("0.03")) for y in years
    }
    assert {k: v for k, v in _rows(db_session, created, "bear").items() if k[0] == code} == {
        (code, y): ("offset", D("-0.03")) for y in years
    }


def test_a_duplicate_name_is_a_conflict_on_create_and_update(
    db_session: Session, aapl: Company
) -> None:
    main = _main(db_session, aapl)
    other = create_scenario(db_session, aapl, SettingsInput(name="Other"), NOW)

    with pytest.raises(ScenarioConflict, match="already has a scenario named 'Other'"):
        create_scenario(db_session, aapl, SettingsInput(name="Other"), NOW)
    with pytest.raises(ScenarioConflict):
        update_scenario(db_session, aapl, main.id, SettingsInput(name=" Other "), NOW)
    # its own name is not a duplicate
    assert update_scenario(db_session, aapl, other.id, SettingsInput(name="Other"), NOW).name == (
        "Other"
    )


@pytest.mark.parametrize(
    ("data", "message"),
    [
        (SettingsInput(name=""), "name must not be blank"),
        (SettingsInput(name="   "), "name must not be blank"),
        (SettingsInput(name="x" * 61), "at most 60 characters"),
        (SettingsInput(name="A", revenue_method="magic"), "revenue_method must be one of"),
        (SettingsInput(name="A", revenue_method="segments"), "needs a segment_dimension"),
        (
            SettingsInput(name="A", revenue_method="segments", segment_dimension="kpi"),
            "segment_dimension must be one of business, geo",
        ),
        (SettingsInput(name="A", revenue_method="volume_price"), "needs a volume_kpi"),
    ],
)
def test_invalid_settings_are_refused_and_nothing_is_stored(
    db_session: Session, aapl: Company, data: SettingsInput, message: str
) -> None:
    list_scenarios(db_session, aapl, NOW)

    with pytest.raises(InvalidScenario, match=message):
        create_scenario(db_session, aapl, data, NOW)
    assert len(list_scenarios(db_session, aapl, NOW)) == 1
    assert db_session.query(ScenarioCase).count() == 3
    assert db_session.query(DriverValue).filter_by(case_id=None).count() == 0


def test_a_sixty_character_name_is_accepted(db_session: Session, aapl: Company) -> None:
    created = create_scenario(db_session, aapl, SettingsInput(name="x" * 60), NOW)
    assert created.name == "x" * 60


def test_volume_and_price_must_be_kpis_of_the_company_with_their_units(
    db_session: Session, aapl: Company
) -> None:
    _series(db_session, aapl, "Units", dimension="kpi", metric="units", unit="count")
    _series(db_session, aapl, "ASP", dimension="kpi", metric="asp", unit="USD_per_unit")
    _series(db_session, aapl, "Margin", dimension="kpi", metric="margin", unit="pct")
    vp = {"revenue_method": "volume_price"}

    for volume, price, message in (
        ("asp", "asp", "volume_kpi 'asp' is not a KPI of AAPL with unit count"),
        ("units", "units", "price_kpi 'units' is not a KPI of AAPL with unit USD_per_unit"),
        ("nope", "asp", "volume_kpi 'nope' is not a KPI of AAPL"),
        ("units", None, "needs a price_kpi"),
        ("units", "margin", "price_kpi 'margin'"),
    ):
        with pytest.raises(InvalidScenario, match=message):
            create_scenario(
                db_session,
                aapl,
                SettingsInput(name="VP", volume_kpi=volume, price_kpi=price, **vp),  # type: ignore[arg-type]
                NOW,
            )
    created = create_scenario(
        db_session,
        aapl,
        SettingsInput(name="VP", volume_kpi="units", price_kpi="asp", **vp),  # type: ignore[arg-type]
        NOW,
    )
    assert (created.revenue_method, created.volume_kpi, created.price_kpi) == (
        "volume_price",
        "units",
        "asp",
    )


def test_an_update_keeps_the_settings_it_does_not_name(db_session: Session, aapl: Company) -> None:
    main = _main(db_session, aapl)

    updated = update_scenario(
        db_session,
        aapl,
        main.id,
        SettingsInput(revenue_method="segments", segment_dimension="geo"),
        NOW,
    )
    assert (updated.name, updated.revenue_method, updated.segment_dimension) == (
        "Main",
        "segments",
        "geo",
    )
    again = update_scenario(db_session, aapl, main.id, SettingsInput(name="Core"), NOW)

    assert (again.revenue_method, again.segment_dimension, again.name) == (
        "segments",
        "geo",
        "Core",
    )
    assert again.updated_at == datetime(2026, 10, 31, 9, 0)


def test_renaming_a_scenario_keeps_the_offsets_of_its_cases(
    db_session: Session, aapl: Company
) -> None:
    main = _main(db_session, aapl)
    before = {c: _rows(db_session, main, c) for c in ("base", "bull", "bear")}

    update_scenario(db_session, aapl, main.id, SettingsInput(name="Core"), NOW)

    assert {c: _rows(db_session, main, c) for c in ("base", "bull", "bear")} == before


def test_another_company_s_scenario_is_not_found(
    db_session: Session, aapl: Company, empty: Company
) -> None:
    other = _main(db_session, empty)
    list_scenarios(db_session, aapl, NOW)

    with pytest.raises(ScenarioNotFound):
        update_scenario(db_session, aapl, other.id, SettingsInput(name="X"), NOW)
    with pytest.raises(ScenarioNotFound):
        delete_scenario(db_session, aapl, other.id)
    with pytest.raises(ScenarioNotFound):
        delete_scenario(db_session, aapl, 999_999)
    with pytest.raises(ScenarioNotFound):
        reset_case(db_session, aapl, other.id, "bull", NOW)


def test_the_default_scenario_cannot_be_deleted(db_session: Session, aapl: Company) -> None:
    main = _main(db_session, aapl)

    with pytest.raises(ScenarioConflict, match="The default scenario cannot be deleted"):
        delete_scenario(db_session, aapl, main.id)


def test_deleting_a_scenario_deletes_its_cases_and_driver_rows(
    db_session: Session, aapl: Company
) -> None:
    main = _main(db_session, aapl)
    extra = create_scenario(db_session, aapl, SettingsInput(name="Extra"), NOW)
    kept = (
        db_session.query(DriverValue).count()
        - len(_rows(db_session, extra, "bull"))
        - len(_rows(db_session, extra, "bear"))
    )

    delete_scenario(db_session, aapl, extra.id)

    assert [s.name for s in list_scenarios(db_session, aapl, NOW)] == ["Main"]
    assert _case_names(db_session, extra) == set()
    assert db_session.query(ScenarioCase).count() == 3
    assert db_session.query(DriverValue).count() == kept
    assert _rows(db_session, main, "bull")  # Main's cases are untouched


# --- segments: default offsets ----------------------------------------------------------------


def test_bull_and_bear_switched_to_segments_get_an_offset_on_each_segment(
    db_session: Session, aapl: Company
) -> None:
    iphone = _series(db_session, aapl, "iPhone", fy_values={2024: 200})
    mac = _series(db_session, aapl, "Mac", fy_values={2024: 30})
    geo = _series(db_session, aapl, "Americas", dimension="geo")
    income = _series(db_session, aapl, "iPhone OI", metric="operating_income")
    main = _main(db_session, aapl)
    years = forecast_years(load_history(db_session, aapl), 5)
    before = {c: _rows(db_session, main, c) for c in ("base", "bull", "bear")}

    update_scenario(
        db_session,
        aapl,
        main.id,
        SettingsInput(revenue_method="segments", segment_dimension="business"),
        NOW,
    )

    assert _rows(db_session, main, "base") == {}
    for case, sign in (("bull", ""), ("bear", "-")):
        after = _rows(db_session, main, case)
        added = {k: v for k, v in after.items() if k not in before[case]}
        assert added == {
            (f"segment_growth:{s.id}", y): ("offset", D(f"{sign}0.03"))
            for s in (iphone, mac)
            for y in years
        }
        # the revenue_growth offsets stay, for a switch back to growth
        assert {k: v for k, v in after.items() if k in before[case]} == before[case]
        assert not any(code.endswith((str(geo.id), str(income.id))) for code, _ in added)


def test_a_segment_with_own_rows_keeps_them_and_a_later_segment_gets_none(
    db_session: Session, aapl: Company
) -> None:
    iphone = _series(db_session, aapl, "iPhone")
    main = _main(db_session, aapl)
    bull = scenarios_repo.cases_of(db_session, main.id)["bull"]
    first_year = forecast_years(load_history(db_session, aapl), 5)[0]
    db_session.add(
        DriverValue(
            case_id=bull.id,
            driver_code=f"segment_growth:{iphone.id}",
            fiscal_year=first_year,
            kind="value",
            value=D("0.2"),
        )
    )
    db_session.commit()
    mac = _series(db_session, aapl, "Mac")

    update_scenario(
        db_session,
        aapl,
        main.id,
        SettingsInput(revenue_method="segments", segment_dimension="business"),
        NOW,
    )
    later = _series(db_session, aapl, "Services")
    update_scenario(db_session, aapl, main.id, SettingsInput(name="Core"), NOW)

    rows = _rows(db_session, main, "bull")
    assert {k: v for k, v in rows.items() if k[0] == f"segment_growth:{iphone.id}"} == {
        (f"segment_growth:{iphone.id}", first_year): ("value", D("0.2"))
    }
    assert sum(1 for code, _ in rows if code == f"segment_growth:{mac.id}") == 5
    assert not any(code == f"segment_growth:{later.id}" for code, _ in rows)


def test_changing_the_dimension_writes_the_offsets_of_the_new_dimension(
    db_session: Session, aapl: Company
) -> None:
    _series(db_session, aapl, "iPhone")
    americas = _series(db_session, aapl, "Americas", dimension="geo")
    main = _main(db_session, aapl)
    to = SettingsInput(revenue_method="segments", segment_dimension="business")
    update_scenario(db_session, aapl, main.id, to, NOW)

    update_scenario(db_session, aapl, main.id, SettingsInput(segment_dimension="geo"), NOW)

    rows = _rows(db_session, main, "bear")
    assert sum(1 for code, _ in rows if code == f"segment_growth:{americas.id}") == 5
    assert all(
        v == ("offset", D("-0.03")) for (c, _), v in rows.items() if c.endswith(f":{americas.id}")
    )


def test_a_settings_change_applies_to_all_three_cases(db_session: Session, aapl: Company) -> None:
    iphone = _series(db_session, aapl, "iPhone", fy_values={2024: 200, 2025: 210})
    main = _main(db_session, aapl)
    update_scenario(
        db_session,
        aapl,
        main.id,
        SettingsInput(revenue_method="segments", segment_dimension="business"),
        NOW,
    )

    for case in ("base", "bull", "bear"):
        codes = [r.code for r in driver_grid(db_session, aapl, main.id, case).rows]
        assert f"segment_growth:{iphone.id}" in codes
        assert "revenue_growth" not in codes


def test_a_scenario_s_cases_are_independent_of_another_scenario(
    db_session: Session, aapl: Company
) -> None:
    main = _main(db_session, aapl)
    other = create_scenario(db_session, aapl, SettingsInput(name="Other"), NOW)
    y = driver_grid(db_session, aapl, main.id, "base").forecast_years[0]

    _put(db_session, aapl, main, "base", DriverRowInput("gross_margin", "value", [(y, D("0.4"))]))

    main_bull = _row(driver_grid(db_session, aapl, main.id, "bull"), "gross_margin")
    other_bull = _row(driver_grid(db_session, aapl, other.id, "bull"), "gross_margin")
    assert main_bull.values[0] == D("0.41")
    assert other_bull.values[0] != D("0.41")


# --- reset ------------------------------------------------------------------------------------


def test_reset_of_base_drops_its_rows_and_returns_the_grid(
    db_session: Session, aapl: Company
) -> None:
    main = _main(db_session, aapl)
    choose_engines(db_session, main.id, {"tax_rate": "mean"})  # asserts the M4 3-year mean
    y = driver_grid(db_session, aapl, main.id, "base").forecast_years[0]
    _put(db_session, aapl, main, "base", DriverRowInput("tax_rate", "value", [(y, D("0.2"))]))
    bull_before = _rows(db_session, main, "bull")

    grid = reset_case(db_session, aapl, main.id, "base", NOW)

    assert _rows(db_session, main, "base") == {}
    assert _rows(db_session, main, "bull") == bull_before  # the other cases are untouched
    assert (grid.scenario_id, grid.case) == (main.id, "base")
    assert _row(grid, "tax_rate").sources == ["default"] * 5


@pytest.mark.parametrize("case", ["bull", "bear"])
def test_reset_of_bull_or_bear_restores_exactly_the_defaults(
    db_session: Session, aapl: Company, case: str
) -> None:
    main = _main(db_session, aapl)
    defaults = _rows(db_session, main, case)
    y = driver_grid(db_session, aapl, main.id, case).forecast_years[0]
    _put(
        db_session,
        aapl,
        main,
        case,
        DriverRowInput("gross_margin", "value", [(y, D("0.5"))]),
        DriverRowInput("tax_rate", "offset", [(y, D("0.01"))]),
    )
    assert _rows(db_session, main, case) != defaults

    grid = reset_case(db_session, aapl, main.id, case, NOW)

    assert _rows(db_session, main, case) == defaults
    assert _row(grid, "gross_margin").kind == "offset"


def test_reset_after_a_revenue_build_switch_restores_the_segment_offsets(
    db_session: Session, aapl: Company
) -> None:
    iphone = _series(db_session, aapl, "iPhone", fy_values={2024: 200})
    main = _main(db_session, aapl)
    update_scenario(
        db_session,
        aapl,
        main.id,
        SettingsInput(revenue_method="segments", segment_dimension="business"),
        NOW,
    )
    years = forecast_years(load_history(db_session, aapl), 5)
    expected = _rows(db_session, main, "bear")
    _put(
        db_session, aapl, main, "bear", DriverRowInput("gross_margin", "value", [(years[0], D(1))])
    )

    reset_case(db_session, aapl, main.id, "bear", NOW)

    rows = _rows(db_session, main, "bear")
    assert rows == expected
    assert rows[(f"segment_growth:{iphone.id}", years[0])] == ("offset", D("-0.03"))


def test_reset_adds_the_segment_offsets_a_switch_left_out(
    db_session: Session, aapl: Company
) -> None:
    """A series added after the switch has no offset until the case is reset."""
    main = _main(db_session, aapl)
    update_scenario(
        db_session,
        aapl,
        main.id,
        SettingsInput(revenue_method="segments", segment_dimension="business"),
        NOW,
    )
    later = _series(db_session, aapl, "Services")
    assert not any(c == f"segment_growth:{later.id}" for c, _ in _rows(db_session, main, "bull"))

    reset_case(db_session, aapl, main.id, "bull", NOW)

    assert any(c == f"segment_growth:{later.id}" for c, _ in _rows(db_session, main, "bull"))


def test_reset_without_an_opening_balance_sheet_is_unavailable(
    db_session: Session, empty: Company
) -> None:
    main = _main(db_session, empty)

    with pytest.raises(ForecastUnavailable, match="No complete balance sheet"):
        reset_case(db_session, empty, main.id, "bull", NOW)


def test_a_scenario_deleted_between_the_lookup_and_its_cases_is_not_found(
    db_session: Session, aapl: Company
) -> None:
    main = _main(db_session, aapl)
    db_session.query(DriverValue).delete()
    db_session.query(ScenarioCase).delete()
    db_session.commit()

    with pytest.raises(ScenarioNotFound):
        driver_grid(db_session, aapl, main.id, "bull")


def test_an_unknown_case_is_refused(db_session: Session, aapl: Company) -> None:
    main = _main(db_session, aapl)

    with pytest.raises(InvalidScenario, match="case must be one of base, bull, bear"):
        driver_grid(db_session, aapl, main.id, "worst")
    with pytest.raises(InvalidScenario):
        reset_case(db_session, aapl, main.id, "worst", NOW)


# --- history ----------------------------------------------------------------------------------


def test_the_history_holds_the_statements_and_the_fy_values_of_each_series(
    db_session: Session, aapl: Company
) -> None:
    iphone = _series(db_session, aapl, "iPhone", fy_values={2023: 200, 2024: 201})
    db_session.add(
        SegmentValue(series_id=iphone.id, fiscal_year=2024, fiscal_period="Q1", value=60)
    )
    db_session.commit()

    history = load_history(db_session, aapl)

    assert set(history.annual) == set(history.quarterly) == {"IS", "BS", "CF"}
    assert history.latest_fy_end == history.annual["IS"].periods[-1].end
    (series,) = history.segment_series
    assert (series.id, series.dimension, series.name, series.metric, series.unit) == (
        iphone.id,
        "business",
        "iPhone",
        "revenue",
        "USD",
    )
    assert dict(series.fy_values) == {2023: D(200), 2024: D(201)}
    assert str(series.fy_values[2024]) == "201"  # plain, no Numeric padding (G15)
    assert dict(series.quarter_values) == {(2024, "Q1"): D(60)}  # as entered, apart from the FYs


def test_a_company_without_data_has_an_empty_history(db_session: Session, empty: Company) -> None:
    history = load_history(db_session, empty)

    assert history.latest_fy_end is None
    assert history.segment_series == ()


# --- driver grid ------------------------------------------------------------------------------


def _row(grid: DriverGrid, code: str) -> GridRow:
    return next(r for r in grid.rows if r.code == code)


def test_base_s_grid_shows_five_history_years_and_the_defaults(
    db_session: Session, aapl: Company
) -> None:
    main = _main(db_session, aapl)
    choose_engines(db_session, main.id, {"revenue_growth": "mean"})  # asserts the M4 3-year mean
    history = load_history(db_session, aapl)

    grid = driver_grid(db_session, aapl, main.id, "base")

    assert (grid.scenario_id, grid.case) == (main.id, "base")
    assert grid.history_years == history_years(history)
    assert len(grid.history_years) == 5
    assert grid.forecast_years == forecast_years(history, 5)
    assert [r.code for r in grid.rows] == [d.code for d in drivers_for("growth")]
    growth = _row(grid, "revenue_growth")
    assert (growth.label, growth.group, growth.unit, growth.kind) == (
        "Revenue growth",
        "Revenue",
        "pct",
        None,
    )
    assert all(v is not None for v in growth.history)
    assert growth.sources == ["default"] * 5
    assert growth.own == [None] * 5
    defaults = default_drivers(history, ScenarioSettings("growth"))
    assert growth.values == [defaults["revenue_growth"]] * 5
    # a policy driver has no history, and defaults to zero
    cash = _row(grid, "min_cash")
    assert cash.history == [None] * 5
    assert (cash.values, cash.sources) == ([D(0)] * 5, ["default"] * 5)
    assert grid.warnings == []


def test_bull_s_grid_shows_base_plus_its_offsets(db_session: Session, aapl: Company) -> None:
    main = _main(db_session, aapl)
    choose_engines(db_session, main.id, {"sga_pct_revenue": "mean"})  # asserts the M4 3-year mean
    base = driver_grid(db_session, aapl, main.id, "base")

    bull = driver_grid(db_session, aapl, main.id, "bull")

    assert bull.case == "bull"
    growth = _row(bull, "revenue_growth")
    assert growth.kind == "offset"
    assert growth.sources == ["offset"] * 5
    assert growth.own == [D("0.03")] * 5
    assert growth.values == [v + D("0.03") for v in _row(base, "revenue_growth").values]  # type: ignore[operator]
    assert _row(bull, "sga_pct_revenue").sources == ["default"] * 5


def test_the_grid_warns_that_revenue_growth_offsets_are_unused_by_segments(
    db_session: Session, aapl: Company
) -> None:
    iphone = _series(db_session, aapl, "iPhone", fy_values={2024: 200, 2025: 210})
    main = _main(db_session, aapl)
    update_scenario(
        db_session,
        aapl,
        main.id,
        SettingsInput(revenue_method="segments", segment_dimension="business"),
        NOW,
    )

    grid = driver_grid(db_session, aapl, main.id, "bull")

    assert grid.warnings == ["Offsets on revenue_growth are not used by the segments method"]
    codes = [r.code for r in grid.rows]
    assert "revenue_growth" not in codes
    segment = _row(grid, f"segment_growth:{iphone.id}")
    assert segment.label == "iPhone growth"
    assert segment.history[-1] == D("0.05")


def test_a_company_without_an_opening_has_no_grid(db_session: Session, empty: Company) -> None:
    main = _main(db_session, empty)

    with pytest.raises(ForecastUnavailable, match="No complete balance sheet"):
        driver_grid(db_session, empty, main.id, "base")


# --- driver PUT -------------------------------------------------------------------------------


def _put(
    session: Session, company: Company, scenario: Scenario, case: str, *rows: DriverRowInput
) -> DriverGrid:
    return put_drivers(session, company, scenario.id, case, rows, NOW)


def test_a_put_stores_a_row_and_drops_its_nulls(db_session: Session, aapl: Company) -> None:
    main = _main(db_session, aapl)
    choose_engines(db_session, main.id, {"revenue_growth": "mean"})  # asserts the M4 3-year mean
    y = driver_grid(db_session, aapl, main.id, "base").forecast_years

    grid = _put(
        db_session,
        aapl,
        main,
        "base",
        DriverRowInput("revenue_growth", "value", [(y[0], D("0.08")), (y[1], None)]),
    )

    growth = _row(grid, "revenue_growth")
    assert (growth.kind, growth.own[:2], growth.sources[:2]) == (
        "value",
        [D("0.08"), None],
        ["own", "default"],
    )
    assert growth.values[0] == D("0.08")
    assert _rows(db_session, main, "base") == {("revenue_growth", y[0]): ("value", D("0.08"))}


def test_a_put_replaces_every_row_of_the_driver_including_stale_years(
    db_session: Session, aapl: Company
) -> None:
    main = _main(db_session, aapl)
    y = driver_grid(db_session, aapl, main.id, "base").forecast_years
    _put(
        db_session,
        aapl,
        main,
        "base",
        DriverRowInput("tax_rate", "value", [(y[0], D("0.2")), (y[1], D("0.2"))]),
    )
    base_case = scenarios_repo.cases_of(db_session, main.id)["base"]
    db_session.add(
        DriverValue(
            case_id=base_case.id, driver_code="tax_rate", fiscal_year=2001, kind="value", value=1
        )
    )
    db_session.commit()

    _put(db_session, aapl, main, "base", DriverRowInput("tax_rate", "value", [(y[2], D("0.25"))]))

    assert _rows(db_session, main, "base") == {("tax_rate", y[2]): ("value", D("0.25"))}


def test_a_value_row_on_bull_replaces_its_offsets(db_session: Session, aapl: Company) -> None:
    main = _main(db_session, aapl)
    choose_engines(db_session, main.id, {"gross_margin": "mean"})  # asserts the M4 3-year mean
    y = driver_grid(db_session, aapl, main.id, "bull").forecast_years

    grid = _put(
        db_session, aapl, main, "bull", DriverRowInput("gross_margin", "value", [(y[0], D("0.5"))])
    )

    rows = _rows(db_session, main, "bull")
    assert {k: v for k, v in rows.items() if k[0] == "gross_margin"} == {
        ("gross_margin", y[0]): ("value", D("0.5"))
    }
    margin = _row(grid, "gross_margin")
    assert margin.sources[:2] == ["own", "default"]


def test_a_put_on_bull_leaves_base_and_bear_alone(db_session: Session, aapl: Company) -> None:
    main = _main(db_session, aapl)
    y = driver_grid(db_session, aapl, main.id, "bull").forecast_years
    before = {c: _rows(db_session, main, c) for c in ("base", "bear")}

    _put(db_session, aapl, main, "bull", DriverRowInput("tax_rate", "offset", [(y[0], D("0.01"))]))

    assert {c: _rows(db_session, main, c) for c in ("base", "bear")} == before


def test_a_base_edit_moves_bull_s_inherited_and_offset_values(
    db_session: Session, aapl: Company
) -> None:
    main = _main(db_session, aapl)
    y = driver_grid(db_session, aapl, main.id, "base").forecast_years

    _put(
        db_session,
        aapl,
        main,
        "base",
        DriverRowInput("gross_margin", "value", [(y[0], D("0.4"))]),
        DriverRowInput("sga_pct_revenue", "value", [(y[0], D("0.07"))]),
    )

    bull = driver_grid(db_session, aapl, main.id, "bull")
    assert (_row(bull, "gross_margin").values[0], _row(bull, "gross_margin").sources[0]) == (
        D("0.41"),
        "offset",
    )
    assert (_row(bull, "sga_pct_revenue").values[0], _row(bull, "sga_pct_revenue").sources[0]) == (
        D("0.07"),
        "base",
    )


@pytest.mark.parametrize(
    ("row", "message"),
    [
        (DriverRowInput("magic", "value", []), "Unknown driver 'magic'"),
        (DriverRowInput("segment_growth", "value", []), "Unknown driver 'segment_growth'"),
        (
            DriverRowInput("volume_growth", "value", []),
            "volume_growth is not a driver of the growth method",
        ),
        (DriverRowInput("tax_rate", "value", [(2001, D("0.2"))]), "FY2001 is not a forecast year"),
        (DriverRowInput("tax_rate", "value", [(0, D("2"))]), "tax_rate must be in \\[0, 1\\]"),
        (
            DriverRowInput("revenue_growth", "value", [(0, D("-1"))]),
            "revenue_growth must be in \\(-1, 10\\]",
        ),
        (
            DriverRowInput("tax_rate", "value", [(0, D("Infinity"))]),
            "tax_rate must be a finite number",
        ),
        (DriverRowInput("tax_rate", "value", [(0, D("NaN"))]), "tax_rate must be a finite number"),
        (
            DriverRowInput("buybacks", "value", [(0, D("1e400"))]),
            "buybacks must be in \\[0, 10\\^15\\)",
        ),
        (DriverRowInput("tax_rate", "offset", [(0, D("0.01"))]), "Base cannot hold offsets"),
        (DriverRowInput("tax_rate", "both", [(0, D("0.01"))]), "kind must be value or offset"),
        (
            DriverRowInput("tax_rate", "value", [(0, D("0.2")), (0, D("0.3"))]),
            "FY.* is given twice for tax_rate",
        ),
    ],
)
def test_an_invalid_put_on_base_is_refused_and_stores_nothing(
    db_session: Session, aapl: Company, row: DriverRowInput, message: str
) -> None:
    main = _main(db_session, aapl)
    first = driver_grid(db_session, aapl, main.id, "base").forecast_years[0]
    # year 0 stands for the first forecast year
    row = DriverRowInput(row.driver_code, row.kind, [(y or first, v) for y, v in row.values])
    valid = DriverRowInput("sga_pct_revenue", "value", [(first, D("0.1"))])

    with pytest.raises(InvalidDrivers, match=message):
        _put(db_session, aapl, main, "base", valid, row)
    assert _rows(db_session, main, "base") == {}


def test_a_driver_given_twice_is_refused(db_session: Session, aapl: Company) -> None:
    main = _main(db_session, aapl)
    row = DriverRowInput("tax_rate", "value", [])

    with pytest.raises(InvalidDrivers, match="tax_rate is given twice"):
        _put(db_session, aapl, main, "base", row, row)


def test_an_offset_beyond_its_bound_is_refused(db_session: Session, aapl: Company) -> None:
    main = _main(db_session, aapl)
    first = driver_grid(db_session, aapl, main.id, "bull").forecast_years[0]

    with pytest.raises(InvalidDrivers, match="receivable_days offset must be in \\[-730, 730\\]"):
        _put(
            db_session,
            aapl,
            main,
            "bull",
            DriverRowInput("receivable_days", "offset", [(first, D(731))]),
        )
    _put(
        db_session, aapl, main, "bull", DriverRowInput("tax_rate", "offset", [(first, D("-0.05"))])
    )
    assert _rows(db_session, main, "bull")[("tax_rate", first)] == ("offset", D("-0.05"))


def test_another_company_s_scenario_has_no_grid(
    db_session: Session, aapl: Company, empty: Company
) -> None:
    other = _main(db_session, empty)

    with pytest.raises(ScenarioNotFound):
        driver_grid(db_session, aapl, other.id, "base")
    with pytest.raises(ScenarioNotFound):
        put_drivers(db_session, aapl, other.id, "base", [], NOW)


# --- review fixes -------------------------------------------------------------------------------


def test_a_stale_kpi_off_volume_price_does_not_block_later_writes(
    db_session: Session, aapl: Company
) -> None:
    units = _series(db_session, aapl, "Units", dimension="kpi", metric="units", unit="count")
    asp = _series(db_session, aapl, "ASP", dimension="kpi", metric="asp", unit="USD_per_unit")
    main = _main(db_session, aapl)
    vp = SettingsInput(revenue_method="volume_price", volume_kpi="units", price_kpi="asp")
    update_scenario(db_session, aapl, main.id, vp, NOW)
    update_scenario(db_session, aapl, main.id, SettingsInput(revenue_method="growth"), NOW)
    for series in (units, asp):
        db_session.delete(series)
    db_session.commit()

    renamed = update_scenario(db_session, aapl, main.id, SettingsInput(name="Main 2"), NOW)
    created = create_scenario(db_session, aapl, SettingsInput(name="New"), NOW)

    assert renamed.name == "Main 2"
    assert created.revenue_method == "growth"
    with pytest.raises(InvalidScenario, match="volume_kpi 'units' is not a KPI"):
        update_scenario(
            db_session, aapl, main.id, SettingsInput(revenue_method="volume_price"), NOW
        )


def test_defaults_created_by_a_concurrent_request_are_not_an_error(
    db_session: Session, aapl: Company, monkeypatch: pytest.MonkeyPatch
) -> None:
    created = list_scenarios(db_session, aapl, NOW)
    # The other request's insert lands between this request's check and its own insert.
    real = scenarios_repo.list_for
    stale = [True]

    def list_for(session: Session, company_id: int) -> list[Scenario]:
        if stale:
            stale.pop()
            return []
        return real(session, company_id)

    monkeypatch.setattr(scenarios_repo, "list_for", list_for)

    ensure_defaults(db_session, aapl, NOW)

    assert [s.id for s in list_scenarios(db_session, aapl, NOW)] == [s.id for s in created]
    assert db_session.query(ScenarioCase).count() == 3


def _count_history_loads(monkeypatch: pytest.MonkeyPatch) -> list[int]:
    """A spy on the real `load_history`: one entry per build of the company's history."""
    calls: list[int] = []
    real = scenarios_service.load_history

    def counting(*args, **kwargs):  # type: ignore[no-untyped-def]  # a spy on the real loader
        calls.append(1)
        return real(*args, **kwargs)

    monkeypatch.setattr(scenarios_service, "load_history", counting)
    return calls


@pytest.mark.parametrize("case", ["base", "bull", "bear"])
def test_a_driver_put_builds_the_history_once(
    db_session: Session, aapl: Company, monkeypatch: pytest.MonkeyPatch, case: str
) -> None:
    main = _main(db_session, aapl)
    years = driver_grid(db_session, aapl, main.id, case).forecast_years
    calls = _count_history_loads(monkeypatch)
    kind = "value" if case == "base" else "offset"

    grid = put_drivers(
        db_session,
        aapl,
        main.id,
        case,
        [DriverRowInput("gross_margin", kind, [(y, Decimal("0.02")) for y in years])],
        NOW,
    )

    assert len(calls) == 1
    row = next(r for r in grid.rows if r.code == "gross_margin")
    assert row.own == [Decimal("0.02")] * len(years)  # the returned grid holds the write


@pytest.mark.parametrize("case", ["base", "bull", "bear"])
def test_a_reset_and_a_confirmed_driver_import_build_the_history_once(
    db_session: Session, aapl: Company, monkeypatch: pytest.MonkeyPatch, case: str
) -> None:
    main = _main(db_session, aapl)
    content, name = export_drivers(db_session, aapl, main.id, case, "csv")
    calls = _count_history_loads(monkeypatch)

    result = import_drivers(db_session, aapl, main.id, case, content, name, False, NOW)
    imported = len(calls)
    reset_case(db_session, aapl, main.id, case, NOW)

    assert imported == 1
    assert len(calls) == 2
    assert result.grid is not None


def test_the_export_file_name_carries_the_scenario_and_the_case(
    db_session: Session, aapl: Company
) -> None:
    main = _main(db_session, aapl)

    names = [export_drivers(db_session, aapl, main.id, c, "csv")[1] for c in ("base", "bull")]

    assert names == ["AAPL-Main-Base-drivers.csv", "AAPL-Main-Bull-drivers.csv"]
    assert export_drivers(db_session, aapl, main.id, "bear", "xlsx")[1] == (
        "AAPL-Main-Bear-drivers.xlsx"
    )


# --- quarterly drivers ----------------------------------------------------------------------


def _annual_only(monkeypatch: pytest.MonkeyPatch) -> None:
    """Makes `load_history` return the company's history without its quarterly statements."""
    real = scenarios_service.load_history

    def annual_only(session: Session, company: Company) -> ForecastHistory:
        history = real(session, company)
        empty = {
            code: replace(table, periods=[], rows=[]) for code, table in history.quarterly.items()
        }
        return replace(history, quarterly=empty)

    monkeypatch.setattr(scenarios_service, "load_history", annual_only)


def test_an_annual_only_company_has_no_quarterly_grid_and_no_quarterly_put(
    db_session: Session, aapl: Company, monkeypatch: pytest.MonkeyPatch
) -> None:
    main = list_scenarios(db_session, aapl, NOW)[0]
    _annual_only(monkeypatch)

    with pytest.raises(ForecastUnavailable, match="^No quarterly history$"):
        driver_grid(db_session, aapl, main.id, "bull", "quarterly")
    row = DriverRowInput("tax_rate", "value", freq="quarterly", quarters=[(2027, "Q1", D("0.2"))])
    with pytest.raises(ForecastUnavailable, match="^No quarterly history$"):
        put_drivers(db_session, aapl, main.id, "bull", [row], NOW)
    annual = driver_grid(db_session, aapl, main.id, "bull")
    assert annual.freq == "annual"  # annual works
    assert annual.has_quarters is False


def test_an_annual_only_company_cannot_set_a_year_by_quarter(
    db_session: Session, aapl: Company, monkeypatch: pytest.MonkeyPatch
) -> None:
    main = list_scenarios(db_session, aapl, NOW)[0]
    year = driver_grid(db_session, aapl, main.id, "base").forecast_years[0]
    _annual_only(monkeypatch)

    with pytest.raises(ForecastUnavailable, match="^No quarterly history$"):
        scenarios_service.set_year_mode(db_session, aapl, main.id, year, "quarterly", NOW)
    assert all(m.mode == "annual" for m in scenarios_service.year_modes(db_session, aapl, main.id))


def test_a_company_without_data_has_no_quarterly_grid(db_session: Session, empty: Company) -> None:
    main = list_scenarios(db_session, empty, NOW)[0]

    with pytest.raises(ForecastUnavailable):
        driver_grid(db_session, empty, main.id, "base", "quarterly")


def test_a_quarterly_row_with_year_values_or_an_annual_row_with_quarters_is_refused(
    db_session: Session, aapl: Company
) -> None:
    main = list_scenarios(db_session, aapl, NOW)[0]
    first = driver_grid(db_session, aapl, main.id, "bull", "quarterly").forecast_periods[0]
    quarter = (first.fiscal_year, first.fiscal_period, D("0.2"))

    with pytest.raises(InvalidDrivers, match="FY value in a quarterly row"):
        put_drivers(
            db_session,
            aapl,
            main.id,
            "bull",
            [DriverRowInput("tax_rate", "value", [(first.fiscal_year, D("0.2"))], "quarterly")],
            NOW,
        )
    with pytest.raises(InvalidDrivers, match="quarter value in an annual row"):
        put_drivers(
            db_session,
            aapl,
            main.id,
            "bull",
            [DriverRowInput("tax_rate", "value", quarters=[quarter])],
            NOW,
        )
    with pytest.raises(InvalidDrivers, match="is given twice for tax_rate"):
        put_drivers(
            db_session,
            aapl,
            main.id,
            "bull",
            [DriverRowInput("tax_rate", "value", freq="quarterly", quarters=[quarter, quarter])],
            NOW,
        )


def test_a_row_that_stores_no_value_keeps_the_other_frequency_s_rows(
    db_session: Session, aapl: Company
) -> None:
    main = list_scenarios(db_session, aapl, NOW)[0]
    periods = driver_grid(db_session, aapl, main.id, "bull", "quarterly").forecast_periods
    year = periods[0].fiscal_year
    set_year_mode(db_session, aapl, main.id, year, "quarterly", NOW)
    quarters = [
        (p.fiscal_year, p.fiscal_period, D("0.5")) for p in periods if p.fiscal_year == year
    ]
    quarterly = DriverRowInput("gross_margin", "value", freq="quarterly", quarters=quarters)
    grid = put_drivers(db_session, aapl, main.id, "bull", [quarterly], NOW)
    assert _row(grid, "gross_margin").own[0] == D("0.5")

    # an annual row of another kind that stores nothing clears the years, not the quarter
    cleared = DriverRowInput("gross_margin", "offset", [(year, None)])
    put_drivers(db_session, aapl, main.id, "bull", [cleared], NOW)

    kept = driver_grid(db_session, aapl, main.id, "bull", "quarterly")
    assert _row(kept, "gross_margin").own[0] == D("0.5")


def test_one_put_can_hold_an_annual_and_a_quarterly_row_of_the_same_driver(
    db_session: Session, aapl: Company
) -> None:
    """A year set annually and a year set by quarter, in the same PUT."""
    main = list_scenarios(db_session, aapl, NOW)[0]
    periods = driver_grid(db_session, aapl, main.id, "bull", "quarterly").forecast_periods
    annual_year = periods[0].fiscal_year
    quarter_year = next(p.fiscal_year for p in periods if p.fiscal_year != annual_year)
    set_year_mode(db_session, aapl, main.id, quarter_year, "quarterly", NOW)
    annual = DriverRowInput("tax_rate", "value", [(annual_year, D("0.25"))])
    quarterly = DriverRowInput(
        "tax_rate",
        "value",
        freq="quarterly",
        quarters=[
            (p.fiscal_year, p.fiscal_period, D("0.3"))
            for p in periods
            if p.fiscal_year == quarter_year
        ],
    )

    put_drivers(db_session, aapl, main.id, "bull", [annual, quarterly], NOW)

    assert _row(driver_grid(db_session, aapl, main.id, "bull"), "tax_rate").own[0] == D("0.25")
    quarter = driver_grid(db_session, aapl, main.id, "bull", "quarterly")
    tax = _row(quarter, "tax_rate")
    owned = [
        v
        for p, v in zip(quarter.forecast_periods, tax.own, strict=True)
        if p.fiscal_year == quarter_year
    ]
    assert owned == [D("0.3")] * len(owned) and owned
    twice = DriverRowInput("tax_rate", "value", [(annual_year, D("0.2"))])
    with pytest.raises(InvalidDrivers, match="tax_rate is given twice"):
        put_drivers(db_session, aapl, main.id, "bull", [annual, twice], NOW)
