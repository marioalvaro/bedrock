"""Multiple targets (docs/erd/valuation.md "Multiple targets (M5)"): each target kind on a
hand-computed forecast, the percentile, the reference rules and the errors. Pure."""

from decimal import Decimal

import pytest

from bedrock.valuation.inputs import resolve_inputs
from bedrock.valuation.interface import (
    Bridge,
    MarketData,
    MultipleDetails,
    MultipleReference,
    ValuationForecast,
    ValuationResult,
)
from bedrock.valuation.multiples import MultipleTargets, own_history_reference, percentile
from tests.valuation_data import YEARS, annual_forecast, forecast, market

D = Decimal
OFF = {f"{m}_source": "off" for m in ("pe", "ev_ebitda", "p_fcf", "ev_sales")}
FY27 = {
    "net_income_common": 50,
    "free_cash_flow": 40,
    "operating_income": 80,
    "d_and_a": 20,
    "revenue": 400,
}


def _forecast(fy27: dict[str, int] | None = None) -> ValuationForecast:
    lines: dict[int, dict[str, int]] = {y: {"revenue": 1} for y in YEARS}
    lines[2027] = fy27 if fy27 is not None else FY27
    return forecast(annual_forecast(lines))


def _market(
    shares: int | None = 10, references: dict[str, MultipleReference] | None = None
) -> MarketData:
    return market(
        shares=shares, bridge=Bridge(D(200), D(50), D(0), D(0), D(0)), references=references
    )


def _run(
    texts: dict[str, str], m: MarketData | None = None, fy27: dict[str, int] | None = None
) -> list[ValuationResult]:
    inputs = resolve_inputs({}, {**OFF, **texts}, is_base=True, derived={})
    return MultipleTargets().value(_forecast(fy27), m or _market(), inputs)


def _one(
    texts: dict[str, str], m: MarketData | None = None, fy27: dict[str, int] | None = None
) -> ValuationResult:
    results = _run(texts, m, fy27)
    assert len(results) == 1
    return results[0]


def _details(result: ValuationResult) -> MultipleDetails:
    assert isinstance(result.details, MultipleDetails)
    return result.details


def _manual(m: str, multiple: str) -> dict[str, str]:
    return {f"{m}_source": "manual", f"{m}_multiple": multiple, f"{m}_year": "2"}


def test_pe_is_an_equity_multiple_of_net_income_to_common() -> None:
    result = _one(_manual("pe", "20"))
    # equity = 20 × 50; EV = equity + net claims (200 − 50)
    assert (result.key, result.method, result.label) == ("multiple:pe", "multiple_target", "P/E")
    assert (result.equity_value, result.enterprise_value) == (D(1000), D(1150))
    assert (result.value_per_share, result.upside) == (D(100), D(1))
    assert result.error is None
    assert _details(result) == MultipleDetails(
        ratio_code="pe",
        metric_label="net income to common",
        fiscal_year=2027,
        period_label="FY27E",
        metric_value=D(50),
        multiple=D(20),
        source="manual",
        percentile=None,
        n=None,
        comps_set=None,
    )


def test_p_fcf_is_an_equity_multiple_of_free_cash_flow() -> None:
    result = _one(_manual("p_fcf", "25"))
    assert (result.label, result.equity_value, result.enterprise_value) == (
        "P/FCF",
        D(1000),
        D(1150),
    )
    assert _details(result).metric_label == "free cash flow"


def test_ev_ebitda_is_an_ev_multiple_of_operating_income_plus_d_and_a() -> None:
    result = _one(_manual("ev_ebitda", "12"))
    # EV = 12 × (80 + 20); equity = EV − 150
    assert (result.label, result.enterprise_value, result.equity_value) == (
        "EV/EBITDA",
        D(1200),
        D(1050),
    )
    assert result.value_per_share == D(105)
    assert (_details(result).metric_label, _details(result).metric_value) == ("EBITDA", D(100))


def test_ev_sales_is_an_ev_multiple_of_revenue() -> None:
    result = _one(_manual("ev_sales", "3"))
    assert (result.label, result.enterprise_value, result.equity_value) == (
        "EV/Sales",
        D(1200),
        D(1050),
    )
    assert _details(result).metric_label == "revenue"


def test_the_year_input_picks_the_forecast_year() -> None:
    result = _one({"pe_source": "manual", "pe_multiple": "10", "pe_year": "1"})
    assert _error(result) == "FY26E net income to common is not positive"  # FY26 has none


def test_targets_run_in_order_and_off_ones_are_omitted() -> None:
    texts = {**_manual("ev_sales", "3"), **_manual("pe", "20"), **_manual("ev_ebitda", "12")}
    assert [r.key for r in _run(texts)] == [
        "multiple:pe",
        "multiple:ev_ebitda",
        "multiple:ev_sales",
    ]
    assert _run({}) == []


def test_an_own_history_reference_sets_the_multiple() -> None:
    reference = MultipleReference(D(15), "own_history", percentile=D("0.5"), n=4)
    result = _one(
        {"pe_source": "own_history", "pe_year": "2"}, m=_market(references={"pe": reference})
    )
    assert result.equity_value == D(750)
    details = _details(result)
    assert (details.source, details.multiple, details.percentile, details.n) == (
        "own_history",
        D(15),
        D("0.5"),
        4,
    )


def test_a_peer_median_reference_carries_its_set() -> None:
    reference = MultipleReference(D(10), "peer_median", n=3, comps_set=(7, "Megacaps"))
    result = _one(
        {"ev_ebitda_source": "peer_median", "ev_ebitda_year": "2"},
        m=_market(references={"ev_ebitda": reference}),
    )
    assert result.enterprise_value == D(1000)
    assert _details(result).comps_set == (7, "Megacaps")


def _error(result: ValuationResult) -> str | None:
    assert (result.enterprise_value, result.equity_value, result.value_per_share) == (None,) * 3
    assert result.upside is None
    return result.error


@pytest.mark.parametrize("metric", [0, -10])
def test_a_metric_that_is_not_positive_is_an_error(metric: int) -> None:
    result = _one(_manual("pe", "20"), fy27={**FY27, "net_income_common": metric})
    assert _error(result) == "FY27E net income to common is not positive"


def test_a_missing_metric_is_an_error() -> None:
    result = _one(_manual("ev_ebitda", "12"), fy27={"revenue": 400})
    assert _error(result) == "FY27E EBITDA is not positive"


def test_a_reference_with_an_error_passes_it_on() -> None:
    reference = MultipleReference(None, "own_history", error="P/E: fewer than 3 years of history")
    result = _one(
        {"pe_source": "own_history", "pe_year": "2"}, m=_market(references={"pe": reference})
    )
    assert _error(result) == "P/E: fewer than 3 years of history"
    assert result.key == "multiple:pe"


def test_a_missing_reference_is_an_error() -> None:
    assert (
        _error(_one({"pe_source": "peer_median", "pe_year": "2"})) == "P/E: no reference multiple"
    )


def test_a_manual_source_without_a_multiple_is_an_error() -> None:
    assert (
        _error(_one({"ev_sales_source": "manual", "ev_sales_year": "2"}))
        == "Set the EV/Sales multiple"
    )


def test_a_reference_that_is_not_positive_is_an_error() -> None:
    reference = MultipleReference(D(-4), "peer_median", comps_set=(7, "Megacaps"))
    result = _one(
        {"pe_source": "peer_median", "pe_year": "2"}, m=_market(references={"pe": reference})
    )
    assert _error(result) == "P/E: the multiple is not positive"


def test_no_share_count_leaves_the_value_per_share_null() -> None:
    result = _one(_manual("pe", "20"), m=_market(shares=None))
    assert result.error == "No share count"
    assert result.equity_value == D(1000) and result.value_per_share is None


# -- percentile and own-history reference ----------------------------------------------------


@pytest.mark.parametrize(
    ("p", "expected"),
    [
        ("0", "10"),
        ("1", "40"),
        ("0.5", "25"),
        ("0.25", "17.5"),  # position 0.75: 10 + 0.75 × 10
        ("0.6", "28"),  # position 1.8: 20 + 0.8 × 10
    ],
)
def test_percentile_interpolates_linearly(p: str, expected: str) -> None:
    assert percentile([D(30), D(10), D(40), D(20)], D(p)) == D(expected)


def test_the_percentile_of_one_value_is_that_value() -> None:
    assert percentile([D(7)], D("0.3")) == D(7)


def test_the_percentile_of_nothing_raises() -> None:
    with pytest.raises(ValueError):
        percentile([], D("0.5"))


def test_own_history_leaves_out_nulls_and_values_not_positive() -> None:
    values = [None, D(-5), D(0), D(30), D(10), D(20)]
    assert own_history_reference(values, D("0.5"), "P/E") == MultipleReference(
        D(20), "own_history", percentile=D("0.5"), n=3
    )


def test_own_history_needs_three_values() -> None:
    assert own_history_reference([D(10), None, D(20)], D("0.5"), "P/E") == MultipleReference(
        None, "own_history", percentile=D("0.5"), n=2, error="P/E: fewer than 3 years of history"
    )
