"""The projection over the recorded filings of the ten development companies (M7d S1,
docs/erd/face-tree.md "Projection"): every line placed once, both balance-sheet roots checked,
and the open lines are the work list `mapping/gaps.py::unclassified_lines` gives."""

import pytest

from bedrock.mapping.gaps import unclassified_lines
from bedrock.statements.projection import project_all
from tests.statements_pipeline import run_pipeline

DEVELOPMENT = ("AAPL", "BA", "COST", "DE", "JNJ", "MSFT", "NFLX", "NKE", "ORCL", "WMT")
BS_ROOTS = {"total_assets", "total_liabilities_and_equity"}


@pytest.mark.parametrize("ticker", DEVELOPMENT)
def test_every_face_line_is_placed_once(ticker: str) -> None:
    pipeline = run_pipeline(ticker)
    face = pipeline.rules.filing_lines
    assert face is not None

    projected = project_all(face, pipeline.items)

    placed = [
        (p.accession_no, p.statement, line.taxonomy, line.concept)
        for p in projected
        for line in p.lines
    ]
    stored = list(
        zip(
            face.lines["accession_no"],
            face.lines["statement"],
            face.lines["taxonomy"],
            face.lines["concept"],
            strict=True,
        )
    )
    assert len(placed) == len(set(placed))
    assert sorted(placed) == sorted(stored)
    for p in projected:
        assert all(len(line.values) == len(p.periods) for line in p.lines)
        assert all(len(line.foots) == len(p.periods) for line in p.lines)


@pytest.mark.parametrize("ticker", DEVELOPMENT)
def test_both_roots_of_every_balance_sheet_have_a_check(ticker: str) -> None:
    pipeline = run_pipeline(ticker)
    assert pipeline.rules.filing_lines is not None

    sheets = [
        p for p in project_all(pipeline.rules.filing_lines, pipeline.items) if p.statement == "BS"
    ]

    assert sheets
    for sheet in sheets:
        checked = {
            code
            for line in sheet.lines
            if line.parent is None and any(f is not None for f in line.foots)
            for code in line.codes
        }
        assert BS_ROOTS <= checked, sheet.accession_no
        assert sheet.foots is not None


@pytest.mark.parametrize("ticker", DEVELOPMENT)
def test_open_lines_of_the_newest_10k_are_its_unclassified_lines(ticker: str) -> None:
    pipeline = run_pipeline(ticker)
    face = pipeline.rules.filing_lines
    assert face is not None
    tenks = face.lines[[str(f).startswith("10-K") for f in face.lines["form"]]]
    newest = max(zip(tenks["filed_at"], tenks["accession_no"], strict=True))[1]
    amounts = face.facts[face.facts["accession_no"] == newest]
    with_amount = {
        (t, c)
        for t, c, v in zip(amounts["taxonomy"], amounts["concept"], amounts["value"], strict=True)
        if v
    }

    projected = [p for p in project_all(face, pipeline.items) if p.accession_no == newest]

    open_lines = {
        (p.statement, line.taxonomy, line.concept)
        for p in projected
        for line in p.lines
        if line.kind == "open" and (line.taxonomy, line.concept) in with_amount
    }
    expected = {
        (u.statement, u.taxonomy, u.concept)
        for u in unclassified_lines(face, pipeline.items)
        if newest in u.filings
    }
    assert open_lines == expected
