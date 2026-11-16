"""The backtest on the recorded companies with the real engines (FR-ACC-02, -03). `run_method`
raises when a forecast fails its integrity checks (A = L + E, cash and RE roll-forwards, Q1..Q4 =
FY), so a run with no `error` has passed them; Q1..Q4 = FY is also re-checked on the stored rows."""

from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from functools import cache

import pytest

from bedrock.backtest.pit import SETTINGS, MethodRun, origins, run_method
from bedrock.backtest.scoring import (
    Scored,
    driver_actuals,
    line_actuals,
    score_run,
    units_of,
)
from bedrock.backtest.snapshot import ValueRow
from bedrock.forecast.engine_defaults import ENGINE_CODES
from bedrock.forecast.history import opening_period
from bedrock.services.engines import memo_fit
from tests.forecast_data import fixture_history
from tests.statements_pipeline import fixture_splits, ten_k_dates

CLEAN = ("AAPL", "MSFT", "COST")
FLOWS = ("revenue", "operating_income", "net_income", "free_cash_flow")
TOLERANCE = Decimal("0.01")  # USD: the integrity check's rounding room on a sum of quarters


@dataclass(frozen=True)
class OriginRun:
    origin: date
    method: str
    run: MethodRun


@cache
def backtest(ticker: str) -> tuple[OriginRun, ...]:
    return tuple(
        OriginRun(origin, method, run_method(fixture_history(ticker, origin), method, memo_fit))
        for origin in origins(ten_k_dates(ticker))
        for method in ENGINE_CODES
    )


def scored(ticker: str, item: OriginRun) -> list[Scored]:
    latest = fixture_history(ticker)
    years = sorted({r.fiscal_year for r in item.run.rows})
    return score_run(
        item.run.rows,
        line_actuals(latest),
        driver_actuals(latest, SETTINGS, years),
        units_of(latest, SETTINGS),
        item.origin,
        fixture_splits(ticker),
    )


def rows_at(rows: list[ValueRow], code: str, year: int) -> dict[str, Decimal]:
    return {
        r.fiscal_period: r.point
        for r in rows
        if r.kind == "line" and r.code == code and r.fiscal_year == year
    }


def test_the_fixture_history_is_cut_at_the_date() -> None:
    history = fixture_history("MSFT", as_of=date(2017, 8, 2))
    assert history.annual_values.get("revenue", "FY2017") == Decimal("89950000000")
    assert all(p.end <= date(2017, 8, 2) for p in history.annual_values.periods)
    assert fixture_history("MSFT").annual_values.get("revenue", "FY2017") == Decimal("96571000000")


@pytest.mark.parametrize("ticker", CLEAN)
def test_every_origin_and_method_runs(ticker: str) -> None:
    runs = backtest(ticker)
    assert len(runs) == 60
    assert [(r.origin, r.method) for r in runs if r.run.error is not None] == []


@pytest.mark.parametrize("ticker", CLEAN)
def test_the_stored_quarters_sum_to_their_year(ticker: str) -> None:
    checked = 0
    for item in backtest(ticker):
        for year in {r.fiscal_year for r in item.run.rows}:
            for code in FLOWS:
                cells = rows_at(item.run.rows, code, year)
                if {"Q1", "Q2", "Q3", "Q4", "FY"} <= set(cells):
                    quarters = cells["Q1"] + cells["Q2"] + cells["Q3"] + cells["Q4"]
                    assert abs(quarters - cells["FY"]) <= TOLERANCE, (item.origin, code, year)
                    checked += 1
    assert checked > 0


@pytest.mark.parametrize("ticker", [*CLEAN, "DE"])
def test_every_run_has_a_scored_first_year_revenue(ticker: str) -> None:
    for item in backtest(ticker):
        if item.run.error is None:
            found = [
                s
                for s in scored(ticker, item)
                if (s.kind, s.code, s.fiscal_period, s.horizon) == ("line", "revenue", "FY", 1)
            ]
            assert len(found) == 1, (item.origin, item.method)
            assert found[0].pct_error is not None


@pytest.mark.parametrize("ticker", [*CLEAN, "DE"])
def test_no_stored_period_ended_on_or_before_the_opening(ticker: str) -> None:
    for item in backtest(ticker):
        opening = opening_period(fixture_history(ticker, item.origin))
        assert opening.fiscal_period in ("FY", "Q4"), item.origin
        assert all(r.fiscal_year > opening.fiscal_year for r in item.run.rows), item.origin


def test_de_runs_until_it_stops_reporting_cost_of_revenue() -> None:
    runs = backtest("DE")
    early = [r for r in runs if r.origin.year <= 2019]
    late = [r for r in runs if r.origin.year >= 2020]
    assert early and late
    assert [r.origin for r in early if r.run.error is not None] == []
    assert {r.run.error for r in late} == {"Set these drivers: gross_margin"}
