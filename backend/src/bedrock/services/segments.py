"""Segment and KPI series of a followed company (FR-DATA-11)."""

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal

from sqlalchemy.orm import Session

from bedrock.models.company import Company
from bedrock.models.segment_series import DIMENSIONS, UNITS, SegmentSeries
from bedrock.models.segment_value import SegmentValue
from bedrock.repositories import segments as repo
from bedrock.services.adjustments import AMOUNT_LIMIT
from bedrock.services.errors import InvalidImport, InvalidSeries, SeriesNotFound
from bedrock.services.statements import statement_tables
from bedrock.statements import segments as engine
from bedrock.statements.segments import (
    ImportIssue,
    Scale,
    SegmentFreq,
    SegmentGrid,
    SeriesData,
    ValueData,
)
from bedrock.statements.view import trim_periods

__all__ = [
    "FillResult",
    "ImportResult",
    "SeriesInput",
    "ValueInput",
    "create_series",
    "delete_series",
    "fill_annual",
    "import_segments",
    "segment_grid",
    "set_values",
    "update_series",
]


@dataclass(frozen=True)
class SeriesInput:
    dimension: str
    name: str
    metric: str
    unit: str


@dataclass(frozen=True)
class ValueInput:
    fiscal_year: int
    fiscal_period: str  # FY | Q1..Q4
    value: Decimal | None  # None deletes


@dataclass(frozen=True)
class ImportResult:
    series_created: int
    values_created: int
    values_updated: int


@dataclass(frozen=True)
class FillResult:
    values_created: int
    values_overwritten: int
    values_unchanged: int


_YEAR_RANGE = (1000, 9999)  # four digits, as the import grammar
_ORDER_RANGE = (0, 1_000_000)


def _naive_utc(moment: datetime) -> datetime:
    return moment.astimezone(UTC).replace(tzinfo=None) if moment.tzinfo else moment


def segment_grid(session: Session, company: Company, freq: SegmentFreq) -> SegmentGrid:
    """`statements/segments.py::segment_grid` on the company's series and values and its reported
    income statement of `freq` (trimmed: `services/statements.py::statement_tables` then
    `statements/view.py::trim_periods`). A company with no facts and no series gives an empty
    grid. Loads series and values in bulk (no per-series queries)."""
    table = trim_periods(statement_tables(session, company, [("IS", freq)])[("IS", freq)])
    series = repo.list_series(session, company.id)
    values = repo.list_values(session, [s.id for s in series])
    return engine.segment_grid(
        [SeriesData(s.id, s.dimension, s.name, s.metric, s.unit, s.display_order) for s in series],
        [ValueData(v.series_id, v.fiscal_year, v.fiscal_period, v.value) for v in values],
        table,
        freq,
    )


def create_series(
    session: Session, company: Company, data: SeriesInput, now: datetime
) -> SegmentSeries:
    """Validates, stores (name stripped) and commits; `display_order` = the company's highest
    + 1 (1 for the first). Raises InvalidSeries for: an unknown dimension or unit; a blank or
    > 80 character name; business/geo with a metric other than revenue | operating_income or a
    unit other than USD; kpi with a metric that is not a slug ^[a-z][a-z0-9_]{0,39}$ or a code
    already used by another of the company's KPIs; a duplicate (dimension, name, metric)."""
    name = data.name.strip()
    _check_name(name)
    _check_definition(data)
    existing = repo.list_series(session, company.id)
    _check_unique(existing, data.dimension, name, data.metric, None)
    stamp = _naive_utc(now)
    created = repo.add_series(
        session,
        SegmentSeries(
            company_id=company.id,
            dimension=data.dimension,
            name=name,
            metric=data.metric,
            unit=data.unit,
            display_order=repo.max_display_order(session, company.id) + 1,
            created_at=stamp,
            updated_at=stamp,
        ),
    )
    session.commit()
    return created


def update_series(
    session: Session,
    company: Company,
    series_id: int,
    name: str,
    display_order: int,
    now: datetime,
) -> SegmentSeries:
    """Renames (stripped; same name rules and duplicate check as create) and reorders, and
    commits. Raises SeriesNotFound (checked first) and InvalidSeries (also a display_order
    outside 0..1,000,000)."""
    stored = _stored(session, company, series_id)
    name = name.strip()
    _check_name(name)
    if not _ORDER_RANGE[0] <= display_order <= _ORDER_RANGE[1]:
        raise InvalidSeries(f"The display order must be {_ORDER_RANGE[0]}..{_ORDER_RANGE[1]:,}")
    _check_unique(
        repo.list_series(session, company.id), stored.dimension, name, stored.metric, stored.id
    )
    stored.name = name
    stored.display_order = display_order
    stored.updated_at = _naive_utc(now)
    session.commit()
    return _stored(session, company, series_id)


def delete_series(session: Session, company: Company, series_id: int) -> None:
    """Deletes the series and its values. Raises SeriesNotFound."""
    repo.delete_series(session, _stored(session, company, series_id))
    session.commit()


def set_values(
    session: Session,
    company: Company,
    series_id: int,
    values: Sequence[ValueInput],
    now: datetime,
) -> SegmentSeries:
    """Upserts each value on (series, fiscal_year, fiscal_period); a None value deletes it
    (deleting an absent one is a no-op). Commits. Raises SeriesNotFound (checked first) and
    InvalidSeries for a fiscal year outside 1000..9999, a value that is not finite, has
    |value| >= `AMOUNT_LIMIT` (G21) or more than 10 decimal places, or a duplicated period in
    `values`; nothing is written then."""
    stored = _stored(session, company, series_id)
    seen: set[tuple[int, str]] = set()
    for item in values:
        period = (item.fiscal_year, item.fiscal_period)
        if not _YEAR_RANGE[0] <= item.fiscal_year <= _YEAR_RANGE[1]:
            raise InvalidSeries(f"The fiscal year must be {_YEAR_RANGE[0]}..{_YEAR_RANGE[1]}")
        if period in seen:
            raise InvalidSeries(f"Period {item.fiscal_period} {item.fiscal_year} is given twice")
        seen.add(period)
        if item.value is not None:
            _check_value(item.value)
    current = {(v.fiscal_year, v.fiscal_period): v for v in repo.list_values(session, [stored.id])}
    stamp = _naive_utc(now)
    for item in values:
        found = current.get((item.fiscal_year, item.fiscal_period))
        if item.value is None:
            if found is not None:
                repo.delete_value(session, found)
        elif found is None:
            repo.add_value(
                session,
                SegmentValue(
                    series_id=stored.id,
                    fiscal_year=item.fiscal_year,
                    fiscal_period=item.fiscal_period,
                    value=item.value,
                    created_at=stamp,
                    updated_at=stamp,
                ),
            )
        else:
            found.value = item.value
            found.updated_at = stamp
    session.commit()
    return _stored(session, company, series_id)


def import_segments(
    session: Session,
    company: Company,
    dimension: str,
    text: str,
    scale: Scale,
    now: datetime,
) -> ImportResult:
    """`parse_import`, then writes the plan and commits, all or nothing. Series are upserted by
    (dimension, name, metric) (display_order as in create); one value per non-blank cell. Raises
    InvalidImport with every issue in one round (sorted by row, column): the parser's, plus a
    unit that differs from an existing series (row of that series, the unit column 3) and a kpi
    code already used by a KPI of another name (column 2). Nothing is written when there are
    issues. Idempotent: the same text again creates nothing and counts every cell as updated."""
    plan = engine.parse_import(text, dimension, scale)
    existing = [s for s in repo.list_series(session, company.id) if s.dimension == dimension]
    by_key = {(s.name, s.metric): s for s in existing}
    issues: list[ImportIssue] = list(plan.errors)
    codes = {s.metric: s.name for s in existing} if dimension == "kpi" else {}
    for row in plan.rows:
        found = by_key.get((row.name, row.metric))
        if found is not None and found.unit != row.unit:
            issues.append(
                ImportIssue(
                    row.row, 3, f"unit {row.unit!r} differs from the series' {found.unit!r}"
                )
            )
        if dimension == "kpi" and codes.setdefault(row.metric, row.name) != row.name:
            issues.append(
                ImportIssue(
                    row.row, 2, f"KPI code {row.metric!r} is already used by {codes[row.metric]!r}"
                )
            )
    if issues:
        issues.sort(key=lambda i: (i.row, -1 if i.column is None else i.column))
        raise InvalidImport(issues)

    stamp = _naive_utc(now)
    next_order = repo.max_display_order(session, company.id)
    current = {
        (v.series_id, v.fiscal_year, v.fiscal_period): v
        for v in repo.list_values(session, [s.id for s in existing])
    }
    created = added = updated = 0
    for item in plan.series:
        series = by_key.get((item.name, item.metric))
        if series is None:
            next_order += 1
            series = repo.add_series(
                session,
                SegmentSeries(
                    company_id=company.id,
                    dimension=dimension,
                    name=item.name,
                    metric=item.metric,
                    unit=item.unit,
                    display_order=next_order,
                    created_at=stamp,
                    updated_at=stamp,
                ),
            )
            created += 1
        for cell in item.values:
            old = current.get((series.id, cell.fiscal_year, cell.fiscal_period))
            if old is None:
                repo.add_value(
                    session,
                    SegmentValue(
                        series_id=series.id,
                        fiscal_year=cell.fiscal_year,
                        fiscal_period=cell.fiscal_period,
                        value=cell.value,
                        created_at=stamp,
                        updated_at=stamp,
                    ),
                )
                added += 1
            else:
                old.value = cell.value
                old.updated_at = stamp
                updated += 1
    session.commit()
    return ImportResult(created, added, updated)


def fill_annual(session: Session, company: Company, dry_run: bool, now: datetime) -> FillResult:
    """Sets each FY value to the sum of its quarters (`statements/segments.py::fill_annual`: USD
    series, years with all four quarters) and commits. A stored FY value that differs is
    overwritten, an equal one is left untouched and counted unchanged. `dry_run` returns the same
    counts and writes nothing. Raises InvalidSeries for a sum outside the value limit (G21),
    with nothing written."""
    series = repo.list_series(session, company.id)
    stored = repo.list_values(session, [s.id for s in series])
    fills = engine.fill_annual(
        [SeriesData(s.id, s.dimension, s.name, s.metric, s.unit, s.display_order) for s in series],
        [ValueData(v.series_id, v.fiscal_year, v.fiscal_period, v.value) for v in stored],
    )
    for fill in fills:
        _check_value(fill.value)
    current = {(v.series_id, v.fiscal_year): v for v in stored if v.fiscal_period == "FY"}
    stamp = _naive_utc(now)
    created = overwritten = unchanged = 0
    for fill in fills:
        old = current.get((fill.series_id, fill.fiscal_year))
        if old is None:
            created += 1
            if not dry_run:
                repo.add_value(
                    session,
                    SegmentValue(
                        series_id=fill.series_id,
                        fiscal_year=fill.fiscal_year,
                        fiscal_period="FY",
                        value=fill.value,
                        created_at=stamp,
                        updated_at=stamp,
                    ),
                )
        elif old.value == fill.value:
            unchanged += 1
        else:
            overwritten += 1
            if not dry_run:
                old.value = fill.value
                old.updated_at = stamp
    if not dry_run:
        session.commit()
    return FillResult(created, overwritten, unchanged)


def _stored(session: Session, company: Company, series_id: int) -> SegmentSeries:
    stored = repo.get_series(session, company.id, series_id)
    if stored is None:
        raise SeriesNotFound(str(series_id))
    return stored


def _check_name(name: str) -> None:
    if not name:
        raise InvalidSeries("The name is blank")
    if len(name) > engine.NAME_MAX:
        raise InvalidSeries(f"The name is longer than {engine.NAME_MAX} characters")


def _check_definition(data: SeriesInput) -> None:
    if data.dimension not in DIMENSIONS:
        raise InvalidSeries(f"Unknown dimension {data.dimension!r}")
    if data.unit not in UNITS:
        raise InvalidSeries(f"Unknown unit {data.unit!r}")
    if data.dimension == "kpi":
        if not engine.KPI_CODE.match(data.metric):
            raise InvalidSeries(f"{data.metric!r} is not a KPI code (a-z, 0-9, _; at most 40)")
    else:
        if data.metric not in engine.METRICS:
            raise InvalidSeries("The metric must be revenue or operating_income")
        if data.unit != "USD":
            raise InvalidSeries(f"The unit must be USD for {data.dimension}")


def _check_unique(
    existing: Sequence[SegmentSeries],
    dimension: str,
    name: str,
    metric: str,
    own_id: int | None,
) -> None:
    for other in existing:
        if other.id == own_id or other.dimension != dimension:
            continue
        if other.name == name and other.metric == metric:
            raise InvalidSeries(f"{name!r} / {metric!r} already exists")
        if dimension == "kpi" and other.metric == metric and other.name != name:
            raise InvalidSeries(f"KPI code {metric!r} is already used by {other.name!r}")


def _check_value(value: Decimal) -> None:
    if not value.is_finite():
        raise InvalidSeries("A value must be a finite number")
    if abs(value) >= AMOUNT_LIMIT:
        raise InvalidSeries(f"A value must be below {AMOUNT_LIMIT:,} in magnitude")
    exponent = value.normalize().as_tuple().exponent
    if isinstance(exponent, int) and exponent < -engine.VALUE_PLACES:
        raise InvalidSeries(f"A value has at most {engine.VALUE_PLACES} decimal places")
