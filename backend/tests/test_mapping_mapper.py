from datetime import date
from decimal import Decimal

import pandas as pd

from bedrock.mapping.mapper import CANONICAL_COLUMNS, map_facts
from tests.engine_data import fact, facts, item, mappings

FY22 = (date(2021, 7, 1), date(2022, 6, 30))
FY23 = (date(2022, 7, 1), date(2023, 6, 30))
FY24 = (date(2023, 7, 1), date(2024, 6, 30))


def value_at(frame: pd.DataFrame, code: str, period: tuple[date, date]) -> Decimal:
    rows = frame[
        (frame["code"] == code)
        & (frame["period_start"] == period[0])
        & (frame["period_end"] == period[1])
    ]
    assert len(rows) == 1
    value = rows.iloc[0]["value"]
    assert isinstance(value, Decimal)
    return value


def test_output_has_the_canonical_columns() -> None:
    out = map_facts(
        facts([fact("Revenues", *FY23, 5)]),
        mappings(("revenue", "Revenues", 0)),
        [item("revenue")],
    )

    assert list(out.columns) == CANONICAL_COLUMNS
    row = out.iloc[0]
    assert (row["code"], row["concept"], row["taxonomy"], row["kind"]) == (
        "revenue",
        "Revenues",
        "us-gaap",
        "flow",
    )
    assert row["accession_no"] == "0001-24-000001"
    assert row["form"] == "10-K"


def test_tag_switch_between_years_uses_the_fallback_concept() -> None:
    latest = facts(
        [
            fact("SalesRevenueNet", *FY22, 100),
            fact("Revenues", *FY23, 120),
            fact("Revenues", *FY24, 140),
            fact("SalesRevenueNet", *FY24, 999),  # lower priority, same period: ignored
        ]
    )

    out = map_facts(
        latest,
        mappings(("revenue", "Revenues", 0), ("revenue", "SalesRevenueNet", 1)),
        [item("revenue")],
    )

    assert value_at(out, "revenue", FY22) == 100
    assert value_at(out, "revenue", FY24) == 140
    old = out[out["period_end"] == FY22[1]].iloc[0]
    assert old["concept"] == "SalesRevenueNet"  # provenance records the concept used
    assert len(out) == 3


def test_an_override_beats_a_default_even_with_a_worse_priority_number() -> None:
    latest = facts(
        [fact("Revenues", *FY23, 120), fact("CustomRevenue", *FY23, 77, taxonomy="aapl")]
    )

    out = map_facts(
        latest,
        mappings(("revenue", "Revenues", 0), ("revenue", "aapl:CustomRevenue", 0, True)),
        [item("revenue")],
    )

    assert value_at(out, "revenue", FY23) == 77
    assert out.iloc[0]["taxonomy"] == "aapl"


def test_a_default_fills_a_period_the_override_lacks() -> None:
    latest = facts([fact("Revenues", *FY22, 100), fact("CustomRevenue", *FY23, 77)])

    out = map_facts(
        latest,
        mappings(("revenue", "Revenues", 0), ("revenue", "CustomRevenue", 0, True)),
        [item("revenue")],
    )

    assert value_at(out, "revenue", FY22) == 100
    assert value_at(out, "revenue", FY23) == 77


def test_only_facts_in_the_items_unit_count() -> None:
    latest = facts(
        [
            fact("EarningsPerShareDiluted", *FY23, "6.11", unit="USD/shares"),
            fact("EarningsPerShareDiluted", *FY22, "5.00", unit="USD"),
        ]
    )

    out = map_facts(
        latest,
        mappings(("eps_diluted", "EarningsPerShareDiluted", 0)),
        [item("eps_diluted", kind="average", unit="USD/shares")],
    )

    assert len(out) == 1
    assert value_at(out, "eps_diluted", FY23) == Decimal("6.11")


def test_values_are_multiplied_by_sign() -> None:
    latest = facts([fact("PaymentsToAcquirePPE", *FY23, 30)])

    out = map_facts(
        latest,
        mappings(("capex", "PaymentsToAcquirePPE", 0)),
        [item("capex", "CF", sign=-1)],
    )

    assert value_at(out, "capex", FY23) == -30


def test_instants_keep_a_null_period_start() -> None:
    latest = facts([fact("Cash", None, FY23[1], 50)])

    out = map_facts(latest, mappings(("cash", "Cash", 0)), [item("cash", "BS", kind="instant")])

    assert len(out) == 1
    assert out.iloc[0]["period_start"] is None or pd.isna(out.iloc[0]["period_start"])
    assert out.iloc[0]["kind"] == "instant"


def test_ytd_and_discrete_facts_for_one_end_are_both_kept() -> None:
    q2_end = date(2022, 12, 31)
    latest = facts(
        [
            fact("Revenues", date(2022, 10, 1), q2_end, 40),
            fact("Revenues", date(2022, 7, 1), q2_end, 70),
        ]
    )

    out = map_facts(latest, mappings(("revenue", "Revenues", 0)), [item("revenue")])

    assert len(out) == 2


def test_unmapped_facts_and_unknown_codes_are_ignored() -> None:
    latest = facts([fact("Revenues", *FY23, 5), fact("Whatever", *FY23, 9)])

    out = map_facts(
        latest,
        mappings(("revenue", "Revenues", 0), ("ghost", "Whatever", 0)),
        [item("revenue")],
    )

    assert list(out["code"]) == ["revenue"]


def test_no_facts_gives_an_empty_frame_with_columns() -> None:
    out = map_facts(facts([]), mappings(("revenue", "Revenues", 0)), [item("revenue")])

    assert out.empty
    assert list(out.columns) == CANONICAL_COLUMNS
