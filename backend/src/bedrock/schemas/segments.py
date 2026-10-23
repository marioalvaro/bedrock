from datetime import date
from decimal import Decimal
from typing import Literal

from pydantic import BaseModel

from bedrock.models.segment_series import SegmentSeries
from bedrock.statements.segments import SegmentGrid

Dimension = Literal["business", "geo", "kpi"]
SegmentUnit = Literal["USD", "pct", "count", "USD_per_unit"]
Scale = Literal["units", "K", "M", "B"]
FiscalPeriod = Literal["FY", "Q1", "Q2", "Q3", "Q4"]


class SegmentPeriodOut(BaseModel):
    """Like `PeriodOut`, but the dates are null for a period that has only segment values."""

    key: str
    label: str
    fiscal_year: int
    fiscal_period: str
    period_start: date | None
    period_end: date | None
    is_forecast: bool


class SegmentSeriesRowOut(BaseModel):
    id: int
    name: str
    metric: str
    unit: str
    display_order: int
    values: list[Decimal | None]  # aligned with `periods`


class SegmentBlockOut(BaseModel):
    dimension: str
    metric: str | None
    series: list[SegmentSeriesRowOut]
    unallocated: list[Decimal | None] | None


class SegmentsOut(BaseModel):
    ticker: str
    freq: str
    periods: list[SegmentPeriodOut]
    blocks: list[SegmentBlockOut]

    @classmethod
    def from_grid(cls, grid: SegmentGrid, ticker: str) -> "SegmentsOut":
        return cls(
            ticker=ticker,
            freq=grid.freq,
            periods=[
                SegmentPeriodOut(
                    key=p.key,
                    label=p.label,
                    fiscal_year=p.fiscal_year,
                    fiscal_period=p.fiscal_period,
                    period_start=p.start,
                    period_end=p.end,
                    is_forecast=False,
                )
                for p in grid.periods
            ],
            blocks=[
                SegmentBlockOut(
                    dimension=b.dimension,
                    metric=b.metric,
                    series=[
                        SegmentSeriesRowOut(
                            id=s.id,
                            name=s.name,
                            metric=s.metric,
                            unit=s.unit,
                            display_order=s.display_order,
                            values=s.values,
                        )
                        for s in b.series
                    ],
                    unallocated=b.unallocated,
                )
                for b in grid.blocks
            ],
        )


class SegmentSeriesIn(BaseModel):
    dimension: Dimension
    name: str
    metric: str
    unit: SegmentUnit


class SegmentSeriesUpdate(BaseModel):
    """Dimension, metric and unit are fixed once created."""

    name: str
    display_order: int


class SegmentSeriesOut(BaseModel):
    id: int
    dimension: str
    name: str
    metric: str
    unit: str
    display_order: int

    @classmethod
    def from_model(cls, series: SegmentSeries) -> "SegmentSeriesOut":
        return cls(
            id=series.id,
            dimension=series.dimension,
            name=series.name,
            metric=series.metric,
            unit=series.unit,
            display_order=series.display_order,
        )


class SegmentValueIn(BaseModel):
    fiscal_year: int
    fiscal_period: FiscalPeriod
    value: Decimal | None  # null deletes the stored value


class SegmentValuesIn(BaseModel):
    values: list[SegmentValueIn]


class SegmentImportIn(BaseModel):
    dimension: Dimension
    text: str
    scale: Scale


class SegmentImportOut(BaseModel):
    series_created: int
    values_created: int
    values_updated: int


class FillAnnualIn(BaseModel):
    """`dry_run` counts what would change and writes nothing."""

    dry_run: bool = False


class FillAnnualOut(BaseModel):
    values_created: int
    values_overwritten: int  # a stored FY value that differs from the sum of its quarters
    values_unchanged: int  # a stored FY value already equal to that sum


class ImportIssueOut(BaseModel):
    """One entry of the 422 body's `errors`; documented here for the OpenAPI client."""

    row: int
    column: int | None
    message: str


class ImportErrorOut(BaseModel):
    detail: str
    errors: list[ImportIssueOut]
