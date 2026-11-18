"""The Overview summary, one read (M7c S6, FR-WS-04; docs/erd/workspace.md "Company summary"),
on the recorded AAPL and DE fixtures."""

from collections.abc import Callable
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal

import pytest
from sqlalchemy.orm import Session

from bedrock.models.company import Company
from bedrock.repositories import companies as companies_repo
from bedrock.repositories import facts as facts_repo
from bedrock.services import analysis as analysis_service
from bedrock.services import notes as notes_service
from bedrock.services import qoe as qoe_service
from bedrock.services import ratios as ratios_service
from bedrock.services import snapshots as snapshots_service
from bedrock.services import statements as statements_service
from bedrock.services import valuation as valuation_service
from bedrock.services.scenarios import list_scenarios
from bedrock.services.summary import METRIC_CODES, company_summary, excerpt, yoy

NOW = datetime(2026, 11, 18, 9, 0, tzinfo=UTC)
D = Decimal


def _company(session: Session, ticker: str) -> Company:
    company = companies_repo.get_by_ticker(session, ticker)
    assert company is not None
    return company


@pytest.fixture
def aapl(seed_db: Callable[..., None], db_session: Session) -> Company:
    seed_db("AAPL")
    return _company(db_session, "AAPL")


def _note(session: Session, company: Company, body: str, on: date) -> int:
    data = notes_service.NoteInput(body, None, None, None, on)
    return notes_service.create_note(session, company, data, NOW).id


# --- the pure helpers ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("unit", "latest", "prior", "expected"),
    [
        ("USD", D(110), D(100), D("0.1")),  # relative
        ("USD/shares", D("6.08"), D("6.11"), D("-0.004910")),  # relative, per share
        ("USD/shares", D(1), D(-2), D("1.5")),  # against the size of a negative base
        ("pct", D("0.462"), D("0.441"), D("0.021")),  # the difference in points
        ("x", D("-0.3"), D("0.2"), D("-0.5")),  # a multiple: the difference too
        ("USD", D(5), D(0), None),  # no relative change from zero
        ("USD", None, D(1), None),
        ("pct", D(1), None, None),
    ],
)
def test_yoy_follows_the_unit(
    unit: str, latest: Decimal | None, prior: Decimal | None, expected: Decimal | None
) -> None:
    assert yoy(unit, latest, prior) == expected


@pytest.mark.parametrize(
    ("body", "expected"),
    [
        ("# Thesis\n\nServices **grow** _fast_", "Thesis Services grow fast"),
        ("> quoted `code` and ~~struck~~", "quoted code and struck"),
        ("- one\n* two\n+ three\n1. four", "one two three four"),
        ("see [the 10-K](https://sec.gov/x) and ![chart](c.png)", "see the 10-K and chart"),
        ("", ""),
        ("plain", "plain"),
    ],
)
def test_the_excerpt_drops_markdown_markers(body: str, expected: str) -> None:
    assert excerpt(body) == expected


def test_the_excerpt_keeps_the_first_140_characters() -> None:
    assert excerpt("a" * 200) == "a" * 140
    assert excerpt("**" + "b" * 140 + "**") == "b" * 140


# --- the blocks ---------------------------------------------------------------------------------


def test_the_metrics_are_the_seven_in_order_over_the_last_five_fiscal_years(
    aapl: Company, db_session: Session
) -> None:
    summary = company_summary(db_session, aapl)

    assert [m.code for m in summary.metrics] == list(METRIC_CODES)
    assert METRIC_CODES == (
        "revenue",
        "gross_margin",
        "operating_margin",
        "fcf_margin",
        "roic",
        "eps_diluted",
        "net_debt_to_ebitda",
    )
    table = ratios_service.ratios(db_session, aapl, "annual", "reported")
    fy = [i for i, p in enumerate(table.periods) if p.fiscal_period == "FY"][-5:]
    years = [table.periods[i].fiscal_year for i in fy]
    assert len(years) == 5 and years == sorted(years)
    by_code = {r.code: r for r in table.rows}
    for metric in summary.metrics[1:]:
        row = by_code[metric.code]
        assert (metric.label, metric.unit) == (row.label, row.unit)
        assert [(y.fiscal_year, y.value) for y in metric.years] == [
            (table.periods[i].fiscal_year, row.values[i]) for i in fy
        ]
        assert metric.latest == metric.years[-1].value


def test_revenue_comes_from_the_income_statement_and_its_yoy_is_relative(
    aapl: Company, db_session: Session
) -> None:
    revenue = company_summary(db_session, aapl).metrics[0]

    income = statements_service.statement_tables(db_session, aapl, [("IS", "annual")], "reported")[
        ("IS", "annual")
    ]
    row = next(r for r in income.rows if r.code == "revenue")
    stated = {p.fiscal_year: v for p, v in zip(income.periods, row.values, strict=True)}
    assert (revenue.code, revenue.label, revenue.unit) == ("revenue", row.label, "USD")
    assert all(y.value == stated[y.fiscal_year] for y in revenue.years)
    # AAPL FY2024 10-K, consolidated statements of operations: total net sales $391,035M
    assert {y.fiscal_year: y.value for y in revenue.years}[2024] == D(391_035_000_000)
    prior, latest = revenue.years[-2].value, revenue.years[-1].value
    assert prior is not None and latest is not None
    assert (
        revenue.yoy
        == yoy("USD", latest, prior)
        == ((latest - prior) / prior).quantize(D("0.000001"))
    )


def test_a_pct_metric_s_yoy_is_the_difference_in_points(aapl: Company, db_session: Session) -> None:
    gross = {m.code: m for m in company_summary(db_session, aapl).metrics}["gross_margin"]

    prior, latest = gross.years[-2].value, gross.years[-1].value
    assert prior is not None and latest is not None
    assert gross.yoy == latest - prior


def test_the_flags_are_the_warn_and_alert_rules_of_the_newest_year_alerts_first(
    aapl: Company, db_session: Session
) -> None:
    flags = company_summary(db_session, aapl).flags

    table = analysis_service.flags(db_session, aapl, "annual").table
    newest = len(table.periods) - 1
    raised = [r for r in table.rows if r.severity[newest] in ("warn", "alert")]
    assert {f.code for f in flags} == {r.code for r in raised}
    assert all(f.period_label == table.periods[newest].label for f in flags)
    rank = {"alert": 0, "warn": 1}
    keys = [(rank[f.severity], f.label) for f in flags]
    assert keys == sorted(keys)
    for flag in flags:
        row = next(r for r in raised if r.code == flag.code)
        assert (flag.label, flag.severity, flag.value) == (
            row.label,
            row.severity[newest],
            row.values[newest],
        )


def test_alerts_come_before_warns_and_each_severity_is_by_label(
    aapl: Company, db_session: Session
) -> None:
    # Custom rules on revenue (always positive) raise what they are told to; AAPL's own FY25
    # warn is "Receivables growing faster than revenue".
    for label, warn, alert in (
        ("Zeta always alerts", "0", "0"),
        ("Alpha always alerts", "0", "0"),
        ("Beta always warns", "0", None),
    ):
        rule = qoe_service.CustomRuleInput(label, "revenue", "above", "x", warn, alert)
        qoe_service.create_custom_rule(db_session, rule, NOW)

    flags = company_summary(db_session, aapl).flags

    assert [(f.label, f.severity) for f in flags] == [
        ("Alpha always alerts", "alert"),
        ("Zeta always alerts", "alert"),
        ("Beta always warns", "warn"),
        ("Receivables growing faster than revenue", "warn"),
    ]


def test_without_a_default_scenario_valuation_and_forecast_are_null_with_no_warning(
    aapl: Company, db_session: Session
) -> None:
    summary = company_summary(db_session, aapl)

    assert summary.valuation is None
    assert summary.forecast is None
    assert summary.warnings == []


def test_the_valuation_ranges_over_every_case_and_method_and_the_base_is_the_first_method(
    aapl: Company, db_session: Session
) -> None:
    main = list_scenarios(db_session, aapl, NOW)[0]

    valuation = company_summary(db_session, aapl).valuation

    assert valuation is not None
    scored = valuation_service.valuation_summary(db_session, aapl, main.id)
    values = [v for c in scored.cases for v in c.value_per_share.values() if v is not None]
    base_case = next(c for c in scored.cases if c.case == "base")
    first = next(
        base_case.value_per_share[m.key]
        for m in scored.methods
        if base_case.value_per_share.get(m.key) is not None
    )
    assert (valuation.scenario_id, valuation.scenario_name) == (main.id, main.name)
    assert (valuation.price, valuation.price_date) == (scored.price, scored.price_date)
    assert (valuation.low, valuation.high, valuation.base) == (min(values), max(values), first)
    assert valuation.low <= valuation.base <= valuation.high
    assert scored.price is not None
    assert valuation.upside == first / scored.price - 1


def test_a_case_that_cannot_run_is_a_warning_and_no_case_running_is_no_valuation(
    seed_db: Callable[..., None], db_session: Session
) -> None:
    seed_db("AAPL", "DE")
    de = _company(db_session, "DE")
    list_scenarios(db_session, de, NOW)

    summary = company_summary(db_session, de)

    assert summary.valuation is None
    assert "Valuation, base case: Set these drivers: gross_margin" in summary.warnings
    assert [m.code for m in summary.metrics] == list(METRIC_CODES)  # the other blocks stand


def test_the_notes_are_the_three_newest_with_their_excerpt(
    aapl: Company, db_session: Session
) -> None:
    _note(db_session, aapl, "oldest", date(2026, 1, 1))
    newest = _note(db_session, aapl, "# Newest\n**bold** call", date(2026, 3, 1))
    middle = _note(db_session, aapl, "middle", date(2026, 2, 1))
    second = _note(db_session, aapl, "same day, later id", date(2026, 2, 1))

    notes = company_summary(db_session, aapl).notes

    assert [n.id for n in notes] == [newest, second, middle]
    assert notes[0].excerpt == "Newest bold call"
    assert notes[0].created_at is not None


def test_no_notes_is_an_empty_list(aapl: Company, db_session: Session) -> None:
    assert company_summary(db_session, aapl).notes == []


def test_the_forecast_block_reads_the_default_scenario_its_last_snapshot_and_the_newest_report(
    aapl: Company, db_session: Session
) -> None:
    main = list_scenarios(db_session, aapl, NOW)[0]
    report = facts_repo.latest_report(db_session, aapl.id)
    assert report is not None

    before = company_summary(db_session, aapl).forecast
    assert before is not None
    assert (before.scenario_id, before.scenario_name) == (main.id, main.name)
    assert before.updated_at == main.updated_at
    assert before.last_snapshot_at is None
    assert before.newest_filing_date == report.filed_at
    assert before.stale is False  # edited 2026-11-18, after the newest stored report

    snapshot = snapshots_service.create_snapshot(db_session, aapl, main.id, None, NOW)
    main.updated_at = datetime.combine(report.filed_at, datetime.min.time()) - timedelta(days=1)
    db_session.commit()

    after = company_summary(db_session, aapl).forecast
    assert after is not None
    assert after.last_snapshot_at == snapshot.created_at
    assert after.stale is True


def test_a_manual_company_with_no_data_gives_empty_blocks_and_never_raises(
    seed_db: Callable[..., None], db_session: Session
) -> None:
    from bedrock.services.companies import add_manual_company

    seed_db("AAPL")
    add_manual_company(db_session, "PRIV", "Private Co", 12, None)
    priv = _company(db_session, "PRIV")

    summary = company_summary(db_session, priv)

    assert [m.code for m in summary.metrics] == list(METRIC_CODES)
    assert all(m.years == [] and m.latest is None and m.yoy is None for m in summary.metrics)
    assert summary.flags == [] and summary.notes == []
    assert summary.valuation is None and summary.forecast is None
