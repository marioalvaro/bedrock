from typing import Literal

from pydantic import BaseModel

from bedrock.services.seasonality import Seasonality


class SeasonalityLineOut(BaseModel):
    code: str
    label: str


class SeasonalityPeriodOut(BaseModel):
    fiscal_year: int
    fiscal_period: Literal["Q1", "Q2", "Q3", "Q4"]
    label: str


class SeasonalFactorOut(BaseModel):
    """`value` is the seasonal index in the line's unit; `pct` is it as a fraction of the mean
    trend of the last 12 quarters (null when that mean is 0)."""

    fiscal_period: Literal["Q1", "Q2", "Q3", "Q4"]
    value: float
    pct: float | None


class SeasonalityOut(BaseModel):
    """The components are floats over the line's latest consecutive run of quarters (statistics,
    for display only)."""

    code: str
    label: str
    lines: list[SeasonalityLineOut]
    periods: list[SeasonalityPeriodOut]
    observed: list[float]
    trend: list[float]
    seasonal: list[float]
    residual: list[float]
    factors: list[SeasonalFactorOut]
    strength: float

    @classmethod
    def from_view(cls, view: Seasonality) -> "SeasonalityOut":
        return cls(
            code=view.code,
            label=view.label,
            lines=[SeasonalityLineOut(code=x.code, label=x.label) for x in view.lines],
            periods=[
                SeasonalityPeriodOut(
                    fiscal_year=p.fiscal_year,
                    fiscal_period=p.fiscal_period,
                    label=f"{p.fiscal_period} FY{p.fiscal_year % 100:02d}",
                )
                for p in view.periods
            ],
            observed=view.observed,
            trend=view.trend,
            seasonal=view.seasonal,
            residual=view.residual,
            factors=[
                SeasonalFactorOut(
                    fiscal_period=f.fiscal_period,
                    value=f.value,
                    pct=f.pct,
                )
                for f in view.factors
            ],
            strength=view.strength,
        )
