"""Classifications in the statements (M7d S4, docs/erd/face-tree.md "Guards"), over the recorded
development companies. The answers are a deterministic fixture: each open line of a company, in
the order `classify/questions.py::open_lines` gives them, takes in turn its first candidate (one
code), its first two candidates (a combined line) or no code."""

from collections.abc import Mapping
from dataclasses import replace
from decimal import Decimal
from functools import cache

import pytest

from bedrock.classify.questions import open_lines
from bedrock.mapping.config import parse_formula
from bedrock.statements.build import StatementTable, build_statement
from bedrock.statements.cells import solve_cells
from bedrock.statements.imports import company_calendar
from bedrock.statements.structure import Concept
from tests.statements_pipeline import Pipeline, run_pipeline

DEVELOPMENT = ("AAPL", "MSFT", "COST", "DE", "BA", "JNJ", "NFLX", "NKE", "ORCL", "WMT")
STATEMENTS = ("IS", "BS", "CF")
FREQS = ("annual", "quarterly")
Tables = dict[tuple[str, str], StatementTable]
Values = dict[tuple[str, str], Decimal | None]


def answers(pipeline: Pipeline) -> dict[Concept, tuple[str, ...]]:
    face = pipeline.rules.filing_lines
    assert face is not None
    out: dict[Concept, tuple[str, ...]] = {}
    for at, asked in enumerate(open_lines(face, pipeline.items)):
        codes = tuple(c.code for c in asked.question.candidates)
        concept = (asked.question.taxonomy, asked.question.concept)
        out[concept] = (codes[:1], codes[:2], ())[at % 3]
    return out


def tables(pipeline: Pipeline, classified: Mapping[Concept, tuple[str, ...]]) -> Tables:
    face = pipeline.rules.filing_lines
    assert face is not None
    rules = replace(pipeline.rules, filing_lines=replace(face, classified=classified))
    return {
        (s, f): build_statement(pipeline.canonical, pipeline.items, s, f, rules=rules)  # type: ignore[arg-type]
        for s in STATEMENTS
        for f in FREQS
    }


def values(built: Tables) -> Values:
    return {
        (row.code, period.key): row.values[at]
        for table in built.values()
        for row in table.rows
        for at, period in enumerate(table.periods)
    }


@cache
def compared(ticker: str) -> tuple[Pipeline, Values, Values, Tables]:
    pipeline = run_pipeline(ticker)
    before = {
        (s, f): (pipeline.annual if f == "annual" else pipeline.quarterly)[s]
        for s in STATEMENTS
        for f in FREQS
    }
    after = tables(pipeline, answers(pipeline))
    return pipeline, values(before), values(after), after


@pytest.mark.parametrize("ticker", DEVELOPMENT)
def test_with_no_classification_the_tables_are_identical(ticker: str) -> None:
    pipeline = run_pipeline(ticker)

    built = tables(pipeline, {})

    for (statement, freq), table in built.items():
        expected = (pipeline.annual if freq == "annual" else pipeline.quarterly)[statement]
        assert table == expected


@pytest.mark.parametrize("ticker", DEVELOPMENT)
def test_every_cell_a_classification_changes_was_empty(ticker: str) -> None:
    """Residuals move by the guard below; every other changed cell was empty."""
    pipeline, before, after, _ = compared(ticker)
    residuals = {i.code for i in pipeline.items if i.residual}

    changed = [k for k in after if k[0] not in residuals and after[k] != before.get(k)]

    assert [key for key in changed if before.get(key) is not None] == []


@pytest.mark.parametrize("ticker", DEVELOPMENT)
def test_no_subtotal_or_total_moves(ticker: str) -> None:
    pipeline, before, after, _ = compared(ticker)
    parents = {i.parent for i in pipeline.items if i.parent is not None}

    moved = [
        key
        for key in after
        if key[0] in parents and before.get(key) is not None and after[key] != before[key]
    ]

    assert moved == []


@pytest.mark.parametrize("ticker", DEVELOPMENT)
def test_each_residual_moves_by_exactly_the_cells_filled_under_its_parent(ticker: str) -> None:
    pipeline, before, after, _ = compared(ticker)
    wrong = []
    for item in pipeline.items:
        if not item.residual or item.derive is None:
            continue
        operands = [
            (sign, code) for sign, code in parse_formula(item.derive) if code != item.parent
        ]
        for key, now in after.items():
            if key[0] != item.code or now is None or before.get(key) is None:
                continue
            period = key[1]
            filled = sum(
                (
                    sign * (after[(code, period)] or Decimal(0))
                    for sign, code in operands
                    if before.get((code, period)) is None and after.get((code, period)) is not None
                ),
                Decimal(0),
            )
            if now - before[key] != filled:  # type: ignore[operator]
                wrong.append((key, before[key], now, filled))

    assert wrong == []


@pytest.mark.parametrize("ticker", DEVELOPMENT)
def test_a_marked_cell_is_the_signed_sum_of_its_face_lines(ticker: str) -> None:
    pipeline = run_pipeline(ticker)
    face = pipeline.rules.filing_lines
    assert face is not None
    rules = replace(pipeline.rules, filing_lines=replace(face, classified=answers(pipeline)))
    calendar = company_calendar(pipeline.canonical, rules.imported)
    sign = {i.code: i.sign for i in pipeline.items}

    cells = solve_cells(pipeline.canonical, pipeline.items, calendar, rules).cells

    for (code, _), cell in cells.items():
        if cell.classified_by is None:
            continue
        assert cell.provenance == "derived" and cell.derivation is not None
        named = {i.code for i in cell.derivation.inputs}
        assert set(cell.classified_by) <= named
        assert cell.value == sign[code] * sum((i.value for i in cell.derivation.inputs), Decimal(0))


def test_the_fixture_answers_fill_and_mark_cells() -> None:
    """The guards above are not vacuous: across the companies, classifications fill cells and
    mark some of them."""
    filled = marked = 0
    for ticker in DEVELOPMENT:
        _, before, after, built = compared(ticker)
        filled += sum(1 for key in after if before.get(key) is None and after[key] is not None)
        marked += sum(
            1
            for table in built.values()
            for row in table.rows
            for marks in row.classified_by
            if marks is not None
        )

    assert filled > 0
    assert marked > 0
