"""The ratio table of a followed company (FR-ANL-01..04)."""

from functools import cache

from sqlalchemy.orm import Session

from bedrock.models.company import Company
from bedrock.ratios.calculator import RatioFreq, RatioInputs, RatioTable, compute_ratios
from bedrock.ratios.caveats import Caveat, load_caveats
from bedrock.services.statements import Basis, statement_tables


def ratios(session: Session, company: Company, freq: RatioFreq, basis: Basis) -> RatioTable:
    """`compute_ratios` over `ratio_inputs` with the company's caveats. A company with no
    statements gives a table with no periods and every ratio row."""
    inputs = ratio_inputs(session, company, freq, basis)
    return compute_ratios(inputs, freq, _caveats().get(company.ticker.upper(), ()))


def ratio_inputs(session: Session, company: Company, freq: RatioFreq, basis: Basis) -> RatioInputs:
    """The `RatioInputs` of `freq` on `basis` from one load of the company's facts (annual: annual
    IS, CF, BS; ttm: TTM IS and CF, quarterly BS and IS), untrimmed. Also read by the analysis
    engines (QoE flags, capital allocation)."""
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
    return inputs


@cache
def _caveats() -> dict[str, tuple[Caveat, ...]]:
    return load_caveats()
