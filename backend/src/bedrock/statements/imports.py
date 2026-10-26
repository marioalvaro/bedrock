"""Imported statement values on the engine's side: the frames `solve_cells` reads, the calendar
with imported years, and the check of an import's periods against a company's calendar. Pure."""

from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal

import pandas as pd

from bedrock.mapping.config import CanonicalItemDef
from bedrock.mapping.mapper import CANONICAL_COLUMNS
from bedrock.statements.cell_types import EMPTY, IMPORT_PREFIX, Cell, CellKey
from bedrock.statements.periods import Calendar, fiscal_calendar
from bedrock.statements.rules import BALANCE_FLOOR, BALANCE_RELATIVE

IMPORT_FORM = "import"  # the `form` and `taxonomy` of an imported cell's source
VINTAGE_COLUMNS = [
    "code",
    "fiscal_year",
    "fiscal_period",
    "value",
    "accession_no",
    "form",
    "filed_at",
]
_OBJECT_COLUMNS = {
    "period_start": "object",
    "period_end": "object",
    "value": "object",
    "filed_at": "object",
}


@dataclass(frozen=True)
class StoredValue:
    """An imported value as stored: in units, in the reported sign convention, with the import
    it belongs to. `period_start` is None for an instant."""

    import_id: int
    filename: str
    imported_at: datetime
    line_code: str
    fiscal_year: int
    fiscal_period: str
    period_start: date | None
    period_end: date
    value: Decimal


@dataclass(frozen=True)
class ImportedFrames:
    newest: pd.DataFrame  # canonical-shaped: the value each (line, period) shows
    vintages: pd.DataFrame  # every stored value, for cell details


def imported_frames(
    values: Sequence[StoredValue], items: Sequence[CanonicalItemDef]
) -> ImportedFrames:
    """`newest`: per (line, period) the value of the newest import, in the displayed sign
    convention, as a canonical-shaped frame whose source is the import (`import:<id>`). A balance
    sheet value is one per date (the year's beats the fourth quarter's, which is the same date).
    `vintages`: every stored value, oldest import first, for cell details. Lines that are not
    canonical (custom lines) are left out."""
    by_code = {i.code: i for i in items}
    known = [v for v in values if v.line_code in by_code]
    newest: dict[tuple[str, int, str], StoredValue] = {}
    for v in sorted(known, key=lambda v: (v.imported_at, v.import_id)):
        newest[(v.line_code, v.fiscal_year, v.fiscal_period)] = v
    chosen: dict[tuple[object, ...], StoredValue] = {}
    for key, v in newest.items():
        if by_code[v.line_code].kind != "instant":
            chosen[key] = v
            continue
        at = (v.line_code, v.period_end)
        held = chosen.get(at)
        if held is None or (held.fiscal_period != "FY" and v.fiscal_period == "FY"):
            chosen[at] = v

    rows = [_row(v, by_code[v.line_code]) for v in chosen.values()]
    rows.sort(key=lambda r: (r["code"], r["period_end"]))
    history = sorted(
        known,
        key=lambda v: (v.line_code, v.fiscal_year, v.fiscal_period, v.imported_at, v.import_id),
    )
    vintages = [
        {
            "code": v.line_code,
            "fiscal_year": v.fiscal_year,
            "fiscal_period": v.fiscal_period,
            "value": v.value * by_code[v.line_code].sign,
            "accession_no": f"{IMPORT_PREFIX}{v.import_id}",
            "form": IMPORT_FORM,
            "filed_at": v.imported_at.date(),
        }
        for v in history
    ]
    return ImportedFrames(
        pd.DataFrame(rows, columns=[*CANONICAL_COLUMNS, "fiscal_year", "fiscal_period"]).astype(
            _OBJECT_COLUMNS
        ),
        pd.DataFrame(vintages, columns=VINTAGE_COLUMNS).astype(
            {"value": "object", "filed_at": "object"}
        ),
    )


def _row(v: StoredValue, item: CanonicalItemDef) -> dict[str, object]:
    return {
        "code": v.line_code,
        "period_start": None if item.kind == "instant" else v.period_start,
        "period_end": v.period_end,
        "value": v.value * item.sign,
        "taxonomy": IMPORT_FORM,
        "concept": v.line_code,  # distinct per line, so two operands never look like one fact
        "unit": item.unit,
        "accession_no": f"{IMPORT_PREFIX}{v.import_id}",
        "form": IMPORT_FORM,
        "filed_at": v.imported_at.date(),
        "kind": item.kind,
        "fiscal_year": v.fiscal_year,  # beyond the canonical columns: the calendar reads them
        "fiscal_period": v.fiscal_period,
    }


def company_calendar(canonical: pd.DataFrame, imported: pd.DataFrame | None) -> Calendar:
    """The fiscal calendar of the SEC facts plus the years the imports add: those that end before
    the first SEC fiscal year, or every imported year when there is no SEC data (a manual
    company). An imported period inside the SEC years adds nothing: it must match a period of
    the calendar (`check_periods`) and is read against that period's dates."""
    sec = fiscal_calendar(canonical)
    if imported is None or imported.empty:
        return sec
    flows = imported[imported["kind"] == "flow"]
    if sec.years:
        flows = flows[flows["period_end"] < sec.years[0].start]
    spans = _calendar_spans(flows)
    if not spans:
        return sec
    columns = ["period_start", "period_end", "kind"]
    extra = pd.DataFrame([(a, b, "flow") for a, b in spans], columns=columns)
    parts = [extra] if canonical.empty else [canonical[columns], extra]
    return fiscal_calendar(pd.concat(parts, ignore_index=True))


def _calendar_spans(flows: pd.DataFrame) -> list[tuple[date, date]]:
    """The spans the calendar is read from. The calendar finds a year's quarter ends from the
    year-to-date facts of its 10-Qs, which start with the year; imported quarters are discrete, so
    each Q1-Q3 also counts from the year's start, and a year given by its quarters alone gets its
    own span."""
    by_year: dict[int, dict[str, tuple[date, date]]] = {}
    for r in flows.to_dict("records"):
        by_year.setdefault(r["fiscal_year"], {})[r["fiscal_period"]] = (
            r["period_start"],
            r["period_end"],
        )
    spans: list[tuple[date, date]] = []
    for year in by_year.values():
        spans += year.values()
        start = (year.get("FY") or year.get("Q1") or (None, None))[0]
        if start is None:
            continue
        spans += [(start, year[q][1]) for q in ("Q2", "Q3", "Q4") if q in year]
        if "FY" not in year and "Q4" in year:
            spans.append((start, year["Q4"][1]))
    return spans


def integrity_warnings(
    cells: Mapping[CellKey, Cell], balance_keys: Iterable[str], cash_keys: Iterable[str]
) -> list[str]:
    """What an import breaks in the periods it touched: a balance sheet that does not balance
    (`balance_keys`, periods with a balance-sheet value) and a cash flow that does not roll
    forward (`cash_keys`, periods with a cash-flow value; needs every term). Same tolerance as
    the balance check."""
    out: list[str] = []
    for key in sorted(set(balance_keys)):
        assets, liabilities, equity = (
            cells.get((code, key), EMPTY).value
            for code in ("total_assets", "total_liabilities", "total_equity")
        )
        if assets is None or liabilities is None or equity is None:
            continue
        temporary = cells.get(("temporary_equity", key), EMPTY).value or Decimal(0)
        difference = assets - (liabilities + temporary + equity)
        if abs(difference) > max(BALANCE_FLOOR, BALANCE_RELATIVE * assets):
            out.append(f"{key}: the balance sheet does not balance (difference {difference:,})")
    for key in sorted(set(cash_keys)):
        terms = [
            cells.get((code, key), EMPTY).value
            for code in ("net_change_in_cash", "cfo", "cfi", "cff", "fx_effect")
        ]
        change, cfo, cfi, cff, fx = terms
        if change is None or cfo is None or cfi is None or cff is None or fx is None:
            continue
        difference = change - (cfo + cfi + cff + fx)
        if abs(difference) > max(BALANCE_FLOOR, BALANCE_RELATIVE * max(abs(cfo), abs(change))):
            out.append(f"{key}: the cash flow does not roll forward (difference {difference:,})")
    return out
