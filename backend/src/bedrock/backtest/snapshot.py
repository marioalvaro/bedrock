"""A forecast as the rows stored for it (docs/erd/accountability.md "Stored rows"). Pure."""

import json
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from decimal import Decimal
from typing import Literal

from bedrock.forecast.engine_defaults import EngineRow
from bedrock.forecast.engines.driver import ForecastStatements
from bedrock.forecast.history import ScenarioSettings
from bedrock.forecast.resolve import ResolvedDrivers
from bedrock.statements.periods import Period

RowKind = Literal["line", "driver"]


@dataclass(frozen=True)
class ValueRow:
    """One forecast value. `horizon` is its 1-based position among the run's forecast periods of
    its frequency. Quantiles are set only on a driver an engine produced; `source` only on a
    driver."""

    kind: RowKind
    code: str
    fiscal_year: int
    fiscal_period: str
    horizon: int
    point: Decimal
    p05: Decimal | None
    p25: Decimal | None
    p50: Decimal | None
    p75: Decimal | None
    p95: Decimal | None
    source: str | None


def value_rows(
    statements: ForecastStatements,
    drivers: ResolvedDrivers,
    engines: Mapping[str, EngineRow],
    codes: Sequence[str] | None = None,
) -> list[ValueRow]:
    """The line rows (every code of `statements`, or `codes`; years, then quarters; a null value
    has no row) and then the driver rows (a flat or missing driver has none). `engines` holds the
    run's `EngineRow` per driver."""
    wanted = codes if codes is not None else tuple(dict.fromkeys(c for c, _ in statements.values))
    years = [p for p in statements.periods if p.fiscal_period == "FY"]
    quarters = [p for p in statements.periods if p.fiscal_period != "FY"]
    return [
        *_line_rows(statements, wanted, years),
        *_line_rows(statements, wanted, quarters),
        *_driver_rows(drivers, engines),
    ]


def run_meta(
    settings: ScenarioSettings, engines: Mapping[str, EngineRow], warnings: Sequence[str]
) -> str:
    """`forecast_run.engines_json`: what a stored run was made with, as sorted-key JSON."""
    return json.dumps(
        {
            "revenue_method": settings.revenue_method,
            "segment_dimension": settings.segment_dimension,
            "volume_kpi": settings.volume_kpi,
            "price_kpi": settings.price_kpi,
            "engines": {
                code: {"choice": row.choice, "used": row.used, "note": row.note}
                for code, row in engines.items()
            },
            "warnings": list(warnings),
        },
        sort_keys=True,
    )


def _line_rows(
    statements: ForecastStatements, codes: Sequence[str], periods: Sequence[Period]
) -> list[ValueRow]:
    rows = []
    for code in codes:
        for horizon, period in enumerate(periods, start=1):
            value = statements.get(code, period.key)
            if value is not None:
                rows.append(
                    ValueRow(
                        "line",
                        code,
                        period.fiscal_year,
                        period.fiscal_period,
                        horizon,
                        value,
                        None,
                        None,
                        None,
                        None,
                        None,
                        None,
                    )
                )
    return rows


def _driver_rows(drivers: ResolvedDrivers, engines: Mapping[str, EngineRow]) -> list[ValueRow]:
    rows = []
    for code in drivers.codes:
        for horizon, year in enumerate(drivers.years, start=1):
            resolved = drivers.get(code, year)
            if not isinstance(resolved.value, Decimal):
                continue
            row = engines.get(code)
            band = None
            if resolved.source == "engine" and row is not None and row.used != "mean":
                band = row.band.get(year)
            rows.append(
                ValueRow(
                    "driver",
                    code,
                    year,
                    "FY",
                    horizon,
                    resolved.value,
                    None if band is None else band.p05,
                    None if band is None else band.p25,
                    None if band is None else resolved.value,
                    None if band is None else band.p75,
                    None if band is None else band.p95,
                    resolved.source,
                )
            )
    return rows
