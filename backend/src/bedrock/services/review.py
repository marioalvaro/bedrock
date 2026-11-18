"""The earnings review of a company's newest 10-K or 10-Q (FR-ACC-06; docs/erd/accountability.md
"Earnings review"). Computed on read from what is stored: nothing here is persisted."""

from dataclasses import dataclass
from datetime import date, timedelta
from decimal import Decimal

from sqlalchemy.orm import Session

from bedrock.analysis.qoe import FlagTable, evaluate_flags
from bedrock.backtest.review import (
    RESTATED_LIMIT,
    DriverMiss,
    FlagChange,
    LinePick,
    Restated,
    driver_misses,
    flag_changes,
    line_pick,
    restated,
    review_period,
)
from bedrock.backtest.scoring import SCORED_CODES
from bedrock.models.company import Company
from bedrock.models.filing import Filing
from bedrock.ratios.calculator import RatioFreq
from bedrock.repositories import facts as facts_repo
from bedrock.repositories import runs as runs_repo
from bedrock.services import qoe
from bedrock.services.checkpoints import CheckpointView, list_checkpoints
from bedrock.services.guidance import LoggedEntry, guidance_log
from bedrock.services.ratios import ratio_inputs
from bedrock.services.snapshots import SnapshotDetail, detail
from bedrock.services.statements import canonical_items, statement_tables
from bedrock.statements.build import Freq, StatementTable, growth
from bedrock.statements.periods import Period

__all__ = ["DRIVERS_NOTE", "EarningsReview", "ReviewLine", "earnings_review"]

DRIVERS_NOTE = "Drivers are scored on full fiscal years: the next 10-K fills this."
_STATEMENTS = ("IS", "BS", "CF")
_WANTED: list[tuple[str, Freq]] = [(s, f) for s in _STATEMENTS for f in ("annual", "quarterly")]


@dataclass(frozen=True)
class ReviewLine:
    code: str
    label: str
    unit: str
    actual: Decimal | None  # the reported-basis cell at the period
    prior_year: Decimal | None  # the same period a year earlier
    yoy: Decimal | None
    snapshot: LinePick  # nulls without a snapshot before the report
    consensus: LoggedEntry | None
    guidance: LoggedEntry | None  # management's


@dataclass(frozen=True)
class EarningsReview:
    """`filing` None (a manual company, or no 10-K or 10-Q stored) leaves everything else empty;
    `period` None (no table period near the filing's end) leaves the lines and drivers empty."""

    ticker: str
    filing: Filing | None
    period: Period | None
    snapshot: SnapshotDetail | None  # the newest taken on data older than the filing
    lines: list[ReviewLine]
    drivers: list[DriverMiss]
    drivers_note: str | None
    restated: list[Restated]  # the first RESTATED_LIMIT
    restated_total: int
    flags: list[FlagChange]
    checkpoints: list[CheckpointView]  # those whose state changed with the filing


def earnings_review(session: Session, company: Company) -> EarningsReview:
    """The review of `latest_report`: its period, the snapshot taken before it, the key lines
    against it and the guidance log, the drivers that missed most (a 10-K only), and what the
    filing changed (the as-reported read as of the day before it against the one now)."""
    filing = facts_repo.latest_report(session, company.id)
    if filing is None:
        return EarningsReview(company.ticker, None, None, None, [], [], None, [], 0, [], [])
    annual = filing.form == "10-K"
    freq: Freq = "annual" if annual else "quarterly"
    before = filing.filed_at - timedelta(days=1)
    # The key lines are read under the company's classification mode, as the Snapshots view
    # scores them; what the filing changed is read as reported, with no classification on
    # either side, so accepting one never shows as a restatement or a flag change (G55).
    now_tables = statement_tables(session, company, _WANTED, "reported")
    period = review_period(now_tables[("IS", freq)].periods, filing.period_end)
    snapshot = _snapshot_before(session, company, filing)
    lines: list[ReviewLine] = []
    drivers: list[DriverMiss] = []
    if period is not None:
        tables = [now_tables[(s, freq)] for s in _STATEMENTS]
        lines = _lines(session, company, tables, period, snapshot)
        if annual and snapshot is not None:
            drivers = driver_misses(snapshot.cases, period.fiscal_year)
    cutoff = filing.period_end if period is None else period.end
    changed = restated(
        list(_as_reported(session, company, before).values()),
        list(_as_reported(session, company, None).values()),
        cutoff,
    )
    flag_freq: RatioFreq = "annual" if annual else "ttm"
    rules = qoe.effective(session)

    def flags_at(as_of: date | None) -> FlagTable:
        inputs = ratio_inputs(session, company, flag_freq, "reported", as_of=as_of, classified={})
        return evaluate_flags(inputs, rules, flag_freq)

    flags = flag_changes(flags_at(before), flags_at(None))
    return EarningsReview(
        ticker=company.ticker,
        filing=filing,
        period=period,
        snapshot=snapshot,
        lines=lines,
        drivers=drivers,
        drivers_note=None if annual else DRIVERS_NOTE,
        restated=changed[:RESTATED_LIMIT],
        restated_total=len(changed),
        flags=flags,
        checkpoints=[c for c in list_checkpoints(session, company).checkpoints if c.changed],
    )


def _as_reported(
    session: Session, company: Company, as_of: date | None
) -> dict[tuple[str, Freq], StatementTable]:
    return statement_tables(session, company, _WANTED, "reported", as_of=as_of, classified={})


def _snapshot_before(session: Session, company: Company, filing: Filing) -> SnapshotDetail | None:
    """The newest snapshot (by `created_at`, then id) taken on data older than the filing."""
    chosen = next(
        (
            s
            for s in runs_repo.list_snapshots(session, company.id)
            if s.data_as_of is not None and s.data_as_of < filing.filed_at
        ),
        None,
    )
    return None if chosen is None else detail(session, company, chosen.id)


def _lines(
    session: Session,
    company: Company,
    tables: list[StatementTable],
    period: Period,
    snapshot: SnapshotDetail | None,
) -> list[ReviewLine]:
    point = (period.fiscal_year, period.fiscal_period)
    prior = (period.fiscal_year - 1, period.fiscal_period)
    items = {i.code: i for i in canonical_items()}
    entries = [e for e in guidance_log(session, company).entries if e.result.latest]
    lines = []
    for code in SCORED_CODES:
        actual = _value(tables, code, point)
        prior_year = _value(tables, code, prior)
        lines.append(
            ReviewLine(
                code=code,
                label=items[code].label,
                unit=items[code].unit,
                actual=actual,
                prior_year=prior_year,
                yoy=growth(actual, prior_year),
                snapshot=line_pick([] if snapshot is None else snapshot.cases, code, point),
                consensus=_entry(entries, "consensus", code, point),
                guidance=_entry(entries, "management", code, point),
            )
        )
    return lines


def _value(tables: list[StatementTable], code: str, point: tuple[int, str]) -> Decimal | None:
    for table in tables:
        row = next((r for r in table.rows if r.code == code), None)
        if row is None:
            continue
        for p, value in zip(table.periods, row.values, strict=True):
            if (p.fiscal_year, p.fiscal_period) == point:
                return value
    return None


def _entry(
    entries: list[LoggedEntry], source: str, code: str, point: tuple[int, str]
) -> LoggedEntry | None:
    """The latest entry of `source` on the line at the period; `reported` wins over `normalized`."""
    found = [
        e
        for e in entries
        if e.result.entry.source == source
        and e.result.entry.metric == code
        and (e.result.entry.fiscal_year, e.result.entry.fiscal_period) == point
    ]
    return min(found, key=lambda e: e.result.entry.basis != "reported", default=None)
