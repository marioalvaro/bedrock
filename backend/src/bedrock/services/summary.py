"""The Overview summary of one company, computed on read (M7c S6, FR-WS-04; docs/erd/
workspace.md "Company summary"). Only calls existing services and repositories. Each block is
computed on its own: a block that raises a domain error is empty and its message goes to
`warnings`, so a company with missing data still gets a summary."""

import re
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from datetime import date, datetime
from decimal import Decimal

from sqlalchemy.orm import Session

from bedrock.models.company import Company
from bedrock.models.scenario import Scenario
from bedrock.ratios.registry import RATIOS
from bedrock.repositories import facts as facts_repo
from bedrock.repositories import runs as runs_repo
from bedrock.repositories import scenarios as scenarios_repo
from bedrock.services import analysis as analysis_service
from bedrock.services import notes as notes_service
from bedrock.services import ratios as ratios_service
from bedrock.services import valuation as valuation_service
from bedrock.services.errors import DOMAIN_ERRORS, user_message
from bedrock.services.statements import statement_tables
from bedrock.statements.build import RATIO_PLACES, Freq, Row
from bedrock.statements.periods import Period

# The seven metrics, in this order: revenue from the income statement, the rest from the annual
# reported ratio table.
METRIC_CODES = (
    "revenue",
    "gross_margin",
    "operating_margin",
    "fcf_margin",
    "roic",
    "eps_diluted",
    "net_debt_to_ebitda",
)
YEARS = 5
NOTES = 3
EXCERPT_LENGTH = 140
# A difference in points for these units; a relative change for USD and per-share units.
_DIFFERENCE_UNITS = frozenset({"pct", "x", "days"})
_SEVERITY_RANK = {"alert": 0, "warn": 1}
# code -> (label, unit) of each metric; a ratio's from the registry
_METRIC_LABELS = {"revenue": ("Revenue", "USD")} | {
    r.code: (r.label, r.unit) for r in RATIOS if r.code in METRIC_CODES
}


@dataclass(frozen=True)
class YearValue:
    fiscal_year: int
    value: Decimal | None


@dataclass(frozen=True)
class SummaryMetric:
    code: str
    label: str
    unit: str
    years: list[YearValue]  # the last five fiscal years, oldest first
    latest: Decimal | None  # the newest year's value
    yoy: Decimal | None  # see `yoy`


@dataclass(frozen=True)
class SummaryFlag:
    code: str
    label: str
    severity: str  # warn | alert
    value: Decimal | None
    unit: str  # the rule's unit: pct | x
    period_label: str


@dataclass(frozen=True)
class SummaryValuation:
    scenario_id: int
    scenario_name: str
    price: Decimal | None
    price_date: date | None
    low: Decimal  # min and max of every value per share across cases and methods
    high: Decimal
    base: Decimal | None  # the base case's first method with a value
    upside: Decimal | None  # base / price - 1


@dataclass(frozen=True)
class SummaryNote:
    id: int
    excerpt: str
    created_at: datetime


@dataclass(frozen=True)
class SummaryForecast:
    scenario_id: int
    scenario_name: str
    updated_at: datetime
    last_snapshot_at: datetime | None  # the default scenario's newest snapshot
    newest_filing_date: date | None  # of the newest stored 10-K or 10-Q
    stale: bool  # the scenario was last edited before that filing


@dataclass(frozen=True)
class CompanySummary:
    metrics: list[SummaryMetric]
    flags: list[SummaryFlag]
    valuation: SummaryValuation | None
    notes: list[SummaryNote]
    forecast: SummaryForecast | None
    warnings: list[str] = field(default_factory=list)


def company_summary(session: Session, company: Company) -> CompanySummary:
    """Every block of the summary; never raises a domain error (see the module docstring).
    Without a default scenario, `valuation` and `forecast` are None with no warning."""
    warnings: list[str] = []
    default = next((s for s in scenarios_repo.list_for(session, company.id) if s.is_default), None)
    metrics = _block("Metrics", lambda: _metrics(session, company), _no_metrics(), warnings)
    flags: list[SummaryFlag] = _block("Flags", lambda: _flags(session, company), [], warnings)
    valuation = None
    forecast = None
    if default is not None:
        valuation = _block(
            "Valuation", lambda: _valuation(session, company, default, warnings), None, warnings
        )
    notes: list[SummaryNote] = _block("Notes", lambda: _notes(session, company), [], warnings)
    if default is not None:
        forecast = _block("Forecast", lambda: _forecast(session, company, default), None, warnings)
    return CompanySummary(metrics, flags, valuation, notes, forecast, warnings)


def yoy(unit: str, latest: Decimal | None, prior: Decimal | None) -> Decimal | None:
    """The latest year against the one before: the difference for a percentage, a multiple or a
    number of days; for USD and per-share units the change relative to the size of the prior
    value, quantized to RATIO_PLACES (None from a zero prior). None when either side is None."""
    if latest is None or prior is None:
        return None
    if unit in _DIFFERENCE_UNITS:
        return latest - prior
    if prior == 0:
        return None
    return ((latest - prior) / abs(prior)).quantize(RATIO_PLACES)


_MARKDOWN = (
    (re.compile(r"!?\[([^\]]*)\]\([^)]*\)"), r"\1"),  # links and images keep their text
    (re.compile(r"^[ \t]{0,3}(#{1,6}|>|[-*+]|\d+\.)[ \t]+", re.MULTILINE), ""),  # line markers
    (re.compile(r"[*_~`]+"), ""),  # emphasis, strike-through, code
    (re.compile(r"\s+"), " "),
)


def excerpt(body_md: str) -> str:
    """The first 140 characters of the note with its Markdown markers stripped, on one line."""
    text = body_md
    for pattern, replacement in _MARKDOWN:
        text = pattern.sub(replacement, text)
    return text.strip()[:EXCERPT_LENGTH]


def _block[T](name: str, compute: Callable[[], T], empty: T, warnings: list[str]) -> T:
    try:
        return compute()
    except DOMAIN_ERRORS as error:
        warnings.append(f"{name}: {user_message(error)}")
        return empty


def _metrics(session: Session, company: Company) -> list[SummaryMetric]:
    # One load of the annual statements feeds both the ratio table and the revenue line.
    wanted: list[tuple[str, Freq]] = [("IS", "annual"), ("CF", "annual"), ("BS", "annual")]
    loaded = statement_tables(session, company, wanted, "reported")
    annual = {statement: loaded[(statement, freq)] for statement, freq in wanted}
    table = ratios_service.annual_ratios_from(session, company, annual)
    values = {r.code: r.values for r in table.rows}
    values["revenue"] = _aligned(annual["IS"].periods, annual["IS"].rows, table.periods)
    fiscal = [i for i, p in enumerate(table.periods) if p.fiscal_period == "FY"][-YEARS:]
    return [
        _metric(code, [YearValue(table.periods[i].fiscal_year, values[code][i]) for i in fiscal])
        for code in METRIC_CODES
    ]


def _metric(code: str, years: list[YearValue]) -> SummaryMetric:
    label, unit = _METRIC_LABELS[code]
    latest = years[-1].value if years else None
    prior = years[-2].value if len(years) > 1 else None
    return SummaryMetric(code, label, unit, years, latest, yoy(unit, latest, prior))


def _aligned(
    periods: Sequence[Period], rows: Sequence[Row], wanted: Sequence[Period]
) -> list[Decimal | None]:
    """The revenue row's values on the `wanted` periods (None where the statement has none)."""
    row = next((r for r in rows if r.code == "revenue"), None)
    by_key = {} if row is None else dict(zip((p.key for p in periods), row.values, strict=True))
    return [by_key.get(p.key) for p in wanted]


def _no_metrics() -> list[SummaryMetric]:
    return [_metric(code, []) for code in METRIC_CODES]


def _flags(session: Session, company: Company) -> list[SummaryFlag]:
    table = analysis_service.flags(session, company, "annual").table
    if not table.periods:
        return []
    newest = len(table.periods) - 1
    label = table.periods[newest].label
    raised = [
        SummaryFlag(r.code, r.label, severity, r.values[newest], r.unit, label)
        for r in table.rows
        if (severity := r.severity[newest]) in _SEVERITY_RANK
    ]
    return sorted(raised, key=lambda f: (_SEVERITY_RANK[f.severity], f.label))


def _valuation(
    session: Session, company: Company, default: Scenario, warnings: list[str]
) -> SummaryValuation | None:
    scored = valuation_service.valuation_summary(session, company, default.id)
    for case in scored.cases:
        if case.error is not None:
            warnings.append(f"Valuation, {case.case} case: {case.error}")
    values = [v for c in scored.cases for v in c.value_per_share.values() if v is not None]
    if not values:
        return None
    base_case = next(c for c in scored.cases if c.case == "base")
    base = next(
        (
            value
            for m in scored.methods
            if (value := base_case.value_per_share.get(m.key)) is not None
        ),
        None,
    )
    price = scored.price
    upside = None if base is None or not price else base / price - 1
    return SummaryValuation(
        default.id, default.name, price, scored.price_date, min(values), max(values), base, upside
    )


def _notes(session: Session, company: Company) -> list[SummaryNote]:
    newest = notes_service.list_notes(session, company, None, None, None)[:NOTES]
    return [SummaryNote(n.id, excerpt(n.body_md), n.created_at) for n in newest]


def _forecast(session: Session, company: Company, default: Scenario) -> SummaryForecast:
    snapshot = next(
        (s for s in runs_repo.list_snapshots(session, company.id) if s.scenario_id == default.id),
        None,
    )
    report = facts_repo.latest_report(session, company.id)
    filed = None if report is None else report.filed_at
    return SummaryForecast(
        scenario_id=default.id,
        scenario_name=default.name,
        updated_at=default.updated_at,
        last_snapshot_at=None if snapshot is None else snapshot.created_at,
        newest_filing_date=filed,
        stale=filed is not None and default.updated_at.date() < filed,
    )
