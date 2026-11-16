"""The ratio table of a followed company (FR-ANL-01..04)."""

from collections.abc import Mapping
from dataclasses import dataclass, replace
from datetime import date
from decimal import Decimal
from functools import cache

from sqlalchemy.orm import Session

from bedrock.analysis.multiples import MultipleSummary, valuation_summary
from bedrock.models.company import Company
from bedrock.ratios.calculator import RatioFreq, RatioInputs, RatioTable, compute_ratios
from bedrock.ratios.caveats import Caveat, load_caveats
from bedrock.ratios.explain import RatioExplanation, explain_ratio
from bedrock.repositories import prices as price_repo
from bedrock.services.errors import RatioCellNotFound
from bedrock.services.statements import Basis, statement_tables
from bedrock.statements.build import Freq, StatementTable


def ratios(session: Session, company: Company, freq: RatioFreq, basis: Basis) -> RatioTable:
    """`compute_ratios` over `ratio_inputs` with the company's caveats. A company with no
    statements gives a table with no periods and every ratio row."""
    inputs = ratio_inputs(session, company, freq, basis)
    return compute_ratios(inputs, freq, _caveats().get(company.ticker.upper(), ()))


def ratio_cell(
    session: Session,
    company: Company,
    freq: RatioFreq,
    basis: Basis,
    code: str,
    fiscal_year: int,
    fiscal_period: str,
) -> RatioExplanation:
    """How one value of the ratio table was computed: its formula and inputs (FR-ANL-11). Raises
    `RatioCellNotFound` for an unknown ratio or a period that is not a column of the table."""
    inputs = ratio_inputs(session, company, freq, basis)
    caveats = _caveats().get(company.ticker.upper(), ())
    try:
        return explain_ratio(inputs, freq, code, (fiscal_year, fiscal_period), caveats)
    except KeyError as error:
        raise RatioCellNotFound(f"{code} {fiscal_year} {fiscal_period}") from error


_TABLES: dict[RatioFreq, list[tuple[str, Freq]]] = {
    "annual": [("IS", "annual"), ("CF", "annual"), ("BS", "annual")],
    "ttm": [("IS", "ttm"), ("CF", "ttm"), ("BS", "quarterly"), ("IS", "quarterly")],
}


def ratio_inputs(session: Session, company: Company, freq: RatioFreq, basis: Basis) -> RatioInputs:
    """The `RatioInputs` of `freq` on `basis` from one load of the company's facts (annual: annual
    IS, CF, BS; ttm: TTM IS and CF, quarterly BS and IS), untrimmed. Also read by the analysis
    engines (QoE flags, capital allocation). `prices` holds the company's stored closes."""
    wanted = _TABLES["annual" if freq == "annual" else "ttm"]  # any other freq reads as TTM
    tables = statement_tables(session, company, wanted, basis)
    return replace(_inputs(tables, freq), prices=price_repo.closes(session, company.id))


def _inputs(tables: Mapping[tuple[str, Freq], StatementTable], freq: RatioFreq) -> RatioInputs:
    if freq == "annual":
        return RatioInputs(
            tables[("IS", "annual")], tables[("CF", "annual")], tables[("BS", "annual")]
        )
    return RatioInputs(
        tables[("IS", "ttm")],
        tables[("CF", "ttm")],
        tables[("BS", "quarterly")],
        tables[("IS", "quarterly")],
    )


def annual_ratios_from(
    session: Session, company: Company, annual: Mapping[str, StatementTable]
) -> RatioTable:
    """`ratios(session, company, "annual", basis)` from annual IS, CF and BS tables the caller has
    already loaded on that basis, untrimmed (`services/scenarios.py::load_history`'s), so a
    valuation builds the statements once (NFR-02)."""
    inputs = RatioInputs(annual["IS"], annual["CF"], annual["BS"])
    inputs = replace(inputs, prices=price_repo.closes(session, company.id))
    return compute_ratios(inputs, "annual", _caveats().get(company.ticker.upper(), ()))


def company_caveat(company: Company, ratio_code: str) -> str | None:
    """The company's caveat text for a ratio code (`ratios/caveats.yaml`), if it has one."""
    for caveat in _caveats().get(company.ticker.upper(), ()):
        if ratio_code in caveat.codes:
            return caveat.text
    return None


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
    return _current(company, ratio_inputs(session, company, "ttm", basis), close)


def _current(
    company: Company, inputs: RatioInputs, close: tuple[date, Decimal] | None
) -> CurrentTtm:
    if close is not None:
        inputs = replace(inputs, as_of=close[0])
    table = compute_ratios(inputs, "ttm", _caveats().get(company.ticker.upper(), ()))
    return CurrentTtm(close, inputs.income, table)


def multiples(
    session: Session, company: Company, basis: Basis
) -> tuple[tuple[date, Decimal] | None, list[MultipleSummary]]:
    """The latest close and the valuation summary: annual history against the current multiples
    (TTM figures at the latest close), from one build of the statements. Without stored prices
    every number is null."""
    tables = statement_tables(session, company, [*_TABLES["annual"], *_TABLES["ttm"]], basis)
    prices = price_repo.closes(session, company.id)
    caveats = _caveats().get(company.ticker.upper(), ())
    annual = compute_ratios(replace(_inputs(tables, "annual"), prices=prices), "annual", caveats)
    close = price_repo.latest_close(session, company.id)
    current = _current(company, replace(_inputs(tables, "ttm"), prices=prices), close)
    return current.close, valuation_summary(annual, current.table)
