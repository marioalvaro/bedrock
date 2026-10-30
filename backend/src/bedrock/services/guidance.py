"""The guidance log of a followed company: entries judged against actuals (FR-ANL-09)."""

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, date, datetime
from decimal import Decimal
from typing import Literal, cast

from sqlalchemy.orm import Session

from bedrock.analysis.guidance import (
    LOWER_IS_BETTER,
    QUARTER_RATIOS,
    ActualKey,
    Basis,
    Direction,
    GuidanceEntry,
    GuidanceResult,
    GuidanceSummary,
    evaluate,
    quarter_margin,
    summarize,
)
from bedrock.models.company import Company
from bedrock.models.guidance import Guidance
from bedrock.ratios.calculator import compute_ratios
from bedrock.ratios.registry import RATIOS
from bedrock.repositories import guidance as repo
from bedrock.repositories import segments as segments_repo
from bedrock.services import ratios as ratios_service
from bedrock.services.adjustments import AMOUNT_LIMIT
from bedrock.services.errors import GuidanceNotFound, InvalidGuidance
from bedrock.services.statements import canonical_items, statement_tables
from bedrock.statements.build import StatementTable

__all__ = [
    "GuidanceInput",
    "GuidanceLog",
    "LoggedEntry",
    "MetricChoice",
    "create_entry",
    "delete_entry",
    "guidance_log",
    "metric_choices",
    "update_entry",
]

KPI_PREFIX = "kpi:"
YEAR_RANGE = (1000, 9999)  # four digits, as the segment import grammar
_PERIOD_ORDER = {"FY": 0, "Q1": 1, "Q2": 2, "Q3": 3, "Q4": 4}

Group = Literal["line", "ratio", "kpi"]
# (code, fiscal_year, fiscal_period) -> value, for the lines of the statement tables read
_LineValues = dict[tuple[str, int, str], Decimal | None]


@dataclass(frozen=True)
class GuidanceInput:
    metric: str
    fiscal_year: int
    fiscal_period: str
    low: Decimal
    high: Decimal
    basis: Basis
    direction: Direction | None  # None: the metric's default
    given_on: date
    source_note: str | None


@dataclass(frozen=True)
class MetricChoice:
    metric: str
    label: str
    group: Group
    unit: str
    default_direction: Direction
    quarterly: bool  # may be guided on a quarter


@dataclass(frozen=True)
class LoggedEntry:
    stored: Guidance
    label: str
    unit: str | None  # None when the metric is a KPI whose series no longer exists
    result: GuidanceResult


@dataclass(frozen=True)
class GuidanceLog:
    entries: list[LoggedEntry]  # by fiscal year, period (FY first), metric, given_on, id
    summary: GuidanceSummary
    labels: dict[str, str]  # metric -> label, for `summary.by_metric`


def metric_choices(session: Session, company: Company) -> list[MetricChoice]:
    """Every metric the company can be guided on: the statement lines, then the ratios that are
    not also a line (`eps_diluted` is the line), then the company's KPIs. A quarter takes lines,
    KPIs and the margins of `QUARTER_RATIOS`."""
    lines = [
        MetricChoice(i.code, i.label, "line", i.unit, _default_direction(i.code), True)
        for i in canonical_items()
    ]
    taken = {c.metric for c in lines}
    ratios = [
        MetricChoice(
            r.code, r.label, "ratio", r.unit, _default_direction(r.code), r.code in QUARTER_RATIOS
        )
        for r in RATIOS
        if r.code not in taken
    ]
    kpis = [
        MetricChoice(f"{KPI_PREFIX}{s.metric}", s.name, "kpi", s.unit, "higher", True)
        for s in segments_repo.list_series(session, company.id)
        if s.dimension == "kpi"
    ]
    return [*lines, *ratios, *kpis]


def guidance_log(session: Session, company: Company) -> GuidanceLog:
    """Every entry of the company judged against its actual, with the hit/miss summary of the
    latest entries. One statement load per basis and frequency in use."""
    return _log(session, company, repo.list_for(session, company.id))


def create_entry(
    session: Session, company: Company, data: GuidanceInput, now: datetime
) -> LoggedEntry:
    """Validates, stores and commits; returns the entry judged. Raises InvalidGuidance for an
    unknown metric (or KPI), a quarter on a metric that has no quarterly value, a year out of
    range, a non-finite or out-of-range (`AMOUNT_LIMIT`, G21) value, or low > high."""
    _validate(session, company, data)
    stamp = _naive_utc(now)
    added = repo.add(
        session,
        Guidance(company_id=company.id, created_at=stamp, updated_at=stamp, **_fields(data)),
    )
    entry_id = added.id
    session.commit()
    return _logged(session, company, entry_id)


def update_entry(
    session: Session, company: Company, guidance_id: int, data: GuidanceInput, now: datetime
) -> LoggedEntry:
    """Replaces the entry's fields under the rules of `create_entry`. Raises GuidanceNotFound
    for an unknown id (or another company's)."""
    stored = _stored(session, company, guidance_id)
    _validate(session, company, data)
    for name, value in _fields(data).items():
        setattr(stored, name, value)
    stored.updated_at = _naive_utc(now)
    session.commit()
    return _logged(session, company, guidance_id)


def delete_entry(session: Session, company: Company, guidance_id: int) -> None:
    repo.delete(session, _stored(session, company, guidance_id))
    session.commit()


def _logged(session: Session, company: Company, guidance_id: int) -> LoggedEntry:
    """One entry of the committed log (its `latest` depends on the other entries of its key)."""
    return next(e for e in guidance_log(session, company).entries if e.stored.id == guidance_id)


def _log(session: Session, company: Company, stored: Sequence[Guidance]) -> GuidanceLog:
    catalogue = {c.metric: c for c in metric_choices(session, company)}
    ordered = sorted(
        stored,
        key=lambda g: (g.fiscal_year, _PERIOD_ORDER[g.fiscal_period], g.metric, g.given_on, g.id),
    )
    results = evaluate(
        [_entry(g) for g in ordered],
        _actuals(session, company, ordered, catalogue),
    )
    entries = []
    for g, result in zip(ordered, results, strict=True):
        choice = catalogue.get(g.metric)
        entries.append(
            LoggedEntry(
                g,
                g.metric if choice is None else choice.label,
                None if choice is None else choice.unit,
                result,
            )
        )
    labels = {e.stored.metric: e.label for e in entries}
    return GuidanceLog(entries, summarize(results), labels)


def _entry(stored: Guidance) -> GuidanceEntry:
    return GuidanceEntry(
        id=stored.id,
        metric=stored.metric,
        fiscal_year=stored.fiscal_year,
        fiscal_period=stored.fiscal_period,
        low=stored.low,
        high=stored.high,
        basis=cast(Basis, stored.basis),
        direction=cast(Direction, stored.direction),
        given_on=stored.given_on,
    )


def _actuals(
    session: Session,
    company: Company,
    stored: Sequence[Guidance],
    catalogue: Mapping[str, MetricChoice],
) -> dict[ActualKey, Decimal | None]:
    """The actual of every entry, keyed as `evaluate` reads them. KPI values do not depend on
    the basis; a metric missing from the catalogue (a deleted KPI) has none."""
    actuals: dict[ActualKey, Decimal | None] = {}
    kpis = (
        _kpi_values(session, company)
        if any(g.metric.startswith(KPI_PREFIX) for g in stored)
        else {}
    )
    for g in stored:
        if g.metric.startswith(KPI_PREFIX):
            actuals[(cast(Basis, g.basis), g.metric, g.fiscal_year, g.fiscal_period)] = kpis.get(
                (g.metric.removeprefix(KPI_PREFIX), g.fiscal_year, g.fiscal_period)
            )
    bases: tuple[Basis, ...] = ("reported", "normalized")
    for basis in bases:
        mine = [g for g in stored if g.basis == basis and g.metric in catalogue]
        mine = [g for g in mine if catalogue[g.metric].group != "kpi"]
        if any(g.fiscal_period == "FY" for g in mine):
            inputs = ratios_service.ratio_inputs(session, company, "annual", basis)
            lines = _line_values([inputs.income, inputs.cash_flow, inputs.balance])
            table = compute_ratios(inputs, "annual")
            ratio_values: _LineValues = {
                (row.code, p.fiscal_year, p.fiscal_period): v
                for row in table.rows
                for p, v in zip(table.periods, row.values, strict=True)
            }
            for g in mine:
                if g.fiscal_period == "FY":
                    source = ratio_values if catalogue[g.metric].group == "ratio" else lines
                    actuals[(basis, g.metric, g.fiscal_year, "FY")] = source.get(
                        (g.metric, g.fiscal_year, "FY")
                    )
        if any(g.fiscal_period != "FY" for g in mine):
            tables = statement_tables(
                session,
                company,
                [("IS", "quarterly"), ("CF", "quarterly"), ("BS", "quarterly")],
                basis,
            )
            lines = _line_values(list(tables.values()))
            for g in mine:
                if g.fiscal_period == "FY":
                    continue
                key = (basis, g.metric, g.fiscal_year, g.fiscal_period)
                if catalogue[g.metric].group == "ratio":
                    operands = {
                        code: lines.get((code, g.fiscal_year, g.fiscal_period))
                        for code in ("revenue", *QUARTER_RATIOS[g.metric])
                    }
                    actuals[key] = quarter_margin(g.metric, operands)
                else:
                    actuals[key] = lines.get((g.metric, g.fiscal_year, g.fiscal_period))
    return actuals


def _line_values(tables: Sequence[StatementTable]) -> _LineValues:
    return {
        (row.code, p.fiscal_year, p.fiscal_period): v
        for table in tables
        for row in table.rows
        for p, v in zip(table.periods, row.values, strict=True)
    }


def _kpi_values(session: Session, company: Company) -> _LineValues:
    """(KPI code, fiscal_year, fiscal_period) -> value over the company's KPI series."""
    series = {
        s.id: s.metric
        for s in segments_repo.list_series(session, company.id)
        if s.dimension == "kpi"
    }
    return {
        (series[v.series_id], v.fiscal_year, v.fiscal_period): v.value
        for v in segments_repo.list_values(session, list(series))
    }


def _validate(session: Session, company: Company, data: GuidanceInput) -> None:
    choice = next((c for c in metric_choices(session, company) if c.metric == data.metric), None)
    if choice is None:
        what = "KPI" if data.metric.startswith(KPI_PREFIX) else "metric"
        raise InvalidGuidance(f"Unknown {what} {data.metric!r}")
    if data.fiscal_period != "FY" and not choice.quarterly:
        raise InvalidGuidance(
            f"{data.metric} can be guided on a full year only; a quarter takes statement lines, "
            f"KPIs and the margins {sorted(QUARTER_RATIOS)}"
        )
    if not YEAR_RANGE[0] <= data.fiscal_year <= YEAR_RANGE[1]:
        raise InvalidGuidance(
            f"The fiscal year must be between {YEAR_RANGE[0]} and {YEAR_RANGE[1]}"
        )
    for name, value in (("low", data.low), ("high", data.high)):
        if not value.is_finite():
            raise InvalidGuidance(f"The {name} value must be a finite number")
        if abs(value) >= AMOUNT_LIMIT:
            raise InvalidGuidance(
                f"The {name} value is too large: it must be below {AMOUNT_LIMIT:,}"
            )
    if data.low > data.high:
        raise InvalidGuidance("The low end of the range must not exceed the high end")


def _fields(data: GuidanceInput) -> dict[str, object]:
    note = (data.source_note or "").strip()
    return {
        "metric": data.metric,
        "fiscal_year": data.fiscal_year,
        "fiscal_period": data.fiscal_period,
        "low": data.low,
        "high": data.high,
        "basis": data.basis,
        "direction": data.direction or _default_direction(data.metric),
        "given_on": data.given_on,
        "source_note": note or None,
    }


def _default_direction(metric: str) -> Direction:
    return "lower" if metric in LOWER_IS_BETTER else "higher"


def _stored(session: Session, company: Company, guidance_id: int) -> Guidance:
    stored = repo.get(session, company.id, guidance_id)
    if stored is None:
        raise GuidanceNotFound(str(guidance_id))
    return stored


def _naive_utc(moment: datetime) -> datetime:
    # SQLite keeps no time zone: the columns hold UTC without one.
    return moment.astimezone(UTC).replace(tzinfo=None) if moment.tzinfo else moment
