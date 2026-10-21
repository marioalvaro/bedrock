"""The ratio table of a followed company (FR-ANL-01..04)."""

from dataclasses import dataclass, replace
from datetime import date
from decimal import Decimal
from functools import cache

from sqlalchemy.orm import Session

from bedrock.analysis.multiples import MultipleSummary, valuation_summary
from bedrock.models.company import Company
from bedrock.ratios.calculator import RatioFreq, RatioInputs, RatioTable, compute_ratios
from bedrock.ratios.caveats import Caveat, load_caveats
from bedrock.repositories import prices as price_repo
from bedrock.services.statements import Basis, statement_tables
from bedrock.statements.build import StatementTable


def ratios(session: Session, company: Company, freq: RatioFreq, basis: Basis) -> RatioTable:
    """`compute_ratios` over `ratio_inputs` with the company's caveats. A company with no
    statements gives a table with no periods and every ratio row."""
    inputs = ratio_inputs(session, company, freq, basis)
    return compute_ratios(inputs, freq, _caveats().get(company.ticker.upper(), ()))


def ratio_inputs(session: Session, company: Company, freq: RatioFreq, basis: Basis) -> RatioInputs:
    """The `RatioInputs` of `freq` on `basis` from one load of the company's facts (annual: annual
    IS, CF, BS; ttm: TTM IS and CF, quarterly BS and IS), untrimmed. Also read by the analysis
    engines (QoE flags, capital allocation). `prices` holds the company's stored closes."""
    if freq == "annual":
        tables = statement_tables(
            session, company, [("IS", "annual"), ("CF", "annual"), ("BS", "annual")], basis
        )
        inputs = RatioInputs(
            tables[("IS", "annual")], tables[("CF", "annual")], tables[("BS", "annual")]
        )
    else:
        tables = statement_tables(
            session,
            company,
            [("IS", "ttm"), ("CF", "ttm"), ("BS", "quarterly"), ("IS", "quarterly")],
            basis,
        )
        inputs = RatioInputs(
            tables[("IS", "ttm")],
            tables[("CF", "ttm")],
            tables[("BS", "quarterly")],
            tables[("IS", "quarterly")],
        )
    return replace(inputs, prices=price_repo.closes(session, company.id))


@cache
def _caveats() -> dict[str, tuple[Caveat, ...]]:
    return load_caveats()


@dataclass(frozen=True)
class CurrentTtm:
    """The TTM view at the latest close: the close, the TTM income statement and the TTM ratio
    table whose last period is priced at that close (the current multiples)."""

    close: tuple[date, Decimal] | None
    income: StatementTable
    table: RatioTable


def current_ttm(session: Session, company: Company, basis: Basis) -> CurrentTtm:
    """One load of the company's TTM inputs, priced at the latest close (no close: the table is
    the plain TTM one and the price-based numbers are null)."""
    close = price_repo.latest_close(session, company.id)
    inputs = ratio_inputs(session, company, "ttm", basis)
    if close is not None:
        inputs = replace(inputs, as_of=close[0])
    table = compute_ratios(inputs, "ttm", _caveats().get(company.ticker.upper(), ()))
    return CurrentTtm(close, inputs.income, table)


def multiples(
    session: Session, company: Company, basis: Basis
) -> tuple[tuple[date, Decimal] | None, list[MultipleSummary]]:
    """The latest close and the valuation summary: annual history against the current multiples
    (TTM figures at the latest close). Without stored prices every number is null."""
    annual = ratios(session, company, "annual", basis)
    current = current_ttm(session, company, basis)
    return current.close, valuation_summary(annual, current.table)
