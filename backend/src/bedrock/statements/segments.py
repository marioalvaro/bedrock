"""Segment and KPI grids (FR-DATA-11): the reconciliation to the income statement and the
CSV/TSV import grammar. Pure: no database, no network ([erd/data.md](../../../../docs/erd/data.md),
"Segments and KPIs (M3)")."""

import csv
import io
import re
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date
from decimal import Decimal, localcontext
from typing import Literal

from bedrock.statements.build import StatementTable

SegmentFreq = Literal["annual", "quarterly"]
Scale = Literal["units", "K", "M", "B"]

# |value| < VALUE_LIMIT for every stored value (the same bound as services/adjustments.py::
# AMOUNT_LIMIT, Gotcha G21), at most VALUE_PLACES decimal places.
VALUE_LIMIT = Decimal(10) ** 15
VALUE_PLACES = 10

# Import identity rules, shared with the service (which must not copy them).
NAME_MAX = 80  # longest series name, in characters
KPI_CODE = re.compile(r"^[a-z][a-z0-9_]{0,39}$")  # a KPI code: a lowercase slug, 1..40 characters
METRICS = frozenset({"revenue", "operating_income"})  # metrics allowed for business/geo series


@dataclass(frozen=True)
class SeriesData:
    id: int
    dimension: str  # business | geo | kpi
    name: str
    metric: str  # revenue | operating_income for business/geo; the KPI code for kpi
    unit: str  # USD | pct | count | USD_per_unit
    display_order: int


@dataclass(frozen=True)
class ValueData:
    series_id: int
    fiscal_year: int
    fiscal_period: str  # FY | Q1..Q4
    value: Decimal


@dataclass(frozen=True)
class SegmentPeriod:
    """A column of the grid. The dates are those of the income statement period; a period that
    has only segment values (a year before XBRL) has none."""

    key: str  # FY2024, FY2024Q3 (as statements/periods.py::Period.key)
    label: str  # FY24, Q3 FY24
    fiscal_year: int
    fiscal_period: str
    start: date | None
    end: date | None


@dataclass(frozen=True)
class SeriesRow:
    id: int
    name: str
    metric: str
    unit: str
    display_order: int
    values: list[Decimal | None]  # aligned with SegmentGrid.periods


@dataclass(frozen=True)
class SegmentBlock:
    dimension: str
    metric: str | None  # None for the kpi block
    series: list[SeriesRow]  # by display_order, then id
    unallocated: list[Decimal | None] | None  # None for the kpi block


@dataclass(frozen=True)
class SegmentGrid:
    freq: SegmentFreq
    periods: list[SegmentPeriod]  # oldest first
    blocks: list[SegmentBlock]


@dataclass(frozen=True)
class ImportIssue:
    """One import error. `row` is 1-based with the header as row 1; `column` is the 1-based
    column, or None when the problem is the whole row or the whole text."""

    row: int
    column: int | None
    message: str


@dataclass(frozen=True)
class ImportValue:
    fiscal_year: int
    fiscal_period: str
    value: Decimal  # scaled, in stored units


@dataclass(frozen=True)
class ImportSeries:
    row: int  # the 1-based row it came from (for errors the service finds later)
    name: str
    metric: str
    unit: str
    values: list[ImportValue]  # non-blank cells only, in column order


@dataclass(frozen=True)
class ImportRow:
    """The identity of a data row whose name, metric and unit are valid, whatever its cells hold:
    lets the service check conflicts with stored series even when other cells have errors."""

    row: int
    name: str
    metric: str
    unit: str


@dataclass(frozen=True)
class ImportPlan:
    """`errors` empty means `series` is the whole plan; otherwise `series` is empty and `errors`
    lists every problem found (not just the first). `rows` lists every data row with a valid
    identity (also when `errors` is not empty; in file order)."""

    series: list[ImportSeries]
    errors: list[ImportIssue]
    rows: list[ImportRow]


def segment_grid(
    series: Sequence[SeriesData],
    values: Sequence[ValueData],
    is_table: StatementTable,
    freq: SegmentFreq,
) -> SegmentGrid:
    """The grid of one company's series.

    Preconditions: `is_table` is the reported income statement of `freq`, trimmed like the API's
    statements; `values` belong to `series`.
    Postconditions:
    - `periods` = the IS table's periods ∪ the periods of every value of `freq` (annual: FY;
      quarterly: Q1..Q4), oldest first; values of the other frequency are ignored.
    - `blocks` in the order business-revenue, business-operating_income, geo-revenue,
      geo-operating_income, kpi; a block with no series is left out. Each series' `values` are
      aligned with `periods`, None where it has none.
    - A business/geo block's `unallocated[i]` = the IS row `metric` at period i − Σ the block's
      series values there; None unless the IS value and at least one series value exist (a
      negative difference is kept). The kpi block has `metric` and `unallocated` None.
    """
    periods: dict[str, SegmentPeriod] = {
        p.key: SegmentPeriod(p.key, p.label, p.fiscal_year, p.fiscal_period, p.start, p.end)
        for p in is_table.periods
    }
    known = {s.id for s in series}
    wanted = _ANNUAL if freq == "annual" else _QUARTERS
    for v in values:
        if v.series_id in known and v.fiscal_period in wanted:
            key = _period_key(v.fiscal_year, v.fiscal_period)
            if key not in periods:
                periods[key] = SegmentPeriod(
                    key,
                    _period_label(v.fiscal_year, v.fiscal_period),
                    v.fiscal_year,
                    v.fiscal_period,
                    None,
                    None,
                )
    ordered = sorted(periods.values(), key=lambda p: (p.fiscal_year, _FP_ORDER[p.fiscal_period]))
    index = {p.key: i for i, p in enumerate(ordered)}

    cells: dict[int, list[Decimal | None]] = {s.id: [None] * len(ordered) for s in series}
    for v in values:
        if v.series_id in cells and v.fiscal_period in wanted:
            cells[v.series_id][index[_period_key(v.fiscal_year, v.fiscal_period)]] = v.value

    is_rows = {r.code: r.values for r in is_table.rows}
    is_index = {p.key: i for i, p in enumerate(is_table.periods)}

    blocks: list[SegmentBlock] = []
    for dimension, metric in _BLOCK_ORDER:
        members = sorted(
            (
                s
                for s in series
                if s.dimension == dimension and (metric is None or s.metric == metric)
            ),
            key=lambda s: (s.display_order, s.id),
        )
        if not members:
            continue
        rows = [
            SeriesRow(s.id, s.name, s.metric, s.unit, s.display_order, cells[s.id]) for s in members
        ]
        unallocated: list[Decimal | None] | None = None
        if metric is not None:
            canonical = is_rows.get(metric)
            unallocated = []
            for i, period in enumerate(ordered):
                j = is_index.get(period.key)
                total = canonical[j] if canonical is not None and j is not None else None
                parts = [x for r in rows if (x := r.values[i]) is not None]
                if total is None or not parts:
                    unallocated.append(None)
                else:
                    unallocated.append(total - sum(parts, Decimal(0)))
        blocks.append(SegmentBlock(dimension, metric, rows, unallocated))
    return SegmentGrid(freq, ordered, blocks)


def parse_import(text: str, dimension: str, scale: Scale) -> ImportPlan:
    """Parses a CSV/TSV paste.

    Grammar: the delimiter is a tab when the header line contains one, else a comma; quoted
    fields allowed. Header `name,metric,unit,<period>…` with periods `FY2024` or `Q1 FY2024`.
    Each later non-blank line is one series; a blank cell is skipped. `scale` multiplies USD and
    USD_per_unit values only; `pct` is typed as a percent ("5.2" or "5.2%") and stored as a
    fraction; `count` as typed. Numbers accept thousands separators and parentheses or a leading
    "-" for negatives.

    Errors (all reported together, nothing partial): unknown or missing header columns, a bad
    period label, a duplicated period column, a bad number (also non-finite, |v| >= VALUE_LIMIT,
    more than VALUE_PLACES decimals after scaling), a metric not allowed for the dimension
    (business/geo: revenue | operating_income; kpi: a slug ^[a-z][a-z0-9_]{0,39}$), a unit not
    allowed for the dimension (business/geo: USD only), a blank or > 80 character name, a
    duplicate (name, metric) row, empty text.
    """
    if dimension not in ("business", "geo", "kpi"):
        raise ValueError(f"unknown dimension {dimension!r}")
    text = text.removeprefix("\ufeff")
    body = text.lstrip("\r\n \t") if text.strip() else ""
    if not body:
        return ImportPlan([], [ImportIssue(1, None, "the text is empty")], [])
    first_line = body.splitlines()[0]
    delimiter = "\t" if "\t" in first_line else ","
    # row = physical line number; quoted fields with newlines shift later records, which the
    # reader's line_num accounts for.
    reader = csv.reader(io.StringIO(body), delimiter=delimiter)
    errors: list[ImportIssue] = []
    header = next(reader)
    width = len(header)
    while len(header) > len(_HEADER) and not header[-1].strip():
        header.pop()  # trailing blank header cells are ignored
    periods = _parse_header(header, errors)

    out: list[ImportSeries] = []
    rows: list[ImportRow] = []
    seen: set[tuple[str, str]] = set()
    last_line = reader.line_num
    for record in reader:
        row = last_line + 1
        last_line = reader.line_num
        if not any(c.strip() for c in record):
            continue
        identity, series_row = _parse_row(record, row, dimension, scale, periods, width, errors)
        if identity is None:
            continue
        key = (identity.name, identity.metric)
        if key in seen:
            errors.append(ImportIssue(row, None, f"duplicate series {key[0]!r} / {key[1]!r}"))
            continue
        seen.add(key)
        rows.append(identity)
        if series_row is not None:
            out.append(series_row)
    return ImportPlan([] if errors else out, errors, rows)


_ANNUAL = frozenset({"FY"})
_QUARTERS = frozenset({"Q1", "Q2", "Q3", "Q4"})
_FP_ORDER = {"Q1": 0, "Q2": 1, "Q3": 2, "Q4": 3, "FY": 4}
_BLOCK_ORDER: tuple[tuple[str, str | None], ...] = (
    ("business", "revenue"),
    ("business", "operating_income"),
    ("geo", "revenue"),
    ("geo", "operating_income"),
    ("kpi", None),
)


def _period_key(year: int, fp: str) -> str:
    return f"FY{year}" if fp == "FY" else f"FY{year}{fp}"


def _period_label(year: int, fp: str) -> str:
    return f"FY{year % 100:02d}" if fp == "FY" else f"{fp} FY{year % 100:02d}"


_KPI_UNITS = frozenset({"USD", "pct", "count", "USD_per_unit"})
_PERIOD = re.compile(r"^(?:(Q[1-4]) )?FY(\d{4})$")
_PLAIN = re.compile(r"^\d*\.?\d+$|^\d+\.$")
_GROUPED = re.compile(r"^\d{1,3}(?:,\d{3})+(?:\.\d+)?$")
_FACTORS = {"units": 1, "K": 10**3, "M": 10**6, "B": 10**9}
_HEADER = ("name", "metric", "unit")


def _parse_header(header: list[str], errors: list[ImportIssue]) -> list[tuple[int, str] | None]:
    """Period of each header column after the first three (None where the label is bad)."""
    if len(header) < len(_HEADER):
        errors.append(ImportIssue(1, None, "the header needs name, metric and unit columns"))
    for i, expected in enumerate(_HEADER[: len(header)]):
        if header[i].strip() != expected:
            errors.append(
                ImportIssue(1, i + 1, f"expected column {expected!r}, got {header[i].strip()!r}")
            )
    periods: list[tuple[int, str] | None] = []
    seen: set[tuple[int, str]] = set()
    for i, raw in enumerate(header[len(_HEADER) :], start=len(_HEADER) + 1):
        m = _PERIOD.match(raw.strip())
        if m is None:
            errors.append(ImportIssue(1, i, f"bad period label {raw.strip()!r}"))
            periods.append(None)
            continue
        period = (int(m.group(2)), m.group(1) or "FY")
        if period in seen:
            errors.append(ImportIssue(1, i, f"duplicate period column {raw.strip()!r}"))
            periods.append(None)
            continue
        seen.add(period)
        periods.append(period)
    if len(header) >= len(_HEADER) and not periods:
        errors.append(ImportIssue(1, None, "the header has no period column"))
    return periods


def _parse_row(
    record: list[str],
    row: int,
    dimension: str,
    scale: Scale,
    periods: list[tuple[int, str] | None],
    width: int,
    errors: list[ImportIssue],
) -> tuple[ImportRow | None, ImportSeries | None]:
    """The row's identity (None when name, metric or unit is bad) and its series (None when
    anything on the row is bad)."""
    start = len(errors)
    cell = [c.strip() for c in record] + [""] * (len(_HEADER) - len(record))
    name, metric, unit = cell[0], cell[1], cell[2]
    if not name:
        errors.append(ImportIssue(row, 1, "the name is blank"))
    elif len(name) > NAME_MAX:
        errors.append(ImportIssue(row, 1, f"the name is longer than {NAME_MAX} characters"))
    if dimension == "kpi":
        if not KPI_CODE.match(metric):
            errors.append(ImportIssue(row, 2, f"{metric!r} is not a KPI code (a-z, 0-9, _)"))
        if unit not in _KPI_UNITS:
            errors.append(
                ImportIssue(row, 3, f"unit {unit!r} is not one of USD, pct, count, USD_per_unit")
            )
    else:
        if metric not in METRICS:
            errors.append(
                ImportIssue(row, 2, f"metric {metric!r} must be revenue or operating_income")
            )
        if unit != "USD":
            errors.append(ImportIssue(row, 3, f"unit {unit!r} must be USD for {dimension}"))
    identity_ok = len(errors) == start
    unit_ok = (dimension == "kpi" and unit in _KPI_UNITS) or (dimension != "kpi" and unit == "USD")

    values: list[ImportValue] = []
    for offset, text in enumerate(cell[len(_HEADER) :], start=len(_HEADER)):
        if not text:
            continue
        column = offset + 1
        if offset - len(_HEADER) >= len(periods):
            message = (
                "a value under a blank header"
                if column <= width
                else "a value with no period column"
            )
            errors.append(ImportIssue(row, column, message))
            continue
        period = periods[offset - len(_HEADER)]
        if period is None or not unit_ok:
            continue
        value = _parse_number(text, unit, scale)
        if isinstance(value, str):
            errors.append(ImportIssue(row, column, value))
        else:
            values.append(ImportValue(period[0], period[1], value))
    identity = ImportRow(row, name, metric, unit) if identity_ok else None
    if len(errors) > start:
        return identity, None
    return identity, ImportSeries(row, name, metric, unit, values)


def _parse_number(text: str, unit: str, scale: Scale) -> Decimal | str:
    """The stored value, or the reason the cell is bad."""
    raw = text
    negative = False
    if raw.startswith("(") and raw.endswith(")"):
        negative, raw = True, raw[1:-1].strip()
    elif raw.startswith("-"):
        negative, raw = True, raw[1:].strip()
    if unit == "pct" and raw.endswith("%"):
        raw = raw[:-1].strip()
    if not (_PLAIN.match(raw) or _GROUPED.match(raw)):
        return f"{text!r} is not a number"
    with localcontext() as ctx:
        ctx.prec = 100
        value = Decimal(raw.replace(",", ""))
        if negative:
            value = -value
        if unit == "pct":
            value = value / 100
        elif unit in ("USD", "USD_per_unit"):
            value = value * _FACTORS[scale]
        if abs(value) >= VALUE_LIMIT:
            return f"{text!r} is out of range"
        exponent = value.normalize().as_tuple().exponent
        if isinstance(exponent, int) and exponent < -VALUE_PLACES:
            return f"{text!r} has more than {VALUE_PLACES} decimal places after scaling"
        return value
