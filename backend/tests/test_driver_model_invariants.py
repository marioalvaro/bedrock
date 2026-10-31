"""Accounting invariants of the driver model over a seeded sweep of random driver sets, and the
integrity checks themselves (docs/erd/forecasting.md "Tier 1 driver model" → Integrity).
hypothesis is not installed (as in test_capital_allocation.py), so the properties run over
seeded random draws."""

import random
from dataclasses import replace
from decimal import Decimal
from typing import Any

import pytest

from bedrock.forecast import integrity
from bedrock.forecast.engines.driver import DriverModel, ForecastStatements, Horizon
from bedrock.forecast.errors import ForecastIntegrityError
from bedrock.forecast.history import FLAT, ScenarioSettings
from bedrock.forecast.integrity import IntegrityCheck
from tests.forecast_data import resolved
from tests.test_driver_model import DRIVERS_2026, annual_company, quarterly_company

D = Decimal
TOLERANCE = D("0.01")
YEARS = (2026, 2027, 2028)
CASES = 240
FLOWS = (
    "revenue",
    "cost_of_revenue",
    "operating_income",
    "net_income",
    "net_income_common",
    "cfo",
    "cfi",
    "cff",
    "net_change_in_cash",
    "free_cash_flow",
    "debt_issued",
    "debt_repaid",
)


def _uniform(rng: random.Random, low: float, high: float) -> Decimal:
    return D(str(round(rng.uniform(low, high), 4)))


def random_drivers(rng: random.Random) -> dict[str, Any]:
    days = lambda: FLAT if rng.random() < 0.2 else _uniform(rng, 0, 200)  # noqa: E731
    return {
        "revenue_growth": D(0) if rng.random() < 0.15 else _uniform(rng, -0.5, 1.0),
        "gross_margin": _uniform(rng, -0.3, 0.9),
        "rnd_pct_revenue": _uniform(rng, 0, 0.3),
        "sga_pct_revenue": _uniform(rng, 0, 0.3),
        "other_opex_pct_revenue": _uniform(rng, -0.1, 0.2),
        "d_and_a_pct_revenue": _uniform(rng, 0, 0.2),
        "sbc_pct_revenue": _uniform(rng, 0, 0.1),
        "other_nonoperating_pct_revenue": _uniform(rng, -0.1, 0.1),
        "interest_rate": _uniform(rng, 0, 0.2),
        "tax_rate": _uniform(rng, 0, 0.5),
        "nci_share": _uniform(rng, 0, 0.3),
        "receivable_days": days(),
        "inventory_days": days(),
        "payable_days": days(),
        "capex_pct_revenue": _uniform(rng, 0, 0.3),
        "debt_issued": _uniform(rng, 0, 500),
        "debt_repaid": _uniform(rng, 0, 500),
        "min_cash": _uniform(rng, 0, 1000),
        "buybacks": _uniform(rng, 0, 500),
        "dividend_payout": _uniform(rng, 0, 2),
        "share_change": _uniform(rng, -0.2, 0.3),
    }


def assert_invariants(out: ForecastStatements) -> None:
    get = lambda code, key: out.get(code, key) or D(0)  # noqa: E731
    opening = out.opening.balance
    previous = {"Q": (opening["cash"], opening["retained_earnings"])}
    for period in out.periods:
        key = period.key
        # A = L + E (with temporary equity)
        assert abs(get("total_assets", key) - get("total_liabilities_and_equity", key)) <= TOLERANCE
        assert (
            abs(
                get("total_assets", key)
                - get("total_liabilities", key)
                - get("temporary_equity", key)
                - get("total_equity", key)
            )
            <= TOLERANCE
        )
        if period.fiscal_period == "FY":
            continue
        cash, earnings = previous["Q"]
        assert abs(get("cash", key) - cash - get("net_change_in_cash", key)) <= TOLERANCE
        rolled = earnings + get("net_income_common", key) + get("dividends_paid", key)
        assert abs(get("retained_earnings", key) - rolled - get("buybacks", key)) <= TOLERANCE
        previous["Q"] = (get("cash", key), get("retained_earnings", key))
    # Q1..Q4 = FY: the forecast quarters plus, for the year in progress, its actual quarters.
    forecast_quarters = {p.key for p in out.periods if p.fiscal_period != "FY"}
    for year in out.annual():
        quarters = [f"FY{year.fiscal_year}Q{n}" for n in range(1, 5)]
        if not forecast_quarters & set(quarters):
            continue
        in_progress = out.opening.period.fiscal_year == year.fiscal_year
        for code in FLOWS:
            actual = (out.opening.year_to_date.get(code) or D(0)) if in_progress else D(0)
            total = actual + sum((get(code, q) for q in quarters if q in forecast_quarters), D(0))
            assert abs(get(code, year.key) - total) <= TOLERANCE, (code, year.key)


@pytest.mark.parametrize("quarterly", [True, False])
def test_random_driver_sets_keep_every_invariant(quarterly: bool) -> None:
    rng = random.Random(20261031 + quarterly)
    history = quarterly_company() if quarterly else annual_company()
    seen = {"loss": 0, "revolver": 0, "zero_growth": 0}
    for _ in range(CASES // 2):
        by_year = {y: random_drivers(rng) for y in YEARS}
        out = DriverModel().run(
            history, resolved(by_year), Horizon(len(YEARS), 6), ScenarioSettings("growth")
        )
        assert all(c.ok for c in out.integrity)
        assert_invariants(out)
        keys = [p.key for p in out.periods]
        seen["loss"] += any((out.get("net_income", k) or 0) < 0 for k in keys)
        seen["revolver"] += any(
            (out.get("short_term_debt", k) or 0) > 40 for k in keys
        )  # 40 is the opening short-term debt, held flat apart from the revolver
        seen["zero_growth"] += any(d["revenue_growth"] == 0 for d in by_year.values())
    assert all(count > 0 for count in seen.values()), seen


def test_a_tampered_balance_fails_its_checks() -> None:
    out = DriverModel().run(
        annual_company(), resolved({2026: DRIVERS_2026}), Horizon(1, 4), ScenarioSettings("growth")
    )
    values = dict(out.values)
    for code in ("cash", "total_assets", "retained_earnings"):
        values[(code, "FY2026")] = (values[(code, "FY2026")] or D(0)) + 1
    [check] = integrity.check(replace(out, values=values))
    assert (check.balance_diff, check.cash_diff, check.re_diff, check.ok) == (
        D(1),
        D(1),
        D(1),
        False,
    )


def test_a_year_that_is_not_the_sum_of_its_quarters_fails_its_check() -> None:
    out = DriverModel().run(
        quarterly_company(),
        resolved({2026: DRIVERS_2026, 2027: DRIVERS_2026}),
        Horizon(2, 2),
        ScenarioSettings("growth"),
    )
    values = dict(out.values)
    values[("sga", "FY2026")] = (values[("sga", "FY2026")] or D(0)) + D("0.5")
    checks = {c.period_key: c for c in integrity.check(replace(out, values=values))}
    assert (checks["FY2026"].quarters_diff, checks["FY2026"].ok) == (D("0.5"), False)


def test_a_failing_check_raises_an_integrity_error(monkeypatch: pytest.MonkeyPatch) -> None:
    failing = IntegrityCheck("FY2026", D(5), D(0), D(0), None, False)
    monkeypatch.setattr(integrity, "check", lambda statements: [failing])
    with pytest.raises(ForecastIntegrityError, match="FY2026"):
        DriverModel().run(
            annual_company(),
            resolved({2026: DRIVERS_2026}),
            Horizon(1, 4),
            ScenarioSettings("growth"),
        )
