from decimal import Decimal
from typing import Literal

from pydantic import BaseModel

from bedrock.schemas.statements import PeriodOut, StatementOut
from bedrock.services.forecasts import Comparison, Forecast


class IntegrityOut(BaseModel):
    """One forecast period's checks (USD differences); `ok` when each is within 0.01 USD."""

    period_key: str
    balance_diff: Decimal
    cash_diff: Decimal
    re_diff: Decimal
    quarters_diff: Decimal | None  # an FY built from quarters only
    ok: bool


class ForecastOut(StatementOut):
    """The statement payload with the actual periods then the forecast ones (`is_forecast`)."""

    scenario_id: int
    warnings: list[str]
    integrity: list[IntegrityOut]

    @classmethod
    def from_forecast(
        cls,
        forecast: Forecast,
        *,
        ticker: str,
        statement: Literal["IS", "BS", "CF"],
        freq: Literal["annual", "quarterly"],
        currency: str,
        scenario_id: int,
    ) -> "ForecastOut":
        base = StatementOut.from_table(
            forecast.table,
            ticker=ticker,
            statement=statement,
            freq=freq,
            basis="normalized",
            currency=currency,
            forecast_keys=forecast.forecast_keys,
        )
        return cls(
            **dict(base),
            scenario_id=scenario_id,
            warnings=forecast.warnings,
            integrity=[
                IntegrityOut(
                    period_key=c.period_key,
                    balance_diff=c.balance_diff,
                    cash_diff=c.cash_diff,
                    re_diff=c.re_diff,
                    quarters_diff=c.quarters_diff,
                    ok=c.ok,
                )
                for c in forecast.integrity
            ],
        )


class CompareCodeOut(BaseModel):
    code: str
    label: str
    unit: str


class ComparedScenarioOut(BaseModel):
    id: int
    name: str
    values: dict[str, list[Decimal | None]]  # by code, aligned with `periods`; empty on error
    error: str | None  # why the scenario's forecast cannot run


class CompareOut(BaseModel):
    periods: list[PeriodOut]  # forecast periods only
    codes: list[CompareCodeOut]
    scenarios: list[ComparedScenarioOut]

    @classmethod
    def from_comparison(cls, comparison: Comparison) -> "CompareOut":
        return cls(
            periods=[PeriodOut.from_period(p, is_forecast=True) for p in comparison.periods],
            codes=[
                CompareCodeOut(code=c.code, label=c.label, unit=c.unit) for c in comparison.codes
            ],
            scenarios=[
                ComparedScenarioOut(id=s.id, name=s.name, values=s.values, error=s.error)
                for s in comparison.scenarios
            ],
        )
