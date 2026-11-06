from datetime import date
from decimal import Decimal
from typing import Literal

from pydantic import BaseModel, ConfigDict

from bedrock.models.scenario import Case
from bedrock.services.sensitivity import GridAxis, GridResult, TornadoResult
from bedrock.services.valuation import (
    CaseValuation,
    InputsView,
    ScenarioSummary,
)
from bedrock.valuation.interface import (
    DcfDetails,
    MultipleDetails,
    ValuationResult,
)
from bedrock.valuation.sensitivity import TornadoBar


class ForecastYearOut(BaseModel):
    index: int
    fiscal_year: int
    label: str


class ValuationInputRowOut(BaseModel):
    code: str
    label: str
    group: str
    unit: str | None
    kind: str
    choices: list[str] | None
    value: str | None  # the resolved value as text
    source: Literal["own", "base", "default", "derived"]
    own: str | None  # the case's stored text
    note: str | None


class ValuationInputsOut(BaseModel):
    scenario_id: int
    case: Case
    forecast_years: list[ForecastYearOut]
    rows: list[ValuationInputRowOut]
    warnings: list[str]

    @classmethod
    def from_view(cls, view: InputsView) -> "ValuationInputsOut":
        return cls(
            scenario_id=view.scenario_id,
            case=view.case,
            forecast_years=[ForecastYearOut(**vars(y)) for y in view.forecast_years],
            rows=[
                ValuationInputRowOut(
                    **{**vars(r), "choices": None if r.choices is None else list(r.choices)}
                )
                for r in view.rows
            ],
            warnings=view.warnings,
        )


class ValuationInputIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    code: str
    value: str | None  # null deletes the case's own value


class ValuationInputsIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    rows: list[ValuationInputIn]


class BridgeOut(BaseModel):
    total_debt: Decimal
    cash: Decimal
    short_term_investments: Decimal
    minority_interest: Decimal
    temporary_equity: Decimal
    net_claims: Decimal


class DiscountOut(BaseModel):
    method: str
    rate: Decimal
    cost_of_equity: Decimal | None
    after_tax_cost_of_debt: Decimal | None
    risk_free_rate: Decimal | None
    equity_risk_premium: Decimal | None
    beta: Decimal | None
    cost_of_debt: Decimal | None
    tax_rate: Decimal | None
    debt_weight: Decimal | None
    equity_weight: Decimal | None


class DcfPeriodOut(BaseModel):
    period_key: str
    label: str
    start: date
    end: date
    stub: bool
    nopat: Decimal
    d_and_a: Decimal
    change_working_capital: Decimal
    capex: Decimal
    fcff: Decimal
    years: Decimal
    discount_factor: Decimal
    present_value: Decimal


class TerminalOut(BaseModel):
    method: str
    growth: Decimal | None
    exit_multiple: Decimal | None
    base_fcff: Decimal
    base_ebitda: Decimal
    value: Decimal
    years: Decimal
    discount_factor: Decimal
    present_value: Decimal
    implied_exit_multiple: Decimal | None
    implied_growth: Decimal | None


class DcfOut(BaseModel):
    valuation_date: date
    discount: DiscountOut
    mid_year: bool
    periods: list[DcfPeriodOut]
    terminal: TerminalOut
    sum_present_value: Decimal
    terminal_share: Decimal | None


class CompsSetRefOut(BaseModel):
    id: int
    name: str


class MultipleOut(BaseModel):
    ratio_code: str
    metric_label: str
    fiscal_year: int
    period_label: str
    metric_value: Decimal
    multiple: Decimal
    source: str
    percentile: Decimal | None
    n: int | None
    comps_set: CompsSetRefOut | None


class ValuationResultOut(BaseModel):
    key: str
    method: str
    label: str
    enterprise_value: Decimal | None
    equity_value: Decimal | None
    value_per_share: Decimal | None
    upside: Decimal | None
    caveat: str | None
    error: str | None
    dcf: DcfOut | None
    multiple: MultipleOut | None

    @classmethod
    def from_result(cls, result: ValuationResult, caveat: str | None) -> "ValuationResultOut":
        details = result.details
        return cls(
            key=result.key,
            method=result.method,
            label=result.label,
            enterprise_value=result.enterprise_value,
            equity_value=result.equity_value,
            value_per_share=result.value_per_share,
            upside=result.upside,
            caveat=caveat,
            error=result.error,
            dcf=DcfOut.model_validate(details, from_attributes=True)
            if isinstance(details, DcfDetails)
            else None,
            multiple=_multiple(details) if isinstance(details, MultipleDetails) else None,
        )


def _multiple(details: MultipleDetails) -> MultipleOut:
    fields = {k: v for k, v in vars(details).items() if k != "comps_set"}
    reference = None
    if details.comps_set is not None:
        reference = CompsSetRefOut(id=details.comps_set[0], name=details.comps_set[1])
    return MultipleOut(**fields, comps_set=reference)


class ValuationOut(BaseModel):
    scenario_id: int
    case: Case
    price: Decimal | None
    price_date: date | None
    valuation_date: date | None
    shares: Decimal | None
    bridge: BridgeOut
    results: list[ValuationResultOut]
    warnings: list[str]

    @classmethod
    def from_valuation(cls, valuation: CaseValuation) -> "ValuationOut":
        market = valuation.market
        return cls(
            scenario_id=valuation.scenario_id,
            case=valuation.case,
            price=market.price,
            price_date=market.price_date,
            valuation_date=valuation.valuation_date,
            shares=market.shares,
            bridge=BridgeOut(**vars(market.bridge), net_claims=market.bridge.net_claims),
            results=[
                ValuationResultOut.from_result(r, valuation.caveats.get(r.key))
                for r in valuation.results
            ],
            warnings=valuation.warnings,
        )


class SummaryMethodOut(BaseModel):
    key: str
    label: str


class SummaryCaseOut(BaseModel):
    case: Case
    label: str  # Base | Bull | Bear
    value_per_share: dict[str, Decimal | None]
    upside: dict[str, Decimal | None]
    errors: dict[str, str]
    error: str | None  # the case's forecast cannot run


class ValuationSummaryOut(BaseModel):
    scenario_id: int
    price: Decimal | None
    price_date: date | None
    methods: list[SummaryMethodOut]
    cases: list[SummaryCaseOut]

    @classmethod
    def from_summary(cls, summary: ScenarioSummary) -> "ValuationSummaryOut":
        return cls(
            scenario_id=summary.scenario_id,
            price=summary.price,
            price_date=summary.price_date,
            methods=[SummaryMethodOut(key=m.key, label=m.label) for m in summary.methods],
            cases=[
                SummaryCaseOut(
                    case=c.case,
                    label=c.case.capitalize(),
                    value_per_share=c.value_per_share,
                    upside=c.upside,
                    errors=c.errors,
                    error=c.error,
                )
                for c in summary.cases
            ],
        )


class TornadoBarOut(BaseModel):
    code: str
    label: str
    kind: str
    unit: str
    step: Decimal
    mode: str
    low_value: Decimal | None
    high_value: Decimal | None
    low_change: Decimal | None
    high_change: Decimal | None
    range: Decimal | None
    error: str | None

    @classmethod
    def from_bar(cls, bar: TornadoBar) -> "TornadoBarOut":
        return cls(**vars(bar))


class TornadoOut(BaseModel):
    scenario_id: int
    case: Case
    base_value: Decimal
    price: Decimal | None
    bars: list[TornadoBarOut]

    @classmethod
    def from_result(cls, result: TornadoResult) -> "TornadoOut":
        return cls(
            scenario_id=result.scenario_id,
            case=result.case,
            base_value=result.base_value,
            price=result.price,
            bars=[TornadoBarOut.from_bar(b) for b in result.bars],
        )


class GridAxisOut(BaseModel):
    code: str
    label: str
    unit: str
    step: Decimal
    mode: str
    shifts: list[Decimal]
    points: list[Decimal | None]

    @classmethod
    def from_axis(cls, axis: GridAxis) -> "GridAxisOut":
        item = axis.item
        return cls(
            code=item.code,
            label=item.label,
            unit=item.unit,
            step=item.step,
            mode=item.mode,
            shifts=list(axis.shifts),
            points=list(axis.points),
        )


class SensitivityGridOut(BaseModel):
    scenario_id: int
    case: Case
    base_value: Decimal
    price: Decimal | None
    x: GridAxisOut
    y: GridAxisOut
    values: list[list[Decimal | None]]  # [y point][x point]
    upside: list[list[Decimal | None]]
    errors: list[list[str | None]]

    @classmethod
    def from_result(cls, result: GridResult) -> "SensitivityGridOut":
        grid = result.grid
        return cls(
            scenario_id=result.scenario_id,
            case=result.case,
            base_value=result.base_value,
            price=result.price,
            x=GridAxisOut.from_axis(result.x),
            y=GridAxisOut.from_axis(result.y),
            values=[list(r) for r in grid.values],
            upside=[list(r) for r in grid.upside],
            errors=[list(r) for r in grid.errors],
        )
