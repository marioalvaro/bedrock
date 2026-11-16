"""The market series behind the valuation's discount defaults (docs/erd/valuation.md "Market
defaults"): their daily refresh, and the defaults read off the stored data."""

from datetime import UTC, date, datetime, timedelta
from decimal import Decimal

from sqlalchemy.orm import Session

from bedrock.ingest.protocol import SourceUnavailable
from bedrock.ingest.sources import Sources
from bedrock.models.company import Company
from bedrock.repositories import macro
from bedrock.repositories import prices as prices_repo
from bedrock.valuation.market import BETA_MONTHS, beta, market_defaults

RISK_FREE_SERIES = ("DGS10", "^TNX")  # FRED first, when it has been fetched
ERP_SERIES = "DAMODARAN_ERP"
INDEX_SERIES = "^GSPC"
_DUE_AFTER = timedelta(hours=20)


def refresh_market(session: Session, sources: Sources, now: datetime) -> list[str]:
    """Fetch and store each market series; a failing one is a warning, the others are kept."""
    if sources.market is None:
        return []
    warnings: list[str] = []
    today = now.astimezone(UTC).date()
    for name in ("risk_free", "erp", "index"):
        try:
            series = getattr(sources.market, name)(today)
        except SourceUnavailable as error:
            warnings.append(f"{name} not updated: {error}")
            continue
        macro.upsert(
            session,
            series.series_id,
            series.title,
            series.frequency,
            series.source,
            series.rows,
            now,
        )
        session.commit()
    return warnings


def market_due(session: Session, now: datetime) -> bool:
    """Whether the market series are older than a day's refresh (or were never fetched)."""
    fetched = macro.fetched_at(session, INDEX_SERIES)
    if fetched is None:
        return True
    return now.astimezone(UTC).replace(tzinfo=None) - fetched >= _DUE_AFTER


def discount_defaults(session: Session, company: Company) -> dict[str, Decimal]:
    """The market defaults of `risk_free_rate`, `equity_risk_premium` and `beta` from the stored
    series and the company's adjusted closes; what is missing is left out."""
    risk_free = next(
        (found for s in RISK_FREE_SERIES if (found := macro.latest(session, s)) is not None), None
    )
    erp = macro.latest(session, ERP_SERIES)
    index = macro.observations(session, INDEX_SERIES)
    company_beta = None
    if index:
        since = _months_before(index[-1][0], BETA_MONTHS + 2)
        company_beta = beta(prices_repo.adj_closes(session, company.id, since), index)
    return market_defaults(
        risk_free_pct=None if risk_free is None else risk_free[1],
        erp_pct=None if erp is None else erp[1],
        beta=company_beta,
    )


def _months_before(day: date, months: int) -> date:
    y, m = divmod(day.year * 12 + day.month - 1 - months, 12)
    return date(y, m + 1, 1)
