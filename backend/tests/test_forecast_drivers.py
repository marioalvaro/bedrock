"""The driver catalog (docs/erd/forecasting.md "Drivers (M4)"). Pure."""

from decimal import Decimal
from typing import get_args

import pytest

from bedrock.forecast.drivers import DRIVERS, UnknownDriver, check_bounds, driver_def, drivers_for
from bedrock.statements.cell_types import Provenance

# The ERD table, in its order.
CATALOG = [
    "revenue_growth",
    "segment_growth",
    "volume_growth",
    "price_growth",
    "gross_margin",
    "rnd_pct_revenue",
    "sga_pct_revenue",
    "other_opex_pct_revenue",
    "d_and_a_pct_revenue",
    "sbc_pct_revenue",
    "other_nonoperating_pct_revenue",
    "interest_rate",
    "tax_rate",
    "nci_share",
    "receivable_days",
    "inventory_days",
    "payable_days",
    "capex_pct_revenue",
    "debt_issued",
    "debt_repaid",
    "min_cash",
    "buybacks",
    "dividend_payout",
    "share_change",
]
REVENUE = {"revenue_growth", "segment_growth", "volume_growth", "price_growth"}
COMMON = [c for c in CATALOG if c not in REVENUE]


def test_forecast_is_a_provenance() -> None:
    assert "forecast" in get_args(Provenance)


def test_the_catalog_lists_the_erd_drivers_in_order() -> None:
    assert [d.code for d in DRIVERS] == CATALOG


def test_units_and_groups_follow_the_erd() -> None:
    by_code = {d.code: d for d in DRIVERS}
    assert {c for c, d in by_code.items() if d.unit == "days"} == {
        "receivable_days",
        "inventory_days",
        "payable_days",
    }
    assert {c for c, d in by_code.items() if d.unit == "USD"} == {
        "debt_issued",
        "debt_repaid",
        "min_cash",
        "buybacks",
    }
    assert by_code["tax_rate"].group == "Below the line"
    assert by_code["capex_pct_revenue"].group == "Investment"
    assert by_code["share_change"].group == "Shareholders"


def test_growth_method_has_revenue_growth_only() -> None:
    assert [d.code for d in drivers_for("growth")] == ["revenue_growth", *COMMON]


def test_segments_method_expands_one_driver_per_series_in_the_given_order() -> None:
    drivers = drivers_for("segments", [(7, "iPhone"), (3, "Mac")])
    assert [d.code for d in drivers] == ["segment_growth:7", "segment_growth:3", *COMMON]
    assert [d.label for d in drivers[:2]] == ["iPhone growth", "Mac growth"]
    assert drivers[0].unit == "pct"


def test_segments_method_without_series_has_no_revenue_driver() -> None:
    assert [d.code for d in drivers_for("segments")] == COMMON


def test_volume_price_method_has_volume_and_price_growth() -> None:
    assert [d.code for d in drivers_for("volume_price", [(7, "iPhone")])] == [
        "volume_growth",
        "price_growth",
        *COMMON,
    ]


def test_driver_def_resolves_a_segment_code_and_rejects_unknown_codes() -> None:
    assert driver_def("segment_growth:12").code == "segment_growth:12"
    assert driver_def("gross_margin").label == "Gross margin"
    for bad in ("nope", "segment_growth:", "segment_growth:x", "segment_growth"):
        with pytest.raises(UnknownDriver):
            driver_def(bad)


@pytest.mark.parametrize(
    ("code", "inside", "outside"),
    [
        # (-1, 10]: -1 excluded, 10 included
        ("revenue_growth", ["-0.9999", "10", "0"], ["-1", "10.0001"]),
        ("segment_growth:4", ["-0.5", "10"], ["-1", "11"]),
        ("price_growth", ["10"], ["-1"]),
        # [-1, 1]
        ("gross_margin", ["-1", "1"], ["-1.0001", "1.0001"]),
        ("other_opex_pct_revenue", ["-1", "1"], ["-1.01", "1.01"]),
        # NCI can take a loss while the parent earns (DE FY2022-25)
        ("nci_share", ["-1", "-0.0058", "1"], ["-1.0001", "1.0001"]),
        # [0, 1]
        ("rnd_pct_revenue", ["0", "1"], ["-0.0001", "1.0001"]),
        ("tax_rate", ["0", "1"], ["-0.01", "1.01"]),
        # [0, 730]
        ("receivable_days", ["0", "730"], ["-1", "730.5"]),
        # [0, 10^15)
        ("buybacks", ["0", "999999999999999"], ["-1", "1000000000000000"]),
        ("min_cash", ["0"], ["1E15"]),
        # [0, 5]
        ("dividend_payout", ["0", "5"], ["-0.1", "5.1"]),
        # (-1, 1]
        ("share_change", ["1", "-0.99"], ["-1", "1.01"]),
    ],
)
def test_value_bounds_at_every_edge(code: str, inside: list[str], outside: list[str]) -> None:
    for value in inside:
        assert check_bounds(code, "value", Decimal(value)) is None, value
    for value in outside:
        message = check_bounds(code, "value", Decimal(value))
        assert message is not None and code in message, value


@pytest.mark.parametrize(
    ("code", "inside", "outside"),
    [
        # pct: |offset| <= 1, whatever the value bounds are
        ("revenue_growth", ["-1", "1"], ["-1.0001", "1.0001"]),
        ("tax_rate", ["-1", "1"], ["-1.01", "1.01"]),
        # days: |offset| <= 730
        ("payable_days", ["-730", "730"], ["-730.01", "731"]),
        # USD: |offset| < 10^15
        ("debt_issued", ["-999999999999999", "999999999999999"], ["-1E15", "1E15"]),
    ],
)
def test_offset_bounds_at_every_edge(code: str, inside: list[str], outside: list[str]) -> None:
    for value in inside:
        assert check_bounds(code, "offset", Decimal(value)) is None, value
    for value in outside:
        message = check_bounds(code, "offset", Decimal(value))
        assert message is not None and "offset" in message, value


@pytest.mark.parametrize("value", ["NaN", "Infinity", "-Infinity", "sNaN"])
def test_a_non_finite_value_is_out_of_bounds(value: str) -> None:
    for kind in ("value", "offset"):
        assert check_bounds("gross_margin", kind, Decimal(value)) is not None
