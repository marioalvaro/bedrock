"""The Tier 1 driver model (docs/erd/forecasting.md "Tier 1 driver model (M4)"): resolved drivers
and the normalized history in, a balanced annual and quarterly IS/BS/CF forecast out. Pure,
`Decimal` throughout, no rounding."""

from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field, replace
from decimal import Decimal

from bedrock.forecast import integrity
from bedrock.forecast.drivers import segment_code
from bedrock.forecast.errors import ForecastIntegrityError, ForecastUnavailable
from bedrock.forecast.history import (
    ForecastHistory,
    ScenarioSettings,
    StatementValues,
    days,
    forecast_years,
    opening_period,
)
from bedrock.forecast.integrity import IntegrityCheck
from bedrock.forecast.resolve import ResolvedDrivers
from bedrock.statements.fiscal_grid import period_dates
from bedrock.statements.periods import Period
from bedrock.statements.rules import BALANCE_FLOOR, BALANCE_RELATIVE

CURRENT_ASSETS = (
    "cash",
    "short_term_investments",
    "receivables",
    "inventory",
    "other_current_assets",
)
NONCURRENT_ASSETS = (
    "ppe_net",
    "operating_lease_rou",
    "goodwill",
    "intangibles",
    "long_term_investments",
    "other_noncurrent_assets",
)
CURRENT_LIABILITIES = (
    "accounts_payable",
    "short_term_debt",
    "deferred_revenue_current",
    "accrued_liabilities",
    "other_current_liabilities",
)
NONCURRENT_LIABILITIES = (
    "long_term_debt",
    "operating_lease_liabilities_noncurrent",
    "other_noncurrent_liabilities",
)
PARENT_EQUITY = ("common_stock_apic", "retained_earnings", "aoci", "other_equity")
ASSETS = CURRENT_ASSETS + NONCURRENT_ASSETS
LIABILITIES = CURRENT_LIABILITIES + NONCURRENT_LIABILITIES
# The balance-sheet lines the model carries; every total is computed from them.
BALANCE_LINES = (
    CURRENT_ASSETS
    + NONCURRENT_ASSETS
    + CURRENT_LIABILITIES
    + NONCURRENT_LIABILITIES
    + ("temporary_equity",)
    + PARENT_EQUITY
    + ("nci",)
)
NOT_FORECAST = frozenset({"goodwill_impairment", "shares_issued", "treasury_shares"})
EPS = frozenset({"eps_diluted", "eps_basic"})
SHARE_LINES = ("shares_diluted", "shares_basic", "shares_outstanding")
ZERO_CF = (
    "deferred_taxes",
    "other_operating_activities",
    "acquisitions",
    "purchases_of_investments",
    "sales_maturities_of_investments",
    "other_investing_activities",
    "other_financing_activities",
    "fx_effect",
)
ZERO = Decimal(0)
YEAR_DAYS = Decimal(365)

Values = dict[str, Decimal | None]


@dataclass(frozen=True)
class Horizon:
    years: int
    quarters: int  # the quarters after the opening; the span runs on to that fiscal year's end


# Every scenario forecasts this far (user decision 2026-10-31: further adds no value).
FORECAST_HORIZON = Horizon(years=5, quarters=8)


@dataclass(frozen=True)
class Opening:
    """Where the forecast starts: the opening period's balance sheet (every line, nulls as 0,
    balanced exactly) and, for a year in progress, the flows of its actual quarters."""

    period: Period
    balance: Mapping[str, Decimal]
    year_to_date: Mapping[str, Decimal | None]


@dataclass(frozen=True)
class ForecastStatements:
    """Forecast periods (quarters and years, by end date; a year after its Q4) and every
    canonical IS/BS/CF value by (code, period key)."""

    periods: tuple[Period, ...]
    values: Mapping[tuple[str, str], Decimal | None]
    warnings: tuple[str, ...]
    opening: Opening
    flow_codes: frozenset[str]
    integrity: tuple[IntegrityCheck, ...] = ()

    def annual(self) -> list[Period]:
        return [p for p in self.periods if p.fiscal_period == "FY"]

    def quarterly(self) -> list[Period]:
        """Raises ForecastUnavailable("No quarterly history") for an annual-only company."""
        quarters = [p for p in self.periods if p.fiscal_period != "FY"]
        if not quarters:
            raise ForecastUnavailable("No quarterly history")
        return quarters

    def get(self, code: str, key: str) -> Decimal | None:
        return self.values.get((code, key))


@dataclass
class _State:
    """The balance sheet at the end of a period; the revolver sits inside short_term_debt."""

    lines: dict[str, Decimal]
    revolver: Decimal = ZERO

    @property
    def total_debt(self) -> Decimal:
        return self.lines["short_term_debt"] + self.revolver + self.lines["long_term_debt"]


class DriverModel:
    def run(
        self,
        history: ForecastHistory,
        drivers: ResolvedDrivers,
        horizon: Horizon,
        settings: ScenarioSettings,
    ) -> ForecastStatements:
        """The forecast of `horizon` from the history's opening period. `drivers` cover the
        forecast years of `horizon.years`. Raises ForecastUnavailable (a missing or out-of-bounds
        driver, no opening, missing revenue, segment or KPI data) and ForecastIntegrityError."""
        _check_drivers(drivers)
        years = forecast_years(history, horizon.years)
        if tuple(years) != drivers.years:
            raise ValueError(f"The drivers cover {drivers.years}, the forecast years are {years}")
        statements = _Run(history, drivers, settings).build(years, horizon.quarters)
        checks = integrity.check(statements)
        failed = [c.period_key for c in checks if not c.ok]
        if failed:
            raise ForecastIntegrityError(f"Integrity checks failed for {', '.join(failed)}")
        return replace(statements, integrity=tuple(checks))


def _check_drivers(drivers: ResolvedDrivers) -> None:
    missing = drivers.missing_required()
    if missing:
        raise ForecastUnavailable(f"Set these drivers: {', '.join(missing)}")
    out = drivers.out_of_bounds()
    if out:
        raise ForecastUnavailable("; ".join(f"{message} (FY{year})" for _, year, message in out))


@dataclass
class _Run:
    history: ForecastHistory
    drivers: ResolvedDrivers
    settings: ScenarioSettings
    out: dict[tuple[str, str], Decimal | None] = field(default_factory=dict)
    periods: list[Period] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

    def __post_init__(self) -> None:
        self.annual = StatementValues(self.history.annual)
        self.quarterly = StatementValues(self.history.quarterly)
        self.kinds = {
            row.code: row.kind
            for table in self.history.annual.values()
            for row in table.rows
            if not row.custom
        }
        self.flow_codes = frozenset(c for c, kind in self.kinds.items() if kind == "flow")

    def build(self, years: list[int], quarters: int) -> ForecastStatements:
        if self.history.latest_fy_end is None:
            raise ForecastUnavailable("No fiscal year to start from")
        start = opening_period(self.history)
        opening = self._opening(start)
        self.factors = self._growth_factors(years)
        span = _span(start, quarters)
        if not {y for y, _ in span} <= set(years):
            raise ValueError("The quarter span runs past the forecast years")
        state = _State(dict(opening.balance))
        for year in years:
            in_span = [q for y, q in span if y == year]
            if not in_span:
                state = self._step(self._period(year, "FY"), self._annual_revenue(year), state, 1)
                continue
            for quarter in in_span:
                revenue = self._quarter_revenue(year, quarter)
                state = self._step(self._period(year, quarter), revenue, state, 4)
            self._year_from_quarters(year)
        return ForecastStatements(
            tuple(self.periods),
            dict(self.out),
            tuple(self.warnings),
            opening,
            self.flow_codes,
        )

    # -- start -----------------------------------------------------------------------------

    def _opening(self, period: Period) -> Opening:
        """Every balance-sheet line of the opening period, a null one as 0. Each section's
        catch-all line takes the gap to the section's reported total, so the opening totals are
        the reported ones; a balance difference within tolerance goes to
        other_noncurrent_assets. Raises ForecastUnavailable when the sheet does not balance."""
        values = self.annual if period.fiscal_period == "FY" else self.quarterly

        def reported(code: str) -> Decimal | None:
            return values.get(code, period.key)

        balance = {code: reported(code) or ZERO for code in BALANCE_LINES}
        assets, equity = reported("total_assets") or ZERO, reported("total_equity") or ZERO
        temporary = balance["temporary_equity"]
        liabilities = reported("total_liabilities")
        if liabilities is None:
            liabilities = (reported("total_liabilities_and_equity") or ZERO) - temporary - equity
        parent = reported("equity_parent")
        if parent is None:
            parent = equity - balance["nci"]
        for line, total, section in (
            ("other_noncurrent_assets", assets, ASSETS),
            ("other_noncurrent_liabilities", liabilities, LIABILITIES),
            ("other_equity", parent, PARENT_EQUITY),
        ):
            balance[line] += total - sum((balance[c] for c in section), ZERO)
        difference = assets - (liabilities + temporary + equity)
        if abs(difference) > max(BALANCE_FLOOR, BALANCE_RELATIVE * abs(assets)):
            raise ForecastUnavailable(
                f"The {period.label} balance sheet does not balance (difference {difference})"
            )
        balance["other_noncurrent_assets"] -= difference
        return Opening(period, balance, self._year_to_date(period))

    def _year_to_date(self, period: Period) -> dict[str, Decimal | None]:
        """The flows of the actual quarters of a year in progress (the opening is Q1-Q3)."""
        if period.fiscal_period not in ("Q1", "Q2", "Q3"):
            return {}
        keys = [f"FY{period.fiscal_year}Q{n}" for n in range(1, int(period.fiscal_period[1]) + 1)]
        for key in keys:
            if self.quarterly.get("revenue", key) is None:
                raise ForecastUnavailable(f"No quarterly history for {_label(key)}")
        return {code: _sum(self.quarterly.get(code, k) for k in keys) for code in self.flow_codes}

    def _period(self, year: int, fiscal_period: str) -> Period:
        assert self.history.latest_fy_end is not None
        start, end = period_dates(self.history.latest_fy_end, year, fiscal_period)
        label = f"FY{year % 100:02d}E"
        if fiscal_period == "FY":
            return Period(f"FY{year}", label, year, "FY", start, end)
        return Period(
            f"FY{year}{fiscal_period}", f"{fiscal_period} {label}", year, fiscal_period, start, end
        )

    # -- lookups -----------------------------------------------------------------------------

    def _value(self, code: str, key: str) -> Decimal | None:
        """A forecast value, else the actual one."""
        if (code, key) in self.out:
            return self.out[(code, key)]
        return (self.quarterly if "Q" in key else self.annual).get(code, key)

    def _driver(self, code: str, year: int) -> Decimal:
        value = self.drivers.get(code, year).value
        if not isinstance(value, Decimal):
            raise ValueError(f"{code} FY{year} has no value")
        return value

    # -- revenue -----------------------------------------------------------------------------

    def _growth_factors(self, years: list[int]) -> dict[int, Decimal]:
        """Each forecast year's implied revenue growth factor R_y / R_{y-1} under the scenario's
        method, chained from the last actual fiscal year. Raises ForecastUnavailable."""
        method, last = self.settings.revenue_method, years[0] - 1
        if method == "growth":
            return {y: 1 + self._driver("revenue_growth", y) for y in years}
        if method == "volume_price":
            # R = k × V × P with k = revenue / (V × P) of the last actual year held, so k cancels:
            # R_y / R_{y-1} = (1 + volume growth)(1 + price growth).
            kpis = {s.metric: s for s in self.history.segment_series if s.dimension == "kpi"}
            for code in (self.settings.volume_kpi, self.settings.price_kpi):
                if code not in kpis or kpis[code].fy_values.get(last) is None:
                    raise ForecastUnavailable(f"KPI {code} has no FY{last} value")
            return {
                y: (1 + self._driver("volume_growth", y)) * (1 + self._driver("price_growth", y))
                for y in years
            }
        return self._segment_factors(years, last)

    def _segment_factors(self, years: list[int], last: int) -> dict[int, Decimal]:
        """S_y = S_{y-1} × (1 + segment growth) for each revenue series of the dimension;
        R_y = sum S_y / (1 - u), with u the Unallocated share of the last actual year's revenue."""
        dimension = self.settings.segment_dimension
        segments: dict[int, Decimal] = {}
        for s in self.history.segment_series:
            if s.dimension != dimension or s.metric != "revenue":
                continue
            value = s.fy_values.get(last)
            if value is None:
                raise ForecastUnavailable(f"Segment {s.name} has no FY{last} value")
            segments[s.id] = value
        revenue = self.annual.get("revenue", f"FY{last}")
        if revenue is None or revenue == 0:
            raise ForecastUnavailable(f"No FY{last} revenue to start from")
        unallocated = (revenue - sum(segments.values(), ZERO)) / revenue
        if unallocated >= 1:
            raise ForecastUnavailable(f"The {dimension} segments have no FY{last} revenue")
        factors, previous = {}, revenue
        for y in years:
            for id_ in segments:
                segments[id_] *= 1 + self._driver(segment_code(id_), y)
            current = sum(segments.values(), ZERO) / (1 - unallocated)
            factors[y] = current / previous
            previous = current
        return factors

    def _quarter_revenue(self, year: int, quarter: str) -> Decimal:
        """The same quarter one year earlier × the year's implied growth."""
        key = f"FY{year - 1}{quarter}"
        previous = self._value("revenue", key)
        if previous is None:
            raise ForecastUnavailable(f"No quarterly history for {_label(key)}")
        return previous * self.factors[year]

    def _year_from_quarters(self, year: int) -> None:
        """Flows are Q1 + ... + Q4 (actual quarters included), instants Q4's, average shares the
        mean of the quarters, EPS NI common / shares."""
        keys = [f"FY{year}Q{n}" for n in range(1, 5)]
        values: Values = {}
        for code, kind in self.kinds.items():
            quarters = [self._value(code, k) for k in keys]
            if code in NOT_FORECAST or code in EPS:
                values[code] = None
            elif kind == "flow":
                values[code] = _sum(quarters)
            elif kind == "average":
                found = [v for v in quarters if v is not None]
                values[code] = sum(found, ZERO) / len(found) if found else None
            else:
                values[code] = quarters[-1]
        net_common = values["net_income_common"] or ZERO
        values["eps_diluted"] = _per_share(net_common, values["shares_diluted"])
        values["eps_basic"] = _per_share(net_common, values["shares_basic"])
        self._put(self._period(year, "FY"), values)

    def _annual_revenue(self, year: int) -> Decimal:
        previous = self._value("revenue", f"FY{year - 1}")
        if previous is None:
            raise ForecastUnavailable(f"No FY{year - 1} revenue to start from")
        return previous * self.factors[year]

    # -- one period --------------------------------------------------------------------------

    def _step(self, period: Period, revenue: Decimal, opening: _State, share: int) -> _State:
        """Forecast one period from the opening state; `share` is the number of periods the
        year's amounts (debt, buybacks) are split over."""
        year = period.fiscal_year

        def driver(code: str) -> Decimal:
            return self._driver(code, year)

        period_days = Decimal(days(period))
        lines = dict(opening.lines)

        cost = revenue * (1 - driver("gross_margin"))
        gross = revenue - cost
        rnd = revenue * driver("rnd_pct_revenue")
        sga = revenue * driver("sga_pct_revenue")
        other_opex = revenue * driver("other_opex_pct_revenue")
        operating = gross - rnd - sga - other_opex
        interest = driver("interest_rate") * opening.total_debt * period_days / YEAR_DAYS
        nonoperating = revenue * driver("other_nonoperating_pct_revenue")
        pretax = operating - interest + nonoperating
        tax = pretax * driver("tax_rate")
        net = pretax - tax
        net_nci = net * driver("nci_share")
        net_common = net - net_nci

        lines["receivables"] = self._days("receivable_days", year, revenue, period_days, lines)
        lines["inventory"] = self._days("inventory_days", year, cost, period_days, lines)
        lines["accounts_payable"] = self._days("payable_days", year, cost, period_days, lines)

        capex = revenue * driver("capex_pct_revenue")
        d_and_a = revenue * driver("d_and_a_pct_revenue")
        sbc = revenue * driver("sbc_pct_revenue")
        lines["ppe_net"] += capex - d_and_a

        issued = driver("debt_issued") / share
        repaid = driver("debt_repaid") / share
        if repaid > max(lines["long_term_debt"], ZERO):
            repaid = max(lines["long_term_debt"], ZERO)
            self.warnings.append(
                f"{period.label}: debt_repaid is capped at the opening long-term debt"
            )
        lines["long_term_debt"] += issued - repaid
        buybacks = driver("buybacks") / share
        dividends = driver("dividend_payout") * max(net_common, ZERO)

        lines["common_stock_apic"] += sbc
        lines["retained_earnings"] += net_common - dividends - buybacks
        lines["nci"] += net_nci

        change_receivables = opening.lines["receivables"] - lines["receivables"]
        change_inventory = opening.lines["inventory"] - lines["inventory"]
        change_payables = lines["accounts_payable"] - opening.lines["accounts_payable"]
        cfo = net + d_and_a + sbc + change_receivables + change_inventory + change_payables
        cfi = -capex
        cash = opening.lines["cash"] + cfo + cfi + issued - repaid - buybacks - dividends

        min_cash = driver("min_cash")
        draw = repay = ZERO
        if cash < min_cash:
            draw = min_cash - cash
        elif opening.revolver > 0:
            repay = min(opening.revolver, cash - min_cash)
        lines["cash"] = cash + draw - repay
        revolver = opening.revolver + draw - repay
        cff = issued + draw - repaid - repay - buybacks - dividends

        shares = {code: self._shares(code, period) for code in SHARE_LINES}
        values: Values = dict.fromkeys(self.kinds)
        values.update(
            revenue=revenue,
            cost_of_revenue=cost,
            gross_profit=gross,
            rnd=rnd,
            sga=sga,
            other_operating_expenses=other_opex,
            total_operating_costs=rnd + sga + other_opex,
            operating_income=operating,
            interest_expense=interest,
            other_nonoperating_income=nonoperating,
            pretax_income=pretax,
            income_tax=tax,
            net_income=net,
            net_income_nci=net_nci,
            net_income_common=net_common,
            eps_diluted=_per_share(net_common, shares["shares_diluted"]),
            eps_basic=_per_share(net_common, shares["shares_basic"]),
            dividends_per_share=_per_share(dividends, shares["shares_basic"]),
            cf_net_income=net,
            d_and_a=d_and_a,
            sbc=sbc,
            change_receivables=change_receivables,
            change_inventory=change_inventory,
            change_payables=change_payables,
            cfo=cfo,
            capex=-capex,
            cfi=cfi,
            debt_issued=issued + draw,
            debt_repaid=-(repaid + repay),
            buybacks=-buybacks,
            dividends_paid=-dividends,
            cff=cff,
            net_change_in_cash=cfo + cfi + cff,
            free_cash_flow=cfo - capex,
            **shares,
        )
        values.update(dict.fromkeys(ZERO_CF, ZERO))
        state = _State(lines, revolver)
        values.update(_balance_sheet(state))
        self._put(period, values)
        return state

    def _days(
        self, code: str, year: int, base: Decimal, period_days: Decimal, lines: dict[str, Decimal]
    ) -> Decimal:
        line = {"receivable_days": "receivables", "inventory_days": "inventory"}.get(
            code, "accounts_payable"
        )
        value = self.drivers.get(code, year).value
        if not isinstance(value, Decimal):  # flat: held at its opening value
            return lines[line]
        return base * value / period_days

    def _shares(self, code: str, period: Period) -> Decimal | None:
        """The same period one year earlier × (1 + share_change); a missing base value is held
        at the latest non-null one."""
        suffix = "" if period.fiscal_period == "FY" else period.fiscal_period
        base = self._value(code, f"FY{period.fiscal_year - 1}{suffix}")
        if base is None:
            base = self._latest(code, period.fiscal_period == "FY")
        return (
            None if base is None else base * (1 + self._driver("share_change", period.fiscal_year))
        )

    def _latest(self, code: str, annual: bool) -> Decimal | None:
        history = self.annual if annual else self.quarterly
        forecast = [p for p in self.periods if (p.fiscal_period == "FY") == annual]
        for period in reversed([*history.periods, *forecast]):
            value = self._value(code, period.key)
            if value is not None:
                return value
        return None

    def _put(self, period: Period, values: Values) -> None:
        self.periods.append(period)
        for code, value in values.items():
            self.out[(code, period.key)] = value


def _span(opening: Period, quarters: int) -> list[tuple[int, str]]:
    """The `quarters` quarters after the opening, extended to the end of that fiscal year; none
    after an annual opening."""
    if opening.fiscal_period == "FY":
        return []
    year, number = opening.fiscal_year, int(opening.fiscal_period[1])
    span: list[tuple[int, str]] = []
    while len(span) < quarters or number < 4:
        year, number = (year + 1, 1) if number == 4 else (year, number + 1)
        span.append((year, f"Q{number}"))
    return span


def _sum(values: Iterable[Decimal | None]) -> Decimal | None:
    """None when every value is None; a None among values counts as 0."""
    found = [v for v in values if v is not None]
    return sum(found, ZERO) if found else None


def _label(key: str) -> str:
    year = int(key[2:6])
    return f"{key[6:]} FY{year % 100:02d}"


def _balance_sheet(state: _State) -> Values:
    lines: Values = {**state.lines}
    lines["short_term_debt"] = state.lines["short_term_debt"] + state.revolver

    def total(codes: tuple[str, ...]) -> Decimal:
        return sum((lines[c] or ZERO for c in codes), ZERO)

    current_assets, noncurrent_assets = total(CURRENT_ASSETS), total(NONCURRENT_ASSETS)
    current_liabilities = total(CURRENT_LIABILITIES)
    noncurrent_liabilities = total(NONCURRENT_LIABILITIES)
    parent = total(PARENT_EQUITY)
    equity = parent + state.lines["nci"]
    liabilities = current_liabilities + noncurrent_liabilities
    debt = state.total_debt
    return {
        **lines,
        "total_current_assets": current_assets,
        "total_noncurrent_assets": noncurrent_assets,
        "total_assets": current_assets + noncurrent_assets,
        "total_current_liabilities": current_liabilities,
        "total_noncurrent_liabilities": noncurrent_liabilities,
        "total_liabilities": liabilities,
        "equity_parent": parent,
        "total_equity": equity,
        "total_liabilities_and_equity": liabilities + state.lines["temporary_equity"] + equity,
        "total_debt": debt,
        "net_debt": debt - state.lines["cash"] - state.lines["short_term_investments"],
    }


def _per_share(amount: Decimal, shares: Decimal | None) -> Decimal | None:
    return None if shares is None or shares == 0 else amount / shares
