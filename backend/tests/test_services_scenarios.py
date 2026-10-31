"""Scenarios of a followed company (docs/erd/forecasting.md "Scenarios (M4)"), on the recorded AAPL
fixtures: the default Base/Bull/Bear, CRUD, settings validation, the driver grid and its PUT."""

from collections.abc import Iterator
from datetime import UTC, datetime
from decimal import Decimal

import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session

from bedrock.forecast.drivers import drivers_for
from bedrock.forecast.errors import ForecastUnavailable
from bedrock.forecast.history import (
    ScenarioSettings,
    default_drivers,
    forecast_years,
    history_years,
)
from bedrock.models.company import Company
from bedrock.models.driver_value import DriverValue
from bedrock.models.scenario import Scenario
from bedrock.models.segment_series import SegmentSeries
from bedrock.models.segment_value import SegmentValue
from bedrock.repositories import scenarios as scenarios_repo
from bedrock.services import scenarios as scenarios_service
from bedrock.services.errors import (
    InvalidDrivers,
    InvalidScenario,
    ScenarioConflict,
    ScenarioNotFound,
)
from bedrock.services.refresh import refresh_company
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
    update_scenario,
)

from .seed import fake_sources, follow

NOW = datetime(2026, 10, 31, 9, 0, tzinfo=UTC)
D = Decimal


@pytest.fixture
def aapl(db_session: Session) -> Iterator[Company]:
    sources = fake_sources()
    company = follow(db_session, sources.edgar, "AAPL")
    refresh_company(db_session, sources, "AAPL", NOW)
    yield company


@pytest.fixture
def empty(db_session: Session) -> Company:
    """A followed company with no data: no opening balance sheet."""
    return follow(db_session, fake_sources().edgar, "MSFT")


def _rows(session: Session, scenario: Scenario) -> dict[tuple[str, int], tuple[str, Decimal]]:
    stmt = select(DriverValue).where(DriverValue.scenario_id == scenario.id)
    return {
        (r.driver_code, r.fiscal_year): (r.kind, Decimal(str(r.value)).normalize())
        for r in session.execute(stmt).scalars()
    }


def _named(session: Session, company: Company) -> dict[str, Scenario]:
    return {s.name: s for s in list_scenarios(session, company, NOW)}


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


def test_the_first_list_creates_base_bull_and_bear_once(db_session: Session, aapl: Company) -> None:
    first = list_scenarios(db_session, aapl, NOW)
    ensure_defaults(db_session, aapl, NOW)
    second = list_scenarios(db_session, aapl, NOW)

    assert [s.name for s in first] == ["Base", "Bull", "Bear"]
    assert [s.id for s in second] == [s.id for s in first]
    base, bull, bear = first
    assert (base.is_default, base.base_id) == (True, None)
    assert (bull.is_default, bull.base_id, bear.base_id) == (False, base.id, base.id)
    for s in first:
        assert s.revenue_method == "growth"
        assert s.created_at == datetime(2026, 10, 31, 9, 0)  # naive UTC from the clock


def test_bull_and_bear_hold_offsets_for_the_five_forecast_years_and_base_holds_none(
    db_session: Session, aapl: Company
) -> None:
    """The horizon is fixed at 5 years (user, 2026-10-31): no offset lies beyond it."""
    scenarios = _named(db_session, aapl)
    years = forecast_years(load_history(db_session, aapl), 5)

    assert _rows(db_session, scenarios["Base"]) == {}
    assert _rows(db_session, scenarios["Bull"]) == {
        **{("revenue_growth", y): ("offset", D("0.03")) for y in years},
        **{("gross_margin", y): ("offset", D("0.01")) for y in years},
    }
    assert _rows(db_session, scenarios["Bear"]) == {
        **{("revenue_growth", y): ("offset", D("-0.03")) for y in years},
        **{("gross_margin", y): ("offset", D("-0.01")) for y in years},
    }


def test_a_company_without_an_opening_gets_scenarios_without_offsets(
    db_session: Session, empty: Company
) -> None:
    scenarios = list_scenarios(db_session, empty, NOW)

    assert [s.name for s in scenarios] == ["Base", "Bull", "Bear"]
    assert all(_rows(db_session, s) == {} for s in scenarios)


def test_scenarios_are_listed_base_first_then_by_id(db_session: Session, aapl: Company) -> None:
    list_scenarios(db_session, aapl, NOW)
    create_scenario(db_session, aapl, SettingsInput(name="Aardvark"), NOW)

    assert [s.name for s in list_scenarios(db_session, aapl, NOW)] == [
        "Base",
        "Bull",
        "Bear",
        "Aardvark",
    ]


# --- create, update, delete -----------------------------------------------------------------


def test_a_new_scenario_copies_base_settings_and_inherits_base(
    db_session: Session, aapl: Company
) -> None:
    base = _named(db_session, aapl)["Base"]
    _series(db_session, aapl, "Americas", dimension="geo")
    geo = SettingsInput(revenue_method="segments", segment_dimension="geo")
    update_scenario(db_session, aapl, base.id, geo, NOW)

    created = create_scenario(db_session, aapl, SettingsInput(name="  Mine  "), NOW)

    assert created.name == "Mine"
    assert (created.is_default, created.base_id) == (False, base.id)
    assert (created.revenue_method, created.segment_dimension) == ("segments", "geo")
    assert _rows(db_session, created) == {}


def test_a_duplicate_name_is_a_conflict_on_create_and_update(
    db_session: Session, aapl: Company
) -> None:
    bull = _named(db_session, aapl)["Bull"]

    with pytest.raises(ScenarioConflict, match="already has a scenario named 'Bear'"):
        create_scenario(db_session, aapl, SettingsInput(name="Bear"), NOW)
    with pytest.raises(ScenarioConflict):
        update_scenario(db_session, aapl, bull.id, SettingsInput(name=" Bear "), NOW)
    # its own name is not a duplicate
    assert (
        update_scenario(db_session, aapl, bull.id, SettingsInput(name="Bull"), NOW).name == "Bull"
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
    assert len(list_scenarios(db_session, aapl, NOW)) == 3


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
    bull = _named(db_session, aapl)["Bull"]

    updated = update_scenario(
        db_session,
        aapl,
        bull.id,
        SettingsInput(revenue_method="segments", segment_dimension="geo"),
        NOW,
    )
    assert (updated.name, updated.revenue_method, updated.segment_dimension) == (
        "Bull",
        "segments",
        "geo",
    )
    again = update_scenario(db_session, aapl, bull.id, SettingsInput(name="Bullish"), NOW)

    assert (again.revenue_method, again.segment_dimension, again.name) == (
        "segments",
        "geo",
        "Bullish",
    )
    assert again.updated_at == datetime(2026, 10, 31, 9, 0)


def test_another_company_s_scenario_is_not_found(
    db_session: Session, aapl: Company, empty: Company
) -> None:
    other = list_scenarios(db_session, empty, NOW)[1]
    list_scenarios(db_session, aapl, NOW)

    with pytest.raises(ScenarioNotFound):
        update_scenario(db_session, aapl, other.id, SettingsInput(name="X"), NOW)
    with pytest.raises(ScenarioNotFound):
        delete_scenario(db_session, aapl, other.id)
    with pytest.raises(ScenarioNotFound):
        delete_scenario(db_session, aapl, 999_999)


def test_base_cannot_be_deleted(db_session: Session, aapl: Company) -> None:
    base = _named(db_session, aapl)["Base"]

    with pytest.raises(ScenarioConflict, match="Base cannot be deleted"):
        delete_scenario(db_session, aapl, base.id)


def test_deleting_a_scenario_deletes_its_driver_rows(db_session: Session, aapl: Company) -> None:
    bull = _named(db_session, aapl)["Bull"]

    delete_scenario(db_session, aapl, bull.id)

    assert [s.name for s in list_scenarios(db_session, aapl, NOW)] == ["Base", "Bear"]
    stmt = select(DriverValue).where(DriverValue.scenario_id == bull.id)
    assert db_session.execute(stmt).first() is None


# --- segments: default offsets ----------------------------------------------------------------


def test_bull_and_bear_switched_to_segments_get_an_offset_on_each_segment(
    db_session: Session, aapl: Company
) -> None:
    iphone = _series(db_session, aapl, "iPhone", fy_values={2024: 200})
    mac = _series(db_session, aapl, "Mac", fy_values={2024: 30})
    geo = _series(db_session, aapl, "Americas", dimension="geo")
    income = _series(db_session, aapl, "iPhone OI", metric="operating_income")
    scenarios = _named(db_session, aapl)
    years = forecast_years(load_history(db_session, aapl), 5)
    segments = SettingsInput(revenue_method="segments", segment_dimension="business")

    for name, sign in (("Bull", ""), ("Bear", "-")):
        before = _rows(db_session, scenarios[name])
        update_scenario(db_session, aapl, scenarios[name].id, segments, NOW)
        after = _rows(db_session, scenarios[name])

        added = {k: v for k, v in after.items() if k not in before}
        assert added == {
            (f"segment_growth:{s.id}", y): ("offset", D(f"{sign}0.03"))
            for s in (iphone, mac)
            for y in years
        }
        # the revenue_growth offsets stay, for a switch back to growth
        assert {k: v for k, v in after.items() if k in before} == before
    assert not any(code.endswith((str(geo.id), str(income.id))) for code, _ in added)


def test_a_segment_with_own_rows_keeps_them_and_a_later_segment_gets_none(
    db_session: Session, aapl: Company
) -> None:
    iphone = _series(db_session, aapl, "iPhone")
    bull = _named(db_session, aapl)["Bull"]
    first_year = forecast_years(load_history(db_session, aapl), 5)[0]
    db_session.add(
        DriverValue(
            scenario_id=bull.id,
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
        bull.id,
        SettingsInput(revenue_method="segments", segment_dimension="business"),
        NOW,
    )
    later = _series(db_session, aapl, "Services")
    update_scenario(db_session, aapl, bull.id, SettingsInput(name="Bull 2"), NOW)

    rows = _rows(db_session, bull)
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
    bear = _named(db_session, aapl)["Bear"]
    to = SettingsInput(revenue_method="segments", segment_dimension="business")
    update_scenario(db_session, aapl, bear.id, to, NOW)

    update_scenario(db_session, aapl, bear.id, SettingsInput(segment_dimension="geo"), NOW)

    rows = _rows(db_session, bear)
    assert sum(1 for code, _ in rows if code == f"segment_growth:{americas.id}") == 5
    assert all(
        v == ("offset", D("-0.03")) for (c, _), v in rows.items() if c.endswith(f":{americas.id}")
    )


def test_a_scenario_that_is_not_a_default_bull_or_bear_gets_no_segment_offsets(
    db_session: Session, aapl: Company
) -> None:
    _series(db_session, aapl, "iPhone")
    mine = create_scenario(db_session, aapl, SettingsInput(name="Mine"), NOW)
    base = _named(db_session, aapl)["Base"]
    segments = SettingsInput(revenue_method="segments", segment_dimension="business")

    update_scenario(db_session, aapl, mine.id, segments, NOW)
    update_scenario(db_session, aapl, base.id, segments, NOW)

    assert _rows(db_session, mine) == {}
    assert _rows(db_session, base) == {}


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
    base = _named(db_session, aapl)["Base"]
    history = load_history(db_session, aapl)

    grid = driver_grid(db_session, aapl, base.id)

    assert grid.scenario_id == base.id
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
    scenarios = _named(db_session, aapl)
    base = driver_grid(db_session, aapl, scenarios["Base"].id)

    bull = driver_grid(db_session, aapl, scenarios["Bull"].id)

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
    bull = _named(db_session, aapl)["Bull"]
    update_scenario(
        db_session,
        aapl,
        bull.id,
        SettingsInput(revenue_method="segments", segment_dimension="business"),
        NOW,
    )

    grid = driver_grid(db_session, aapl, bull.id)

    assert grid.warnings == ["Offsets on revenue_growth are not used by the segments method"]
    codes = [r.code for r in grid.rows]
    assert "revenue_growth" not in codes
    segment = _row(grid, f"segment_growth:{iphone.id}")
    assert segment.label == "iPhone growth"
    assert segment.history[-1] == D("0.05")


def test_a_company_without_an_opening_has_no_grid(db_session: Session, empty: Company) -> None:
    base = list_scenarios(db_session, empty, NOW)[0]

    with pytest.raises(ForecastUnavailable, match="No complete balance sheet"):
        driver_grid(db_session, empty, base.id)


# --- driver PUT -------------------------------------------------------------------------------


def _put(
    session: Session, company: Company, scenario: Scenario, *rows: DriverRowInput
) -> DriverGrid:
    return put_drivers(session, company, scenario.id, rows, NOW)


def test_a_put_stores_a_row_and_drops_its_nulls(db_session: Session, aapl: Company) -> None:
    base = _named(db_session, aapl)["Base"]
    y = driver_grid(db_session, aapl, base.id).forecast_years

    grid = _put(
        db_session,
        aapl,
        base,
        DriverRowInput("revenue_growth", "value", [(y[0], D("0.08")), (y[1], None)]),
    )

    growth = _row(grid, "revenue_growth")
    assert (growth.kind, growth.own[:2], growth.sources[:2]) == (
        "value",
        [D("0.08"), None],
        ["own", "default"],
    )
    assert growth.values[0] == D("0.08")
    assert _rows(db_session, base) == {("revenue_growth", y[0]): ("value", D("0.08"))}


def test_a_put_replaces_every_row_of_the_driver_including_stale_years(
    db_session: Session, aapl: Company
) -> None:
    base = _named(db_session, aapl)["Base"]
    y = driver_grid(db_session, aapl, base.id).forecast_years
    _put(
        db_session,
        aapl,
        base,
        DriverRowInput("tax_rate", "value", [(y[0], D("0.2")), (y[1], D("0.2"))]),
    )
    db_session.add(
        DriverValue(
            scenario_id=base.id, driver_code="tax_rate", fiscal_year=2001, kind="value", value=1
        )
    )
    db_session.commit()

    _put(db_session, aapl, base, DriverRowInput("tax_rate", "value", [(y[2], D("0.25"))]))

    assert _rows(db_session, base) == {("tax_rate", y[2]): ("value", D("0.25"))}


def test_a_value_row_on_bull_replaces_its_offsets(db_session: Session, aapl: Company) -> None:
    bull = _named(db_session, aapl)["Bull"]
    y = driver_grid(db_session, aapl, bull.id).forecast_years

    grid = _put(db_session, aapl, bull, DriverRowInput("gross_margin", "value", [(y[0], D("0.5"))]))

    rows = _rows(db_session, bull)
    assert {k: v for k, v in rows.items() if k[0] == "gross_margin"} == {
        ("gross_margin", y[0]): ("value", D("0.5"))
    }
    margin = _row(grid, "gross_margin")
    assert margin.sources[:2] == ["own", "default"]


def test_a_base_edit_moves_bull_s_inherited_and_offset_values(
    db_session: Session, aapl: Company
) -> None:
    scenarios = _named(db_session, aapl)
    y = driver_grid(db_session, aapl, scenarios["Base"].id).forecast_years

    _put(
        db_session,
        aapl,
        scenarios["Base"],
        DriverRowInput("gross_margin", "value", [(y[0], D("0.4"))]),
        DriverRowInput("sga_pct_revenue", "value", [(y[0], D("0.07"))]),
    )

    bull = driver_grid(db_session, aapl, scenarios["Bull"].id)
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
    base = _named(db_session, aapl)["Base"]
    first = driver_grid(db_session, aapl, base.id).forecast_years[0]
    # year 0 stands for the first forecast year
    row = DriverRowInput(row.driver_code, row.kind, [(y or first, v) for y, v in row.values])
    valid = DriverRowInput("sga_pct_revenue", "value", [(first, D("0.1"))])

    with pytest.raises(InvalidDrivers, match=message):
        _put(db_session, aapl, base, valid, row)
    assert _rows(db_session, base) == {}


def test_a_driver_given_twice_is_refused(db_session: Session, aapl: Company) -> None:
    base = _named(db_session, aapl)["Base"]
    row = DriverRowInput("tax_rate", "value", [])

    with pytest.raises(InvalidDrivers, match="tax_rate is given twice"):
        _put(db_session, aapl, base, row, row)


def test_an_offset_beyond_its_bound_is_refused(db_session: Session, aapl: Company) -> None:
    bull = _named(db_session, aapl)["Bull"]
    first = driver_grid(db_session, aapl, bull.id).forecast_years[0]

    with pytest.raises(InvalidDrivers, match="receivable_days offset must be in \\[-730, 730\\]"):
        _put(db_session, aapl, bull, DriverRowInput("receivable_days", "offset", [(first, D(731))]))
    _put(db_session, aapl, bull, DriverRowInput("tax_rate", "offset", [(first, D("-0.05"))]))
    assert _rows(db_session, bull)[("tax_rate", first)] == ("offset", D("-0.05"))


def test_another_company_s_scenario_has_no_grid(
    db_session: Session, aapl: Company, empty: Company
) -> None:
    other = list_scenarios(db_session, empty, NOW)[0]

    with pytest.raises(ScenarioNotFound):
        driver_grid(db_session, aapl, other.id)
    with pytest.raises(ScenarioNotFound):
        put_drivers(db_session, aapl, other.id, [], NOW)


# --- review fixes -------------------------------------------------------------------------------


def test_a_stale_kpi_off_volume_price_does_not_block_later_writes(
    db_session: Session, aapl: Company
) -> None:
    units = _series(db_session, aapl, "Units", dimension="kpi", metric="units", unit="count")
    asp = _series(db_session, aapl, "ASP", dimension="kpi", metric="asp", unit="USD_per_unit")
    base = _named(db_session, aapl)["Base"]
    vp = SettingsInput(revenue_method="volume_price", volume_kpi="units", price_kpi="asp")
    update_scenario(db_session, aapl, base.id, vp, NOW)
    update_scenario(db_session, aapl, base.id, SettingsInput(revenue_method="growth"), NOW)
    for series in (units, asp):
        db_session.delete(series)
    db_session.commit()

    renamed = update_scenario(db_session, aapl, base.id, SettingsInput(name="Base 2"), NOW)
    created = create_scenario(db_session, aapl, SettingsInput(name="New"), NOW)

    assert renamed.name == "Base 2"
    assert created.revenue_method == "growth"
    with pytest.raises(InvalidScenario, match="volume_kpi 'units' is not a KPI"):
        update_scenario(
            db_session, aapl, base.id, SettingsInput(revenue_method="volume_price"), NOW
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


def _count_history_loads(monkeypatch: pytest.MonkeyPatch) -> list[int]:
    """A spy on the real `load_history`: one entry per build of the company's history."""
    calls: list[int] = []
    real = scenarios_service.load_history

    def counting(*args, **kwargs):  # type: ignore[no-untyped-def]  # a spy on the real loader
        calls.append(1)
        return real(*args, **kwargs)

    monkeypatch.setattr(scenarios_service, "load_history", counting)
    return calls


def test_a_driver_put_builds_the_history_once(
    db_session: Session, aapl: Company, monkeypatch: pytest.MonkeyPatch
) -> None:
    bull = _named(db_session, aapl)["Bull"]
    years = driver_grid(db_session, aapl, bull.id).forecast_years
    calls = _count_history_loads(monkeypatch)

    grid = put_drivers(
        db_session,
        aapl,
        bull.id,
        [DriverRowInput("gross_margin", "offset", [(y, Decimal("0.02")) for y in years])],
        NOW,
    )

    assert len(calls) == 1
    row = next(r for r in grid.rows if r.code == "gross_margin")
    assert row.own == [Decimal("0.02")] * len(years)  # the returned grid holds the write


def test_a_confirmed_driver_import_builds_the_history_once(
    db_session: Session, aapl: Company, monkeypatch: pytest.MonkeyPatch
) -> None:
    bull = _named(db_session, aapl)["Bull"]
    content, name = export_drivers(db_session, aapl, bull.id, "csv")
    calls = _count_history_loads(monkeypatch)

    result = import_drivers(db_session, aapl, bull.id, content, name, False, NOW)

    assert len(calls) == 1
    assert result.grid is not None
