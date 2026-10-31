"""The statements use-cases over a refreshed database, checked against the engine-only pipeline."""

from collections.abc import Iterator
from datetime import UTC, datetime

import pytest
from sqlalchemy.orm import Session

from bedrock.mapping.candidates import (
    DEFAULT_CROSSWALK_PATH,
    DEFAULT_VENDOR_PATH,
    candidate_codes,
    load_candidate_index,
)
from bedrock.mapping.config import DEFAULT_ITEMS_PATH, load_canonical_items
from bedrock.mapping.gaps import missing_items
from bedrock.mapping.triage import DEFAULT_TRIAGE_PATH, load_concept_triage
from bedrock.models.company import Company
from bedrock.services.refresh import refresh_company
from bedrock.services.statements import (
    CellNotFound,
    build_statements,
    cell_detail,
    company_key_stats,
    mapping_gaps,
)
from bedrock.statements import build as build_module
from bedrock.statements.coverage import table_coverage
from bedrock.statements.view import trim_periods

from .seed import fake_sources, follow
from .statements_pipeline import STATEMENTS, run_pipeline

NOW = datetime(2026, 10, 8, 14, 30, tzinfo=UTC)


@pytest.fixture
def aapl(db_session: Session) -> Iterator[Company]:
    sources = fake_sources()
    company = follow(db_session, sources.edgar, "AAPL")
    refresh_company(db_session, sources, "AAPL", NOW)
    yield company


@pytest.mark.parametrize("statement", STATEMENTS)
@pytest.mark.parametrize("freq", ["annual", "quarterly"])
def test_the_database_path_gives_the_same_table_as_the_fixture_pipeline(
    db_session: Session, aapl: Company, statement: str, freq: str
) -> None:
    pipeline = run_pipeline("AAPL")
    expected = trim_periods(
        (pipeline.annual if freq == "annual" else pipeline.quarterly)[statement]
    )

    table = build_statements(db_session, aapl, statement, freq)  # type: ignore[arg-type]

    assert table.periods == expected.periods
    assert table.rows == expected.rows
    assert table.balance_check == expected.balance_check
    assert table.rule_warnings == expected.rule_warnings


def test_the_key_stat_load_runs_the_nci_rule_but_no_identity(
    db_session: Session, aapl: Company
) -> None:
    """An identity reads a line that was not loaded as empty and would solve it."""
    from bedrock.services.statements import _key_stat_codes, _load

    subset = _load(db_session, aapl, codes=_key_stat_codes(False))
    full = _load(db_session, aapl)

    assert subset.rules.identities == ()
    assert [i.id for i in full.rules.identities][:2] == ["cash_rollforward", "gross_profit"]
    assert subset.rules.nci_filings is not None
    assert subset.rules.nci_filings == full.rules.nci_filings


def test_annual_income_statement_has_ten_fiscal_years_of_revenue(
    db_session: Session, aapl: Company
) -> None:
    table = build_statements(db_session, aapl, "IS", "annual")

    revenue = next(r for r in table.rows if r.code == "revenue")
    assert sum(v is not None for v in revenue.values) >= 10
    assert all(any(r.values[i] is not None for r in table.rows) for i in range(len(table.periods)))


def test_quarterly_statements_carry_a_derived_q4(db_session: Session, aapl: Company) -> None:
    table = build_statements(db_session, aapl, "IS", "quarterly")

    revenue = next(r for r in table.rows if r.code == "revenue")
    q4 = [i for i, p in enumerate(table.periods) if p.fiscal_period == "Q4"]
    assert q4 and all(revenue.provenance[i] == "derived" for i in q4 if revenue.values[i])


def test_ttm_income_statement_is_built(db_session: Session, aapl: Company) -> None:
    table = build_statements(db_session, aapl, "IS", "ttm")

    assert table.periods and table.periods[-1].key.startswith("TTM-")


def test_a_ttm_balance_sheet_is_rejected(db_session: Session, aapl: Company) -> None:
    with pytest.raises(ValueError, match="TTM"):
        build_statements(db_session, aapl, "BS", "ttm")


def test_balance_sheets_balance_in_every_period_that_is_shown(
    db_session: Session, aapl: Company
) -> None:
    table = build_statements(db_session, aapl, "BS", "quarterly")

    assert table.balance_check is not None
    assert all(check.ok for check in table.balance_check)


def test_normalized_is_the_reported_table_until_adjustments_exist(
    db_session: Session, aapl: Company
) -> None:
    reported = build_statements(db_session, aapl, "IS", "annual", basis="reported")
    normalized = build_statements(db_session, aapl, "IS", "annual", basis="normalized")

    assert normalized == reported


def test_a_company_with_no_data_has_empty_statements(db_session: Session) -> None:
    company = follow(db_session, fake_sources().edgar, "MSFT")

    table = build_statements(db_session, company, "IS", "annual")

    assert table.periods == []


def test_a_reported_cell_names_its_source_filing_and_vintages(
    db_session: Session, aapl: Company
) -> None:
    annual = build_statements(db_session, aapl, "IS", "annual")
    latest = annual.periods[-1]

    cell = cell_detail(db_session, aapl, "revenue", latest.fiscal_year, "FY")

    assert cell.provenance == "reported"
    assert cell.source is not None and cell.source.unit == "USD"
    assert cell.filing is not None and cell.filing.form.startswith("10-K")
    assert cell.vintages and cell.derivation is None
    revenue = next(r for r in annual.rows if r.code == "revenue")
    assert cell.value == revenue.values[-1]


def test_a_derived_cell_shows_its_derivation(db_session: Session, aapl: Company) -> None:
    quarterly = build_statements(db_session, aapl, "IS", "quarterly")
    q4 = next(p for p in reversed(quarterly.periods) if p.fiscal_period == "Q4")

    cell = cell_detail(db_session, aapl, "revenue", q4.fiscal_year, "Q4")

    assert cell.provenance == "derived"
    assert cell.derivation is not None and cell.derivation.inputs
    assert cell.source is None


@pytest.mark.parametrize(
    ("code", "fiscal_year", "fiscal_period"),
    [("not_a_code", 2024, "FY"), ("revenue", 1850, "FY"), ("revenue", 2024, "Q9")],
)
def test_an_unknown_cell_is_not_found(
    db_session: Session, aapl: Company, code: str, fiscal_year: int, fiscal_period: str
) -> None:
    with pytest.raises(CellNotFound):
        cell_detail(db_session, aapl, code, fiscal_year, fiscal_period)


def test_mapping_gaps_list_the_missing_items_like_the_engine_does(
    db_session: Session, aapl: Company
) -> None:
    pipeline = run_pipeline("AAPL")

    gaps = mapping_gaps(db_session, aapl)

    expected = missing_items(pipeline.annual, pipeline.items)
    assert [m.code for m in gaps.missing_items] == [m.code for m in expected]
    assert "short_term_debt" in {m.code for m in gaps.missing_items}  # empty for Apple by design


def test_unmapped_concepts_are_real_concepts_of_the_latest_10k_that_nothing_maps(
    db_session: Session, aapl: Company
) -> None:
    gaps = mapping_gaps(db_session, aapl)

    assert gaps.unmapped_concepts
    assert all(c.taxonomy != "dei" for c in gaps.unmapped_concepts)
    mappings = run_pipeline("AAPL").mappings
    mapped = set(zip(mappings["taxonomy"], mappings["concept"], strict=True))
    assert all((c.taxonomy, c.concept) not in mapped for c in gaps.unmapped_concepts)


def test_unmapped_concepts_carry_the_suggested_codes_and_those_come_first(
    db_session: Session, aapl: Company
) -> None:
    gaps = mapping_gaps(db_session, aapl)

    index = load_candidate_index(
        DEFAULT_VENDOR_PATH, DEFAULT_CROSSWALK_PATH, load_canonical_items(DEFAULT_ITEMS_PATH)
    )
    assert all(
        c.suggested_codes == candidate_codes(index, c.taxonomy, c.concept)
        for c in gaps.unmapped_concepts
    )
    assert any(c.suggested_codes for c in gaps.unmapped_concepts)
    open_ones = [c for c in gaps.unmapped_concepts if c.classification is None]
    has_suggestion = [bool(c.suggested_codes) for c in open_ones]
    assert has_suggestion == sorted(has_suggestion, reverse=True)  # among the open ones


def test_unmapped_concepts_carry_the_shipped_triage_and_the_classified_come_last(
    db_session: Session, aapl: Company
) -> None:
    gaps = mapping_gaps(db_session, aapl)

    triage = load_concept_triage(DEFAULT_TRIAGE_PATH, load_canonical_items(DEFAULT_ITEMS_PATH))
    assert all(
        c.classification == triage.get((c.taxonomy, c.concept)) for c in gaps.unmapped_concepts
    )
    classified = [c.classification is not None for c in gaps.unmapped_concepts]
    assert any(classified)
    assert classified == sorted(classified)


def test_the_full_load_carries_the_cover_page_counts_and_the_key_stat_load_does_not(
    db_session: Session, aapl: Company
) -> None:
    from bedrock.services.statements import _key_stat_codes, _load

    subset = _load(db_session, aapl, codes=_key_stat_codes(False))
    full = _load(db_session, aapl)

    assert subset.rules.cover_shares is None
    assert full.rules.cover_shares is not None
    assert not full.rules.cover_shares.empty
    assert set(full.rules.cover_shares["code"]) == {"shares_outstanding"}


def test_mapping_gaps_carry_the_coverage_of_every_statement_and_frequency(
    db_session: Session, aapl: Company
) -> None:
    pipeline = run_pipeline("AAPL")
    mapped = set(pipeline.mappings["canonical_code"])

    gaps = mapping_gaps(db_session, aapl)

    assert [(c.statement, c.freq) for c in gaps.coverage] == [
        (s, f) for s in STATEMENTS for f in ("annual", "quarterly")
    ]
    for result in gaps.coverage:
        tables = pipeline.annual if result.freq == "annual" else pipeline.quarterly
        table = tables[result.statement]
        expected = table_coverage(table, pipeline.items, mapped, table.rule_warnings)
        assert result == expected


def test_mapping_gaps_list_the_rule_warnings_with_the_line_label(
    db_session: Session, aapl: Company
) -> None:
    pipeline = run_pipeline("AAPL")
    expected = pipeline.annual["CF"].rule_warnings
    assert expected  # S7: Apple's cash roll-forward is refused in three periods

    gaps = mapping_gaps(db_session, aapl)

    assert [w.warning for w in gaps.rule_warnings] == list(expected)
    labels = {i.code: i.label for i in pipeline.items}
    assert all(w.label == labels[w.warning.code] for w in gaps.rule_warnings)
    units = {i.code: i.unit for i in pipeline.items}
    assert all(w.unit == units[w.warning.code] for w in gaps.rule_warnings)


def test_a_company_with_no_facts_has_no_coverage_and_no_warnings(
    db_session: Session,
) -> None:
    sources = fake_sources()
    empty = follow(db_session, sources.edgar, "MSFT")

    gaps = mapping_gaps(db_session, empty)

    assert (gaps.coverage, gaps.rule_warnings) == ([], [])


@pytest.mark.parametrize(
    "build",
    [
        pytest.param(lambda session, company: company_key_stats(session, company), id="key stats"),
        pytest.param(lambda session, company: mapping_gaps(session, company), id="mapping gaps"),
    ],
)
def test_the_cells_are_solved_once_for_all_the_tables_a_request_builds(
    db_session: Session, aapl: Company, monkeypatch: pytest.MonkeyPatch, build
) -> None:  # type: ignore[no-untyped-def]  # `build` is a parametrized lambda
    calls: list[int] = []
    real = build_module.solve_cells

    def counting(*args, **kwargs):  # type: ignore[no-untyped-def]  # a spy on the real solver
        calls.append(1)
        return real(*args, **kwargs)

    monkeypatch.setattr(build_module, "solve_cells", counting)

    build(db_session, aapl)

    assert len(calls) == 1
