"""Valuation inputs and valuations of a scenario's cases (FR-VAL-01..03; docs/erd/valuation.md
"Inputs", "Market data", "Multiple targets"), on the recorded AAPL, MSFT and COST fixtures."""

from collections.abc import Callable
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any

import pytest
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from bedrock.forecast.errors import ForecastUnavailable
from bedrock.ingest.protocol import PriceRow
from bedrock.models.company import Company
from bedrock.models.scenario import Scenario
from bedrock.models.valuation_input import ValuationInput
from bedrock.repositories import companies as companies_repo
from bedrock.repositories import prices as price_repo
from bedrock.services import comps as comps_service
from bedrock.services import ratios as ratios_service
from bedrock.services import statements as statements_service
from bedrock.services import valuation as svc
from bedrock.services.errors import InvalidValuationInput, ScenarioNotFound
from bedrock.services.scenarios import (
    DriverRowInput,
    delete_scenario,
    driver_grid,
    list_scenarios,
    put_drivers,
)
from bedrock.valuation.inputs import INPUTS
from bedrock.valuation.interface import MultipleDetails

NOW = datetime(2026, 11, 6, 9, 0, tzinfo=UTC)
D = Decimal


@pytest.fixture
def followed(seed_db: Callable[..., None]) -> None:
    seed_db("AAPL", "MSFT", "COST")


def _company(session: Session, ticker: str) -> Company:
    company = companies_repo.get_by_ticker(session, ticker)
    assert company is not None
    return company


@pytest.fixture
def aapl(followed: None, db_session: Session) -> Company:
    return _company(db_session, "AAPL")


def _main(session: Session, company: Company) -> Scenario:
    return list_scenarios(session, company, NOW)[0]


def _put(session: Session, company: Company, case: str, **values: str | None) -> svc.InputsView:
    scenario = _main(session, company)
    return svc.put_valuation_inputs(session, company, scenario.id, case, list(values.items()), NOW)


def _inputs(session: Session, company: Company, case: str) -> dict[str, svc.InputRow]:
    view = svc.valuation_inputs(session, company, _main(session, company).id, case)
    return {r.code: r for r in view.rows}


def _result(valuation: svc.CaseValuation, key: str):  # type: ignore[no-untyped-def]
    return next(r for r in valuation.results if r.key == key)


# --- inputs ---------------------------------------------------------------------------------


def test_a_fresh_case_shows_the_catalog_defaults_and_the_derived_values(
    db_session: Session, aapl: Company
) -> None:
    scenario = _main(db_session, aapl)

    view = svc.valuation_inputs(db_session, aapl, scenario.id, "base")

    assert [r.code for r in view.rows] == [d.code for d in INPUTS]
    by = {r.code: r for r in view.rows}
    assert (by["discount_method"].value, by["discount_method"].source) == ("wacc", "default")
    assert by["beta"].value == "1"
    assert by["mid_year"].value == "true"
    assert by["pe_source"].value == "own_history"
    assert by["tax_rate"].source == "derived"
    assert by["tax_rate"].value is not None
    assert by["tax_rate"].note is not None and "tax rate" in by["tax_rate"].note
    assert by["debt_weight"].source == "derived" and by["debt_weight"].value is not None
    assert all(r.own is None for r in view.rows)
    assert [y.index for y in view.forecast_years] == [1, 2, 3, 4, 5]
    assert view.forecast_years[0].label.startswith("FY") and view.warnings == []


def test_a_base_value_is_inherited_by_bull_until_bull_sets_its_own(
    db_session: Session, aapl: Company
) -> None:
    _put(db_session, aapl, "base", beta="1.2")

    inherited = _inputs(db_session, aapl, "bull")["beta"]
    assert (inherited.value, inherited.source, inherited.own) == ("1.2", "base", None)
    assert _inputs(db_session, aapl, "base")["beta"].source == "own"

    _put(db_session, aapl, "bull", beta="1.5")
    own = _inputs(db_session, aapl, "bull")["beta"]
    assert (own.value, own.source, own.own) == ("1.5", "own", "1.5")
    assert _inputs(db_session, aapl, "base")["beta"].value == "1.2"

    _put(db_session, aapl, "bull", beta=None)
    assert _inputs(db_session, aapl, "bull")["beta"].source == "base"
    _put(db_session, aapl, "base", beta=None)
    assert _inputs(db_session, aapl, "bull")["beta"].source == "default"


def test_a_put_stores_the_parsed_text_and_leaves_codes_not_in_the_body(
    db_session: Session, aapl: Company
) -> None:
    _put(db_session, aapl, "base", beta="1.20", mid_year="false")
    _put(db_session, aapl, "base", beta="2")

    rows = _inputs(db_session, aapl, "base")
    assert rows["beta"].own == "2"
    assert rows["mid_year"].own == "false"


def test_reset_clears_only_that_case(db_session: Session, aapl: Company) -> None:
    scenario = _main(db_session, aapl)
    _put(db_session, aapl, "base", beta="1.2")
    _put(db_session, aapl, "bull", beta="1.5", terminal_growth="0.02")

    view = svc.reset_valuation_inputs(db_session, aapl, scenario.id, "bull")

    assert all(r.own is None for r in view.rows)
    assert {r.code: r.source for r in view.rows}["beta"] == "base"
    assert _inputs(db_session, aapl, "base")["beta"].own == "1.2"


def test_derived_values_follow_the_cases_drivers(db_session: Session, aapl: Company) -> None:
    scenario = _main(db_session, aapl)
    years = driver_grid(db_session, aapl, scenario.id, "bull").forecast_years
    base_tax = _inputs(db_session, aapl, "bull")["tax_rate"].value
    put_drivers(
        db_session,
        aapl,
        scenario.id,
        "bull",
        [DriverRowInput("tax_rate", "value", [(y, D("0.31")) for y in years])],
        NOW,
    )

    bull_tax = _inputs(db_session, aapl, "bull")["tax_rate"]

    assert bull_tax.value is not None and D(bull_tax.value) == D("0.31")
    assert bull_tax.value != base_tax


@pytest.mark.parametrize(
    ("rows", "message"),
    [
        ([("nope", "1")], "Unknown valuation input 'nope'"),
        ([("beta", "1"), ("beta", "2")], "beta given twice"),
        ([("beta", "1e5")], "beta must be a number"),
        ([("beta", "inf")], "beta must be a number"),
        ([("beta", "9")], "beta must be in"),
        ([("discount_method", "maybe")], "discount_method must be one of wacc, direct"),
        ([("mid_year", "maybe")], "mid_year must be true or false"),
        ([("pe_year", "0")], "pe_year must be in"),
        ([("comps_set_id", "x")], "comps_set_id must be a comps set id"),
        ([("comps_set_id", "99999")], "No such comps set"),
    ],
)
def test_a_bad_row_is_refused_and_nothing_is_written(
    db_session: Session, aapl: Company, rows: list[tuple[str, str]], message: str
) -> None:
    scenario = _main(db_session, aapl)

    with pytest.raises(InvalidValuationInput, match=message):
        svc.put_valuation_inputs(
            db_session, aapl, scenario.id, "base", [("terminal_growth", "0.02"), *rows], NOW
        )

    assert db_session.scalar(select(func.count()).select_from(ValuationInput)) == 0


def test_a_comps_set_of_another_company_is_refused(
    db_session: Session, aapl: Company, followed: None
) -> None:
    msft = _company(db_session, "MSFT")
    other = comps_service.create_set(db_session, msft, "Theirs", ["COST"], NOW)

    with pytest.raises(InvalidValuationInput, match="No such comps set"):
        _put(db_session, aapl, "base", comps_set_id=str(other.id))


def test_an_unknown_case_or_scenario_is_refused(db_session: Session, aapl: Company) -> None:
    from bedrock.services.errors import InvalidScenario

    scenario = _main(db_session, aapl)
    with pytest.raises(InvalidScenario):
        svc.valuation_inputs(db_session, aapl, scenario.id, "nope")
    with pytest.raises(ScenarioNotFound):
        svc.valuation_inputs(db_session, aapl, 999_999, "base")
    msft = _company(db_session, "MSFT")
    with pytest.raises(ScenarioNotFound):
        svc.valuation_inputs(db_session, msft, scenario.id, "base")


def test_deleting_a_scenario_deletes_its_inputs(db_session: Session, aapl: Company) -> None:
    from bedrock.services.scenarios import SettingsInput, create_scenario

    other = create_scenario(db_session, aapl, SettingsInput("Other"), NOW)
    svc.put_valuation_inputs(db_session, aapl, other.id, "base", [("beta", "1.3")], NOW)
    assert db_session.scalar(select(func.count()).select_from(ValuationInput)) == 1

    delete_scenario(db_session, aapl, other.id)

    assert db_session.scalar(select(func.count()).select_from(ValuationInput)) == 0


# --- valuation ------------------------------------------------------------------------------


def test_a_case_valuation_has_the_dcf_the_default_targets_and_the_market(
    db_session: Session, aapl: Company
) -> None:
    scenario = _main(db_session, aapl)

    valuation = svc.case_valuation(db_session, aapl, scenario.id, "base")

    assert [r.key for r in valuation.results] == ["dcf_fcff", "multiple:pe", "multiple:ev_ebitda"]
    dcf = valuation.results[0]
    assert dcf.error is None and dcf.value_per_share is not None
    assert dcf.upside is not None and valuation.caveats == {}
    market = valuation.market
    assert market.price is not None and market.price_date is not None
    assert market.shares is not None and market.shares > 0
    assert valuation.valuation_date == market.price_date


def test_own_history_needs_three_years_of_priced_ratios(db_session: Session, aapl: Company) -> None:
    scenario = _main(db_session, aapl)

    # The recorded prices cover one year, so no annual multiple exists yet.
    short = svc.case_valuation(db_session, aapl, scenario.id, "base")
    assert _result(short, "multiple:pe").error == "P/E: fewer than 3 years of history"

    ends = [p.end for p in ratios_service.ratios(db_session, aapl, "annual", "normalized").periods]
    rows = [PriceRow(end, D(100 + 20 * i), D(100 + 20 * i), 1) for i, end in enumerate(ends[-5:])]
    price_repo.insert_new(db_session, aapl.id, rows)
    db_session.commit()
    valuation = svc.case_valuation(db_session, aapl, scenario.id, "base")

    pe = _result(valuation, "multiple:pe")
    assert pe.error is None and isinstance(pe.details, MultipleDetails)
    assert pe.details.source == "own_history" and pe.details.percentile == D("0.5")
    assert pe.details.n is not None and pe.details.n >= 3
    assert pe.value_per_share is not None


@pytest.mark.parametrize("call", ["case", "summary"])
def test_a_valuation_request_builds_the_statements_once(
    db_session: Session, aapl: Company, monkeypatch: pytest.MonkeyPatch, call: str
) -> None:
    # NFR-02: the statements are the costly part of a valuation (≈0.3 s for AAPL); the history
    # loaded for the forecast also feeds the own-history multiples (P/E and EV/EBITDA by default).
    scenario = _main(db_session, aapl)
    loads: list[str] = []
    real = statements_service._load

    def counted(*args: Any, **kwargs: Any) -> Any:
        loads.append("load")
        return real(*args, **kwargs)

    monkeypatch.setattr(statements_service, "_load", counted)
    if call == "case":
        svc.case_valuation(db_session, aapl, scenario.id, "base")
    else:
        svc.valuation_summary(db_session, aapl, scenario.id)

    assert len(loads) == 1


def test_bull_values_above_base_above_bear(db_session: Session, aapl: Company) -> None:
    scenario = _main(db_session, aapl)

    per_share = {
        case: svc.case_valuation(db_session, aapl, scenario.id, case).results[0].value_per_share
        for case in ("base", "bull", "bear")
    }

    assert per_share["bull"] is not None and per_share["base"] is not None
    assert per_share["bear"] is not None
    assert per_share["bull"] > per_share["base"] > per_share["bear"]


def test_a_manual_multiple_and_a_direct_rate_value_without_references(
    db_session: Session, aapl: Company
) -> None:
    _put(
        db_session, aapl, "base",
        discount_method="direct", discount_rate="0.1",
        pe_source="manual", pe_multiple="20",
        ev_ebitda_source="off", ev_sales_source="manual", ev_sales_multiple="6",
    )  # fmt: skip

    valuation = svc.case_valuation(db_session, aapl, _main(db_session, aapl).id, "base")

    assert [r.key for r in valuation.results] == ["dcf_fcff", "multiple:pe", "multiple:ev_sales"]
    assert valuation.results[0].details is not None
    assert all(r.error is None for r in valuation.results)


def test_the_peer_median_comes_from_the_comps_set(db_session: Session, aapl: Company) -> None:
    peers = comps_service.create_set(db_session, aapl, "Peers", ["MSFT", "COST"], NOW)
    _put(db_session, aapl, "base", pe_source="peer_median", comps_set_id=str(peers.id))

    valuation = svc.case_valuation(db_session, aapl, _main(db_session, aapl).id, "base")

    pe = _result(valuation, "multiple:pe")
    assert pe.error is None and isinstance(pe.details, MultipleDetails)
    assert pe.details.source == "peer_median"
    assert pe.details.comps_set == (peers.id, "Peers")


def test_a_peer_median_without_a_set_or_with_a_deleted_set_is_that_targets_error(
    db_session: Session, aapl: Company
) -> None:
    scenario = _main(db_session, aapl)
    _put(db_session, aapl, "base", pe_source="peer_median")
    no_set = svc.case_valuation(db_session, aapl, scenario.id, "base")
    assert _result(no_set, "multiple:pe").error == "Choose a comps set"

    peers = comps_service.create_set(db_session, aapl, "Peers", ["MSFT"], NOW)
    _put(db_session, aapl, "base", comps_set_id=str(peers.id))
    comps_service.delete_set(db_session, aapl, peers.id)
    gone = svc.case_valuation(db_session, aapl, scenario.id, "base")

    assert _result(gone, "multiple:pe").error == "The comps set no longer exists"
    assert _result(gone, "dcf_fcff").error is None  # the other results are unaffected


def test_the_summary_lists_the_three_cases_in_order_with_the_union_of_methods(
    db_session: Session, aapl: Company
) -> None:
    scenario = _main(db_session, aapl)
    _put(db_session, aapl, "bull", p_fcf_source="manual", p_fcf_multiple="25")

    summary = svc.valuation_summary(db_session, aapl, scenario.id)

    assert [c.case for c in summary.cases] == ["base", "bull", "bear"]
    keys = [m.key for m in summary.methods]
    assert keys == ["dcf_fcff", "multiple:pe", "multiple:ev_ebitda", "multiple:p_fcf"]
    base, bull, _ = summary.cases
    assert base.error is None and base.value_per_share["dcf_fcff"] is not None
    assert "multiple:p_fcf" not in base.value_per_share
    assert bull.value_per_share["multiple:p_fcf"] is not None
    assert summary.price is not None


def test_a_case_that_cannot_run_is_an_error_of_its_summary_column(
    seed_db: Callable[..., None], db_session: Session
) -> None:
    seed_db("AAPL", "DE")
    de = _company(db_session, "DE")
    scenario = _main(db_session, de)

    summary = svc.valuation_summary(db_session, de, scenario.id)

    assert [c.case for c in summary.cases] == ["base", "bull", "bear"]
    assert summary.cases[0].error == "Set these drivers: gross_margin"
    assert summary.cases[0].value_per_share == {} and summary.cases[0].errors == {}
    assert summary.methods == []
    with pytest.raises(ForecastUnavailable, match="Set these drivers: gross_margin"):
        svc.case_valuation(db_session, de, scenario.id, "base")
    view = svc.valuation_inputs(db_session, de, scenario.id, "base")
    assert {r.code: r.value for r in view.rows}["tax_rate"] is None
    assert view.warnings == ["Set these drivers: gross_margin"]
