"""Thesis checkpoints of a company (FR-NOTE-03; docs/erd/workspace.md "Thesis checkpoints (M7c)").

A checkpoint's state is computed on read, now and as of the day before the newest 10-K or 10-Q,
so nothing but the statement is stored. Not audited (a statement of the thesis, not an
assumption of the model)."""

from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal, InvalidOperation
from typing import Any

from sqlalchemy.orm import Session

from bedrock.analysis import formula as formulas
from bedrock.analysis.checkpoints import (
    AtRiskBy,
    Evaluation,
    State,
    Statement,
    evaluate_checkpoint,
    format_statement,
    parse_statement,
    statement_unit,
)
from bedrock.analysis.formula import FormulaError
from bedrock.analysis.qoe import LEVEL_LIMIT, LEVEL_PLACES, formula_names
from bedrock.core.clock import naive_utc
from bedrock.models.company import Company
from bedrock.models.filing import Filing
from bedrock.models.thesis_checkpoint import CheckpointFreq, ThesisCheckpoint
from bedrock.ratios.calculator import Operands, RatioFreq
from bedrock.ratios.explain import name_unit
from bedrock.repositories import checkpoints as repo
from bedrock.repositories import facts as facts_repo
from bedrock.services.errors import CheckpointNotFound, InvalidCheckpoint
from bedrock.services.ratios import ratio_inputs
from bedrock.statements.periods import Period

LABEL_LIMIT = 120


@dataclass(frozen=True)
class CheckpointInput:
    """A checkpoint as the user sends it. `margin` is text: a number (a fraction) or a constant
    such as "1%"; None or blank means no margin."""

    statement: str
    label: str | None = None
    freq: CheckpointFreq = "ttm"
    margin: str | None = None


@dataclass(frozen=True)
class CheckpointView:
    """A stored checkpoint (margin a plain decimal) with its state now (`evaluation`, read at
    `period`) and the state as of the day before the newest report (`previous_state`; None for a
    company with no report or a statement that no longer parses, whose `error` is then the
    `FormulaError` text). `unit` is the one both sides are in (`statement_unit`), None when
    they have none or the statement no longer parses."""

    row: ThesisCheckpoint
    evaluation: Evaluation
    period: Period | None
    previous_state: State | None
    error: str | None
    unit: str | None

    @property
    def state(self) -> State:
        return self.evaluation.state

    @property
    def at_risk_by(self) -> AtRiskBy | None:
        return self.evaluation.at_risk_by

    @property
    def changed(self) -> bool:
        return self.previous_state is not None and self.previous_state != self.state


@dataclass(frozen=True)
class CheckpointList:
    """The newest report (None for a manual company or none stored) and every checkpoint of the
    company, in id order."""

    report: Filing | None
    checkpoints: list[CheckpointView]


_UNKNOWN = Evaluation("unknown", None, None, None, None, None)


def list_checkpoints(session: Session, company: Company) -> CheckpointList:
    """Every checkpoint with its states. Never fails on a stored statement: one that no longer
    parses lists as `unknown` with its `error`."""
    report = facts_repo.latest_report(session, company.id)
    return CheckpointList(report, checkpoints_for_report(session, company, report))


def checkpoints_for_report(
    session: Session, company: Company, report: Filing | None
) -> list[CheckpointView]:
    """Every checkpoint, its previous state read before `report` (the newest 10-K or 10-Q, as
    `latest_report` gives it; None for none)."""
    return _views(session, company, report, repo.list_for(session, company.id))


def create_checkpoint(
    session: Session, company: Company, data: CheckpointInput, now: datetime
) -> CheckpointView:
    """Validates (`InvalidCheckpoint`), stores and commits; `created_at` / `updated_at` are `now`
    as naive UTC."""
    stamp = naive_utc(now)
    fields = _fields(data)
    row = repo.add(
        session,
        ThesisCheckpoint(company_id=company.id, created_at=stamp, updated_at=stamp, **fields),
    )
    checkpoint_id = row.id
    session.commit()
    return _committed(session, company, checkpoint_id)


def update_checkpoint(
    session: Session, company: Company, checkpoint_id: int, data: CheckpointInput, now: datetime
) -> CheckpointView:
    """Replaces every field, validated as `create_checkpoint`, and commits; `updated_at` is
    `now`. Raises CheckpointNotFound for an id that is not the company's (before validating)."""
    row = repo.get(session, company.id, checkpoint_id)
    if row is None:
        raise CheckpointNotFound(checkpoint_id)
    for field, value in _fields(data).items():
        setattr(row, field, value)
    row.updated_at = naive_utc(now)
    session.commit()
    return _committed(session, company, checkpoint_id)


def delete_checkpoint(session: Session, company: Company, checkpoint_id: int) -> None:
    """Deletes and commits. Raises CheckpointNotFound for an id that is not the company's."""
    row = repo.get(session, company.id, checkpoint_id)
    if row is None:
        raise CheckpointNotFound(checkpoint_id)
    repo.delete(session, row)
    session.commit()


def _fields(data: CheckpointInput) -> dict[str, Any]:
    """The validated column values (nothing is stored when this raises)."""
    try:
        statement = parse_statement(data.statement, formula_names())
    except FormulaError as error:
        raise InvalidCheckpoint(str(error)) from error
    label = (data.label or "").strip() or format_statement(statement)
    if len(label) > LABEL_LIMIT:
        raise InvalidCheckpoint(f"A label has at most {LABEL_LIMIT} characters")
    return {
        "label": label,
        "statement": data.statement.strip(),
        "freq": data.freq,
        "margin": parse_margin(data.margin),
    }


def parse_margin(text: str | None) -> Decimal | None:
    """A margin as typed: None or blank -> None; a decimal literal, or a constant formula of
    numbers ("1%", "0.5% + 0.5%"), in ASCII and without "_". It must be finite, >= 0, below
    `LEVEL_LIMIT` and have at most `LEVEL_PLACES` decimal places (G21). Raises
    InvalidCheckpoint otherwise."""
    if text is None or not text.strip():
        return None
    stripped = text.strip()
    if not stripped.isascii() or "_" in stripped:  # Decimal reads "1_0" and other scripts' digits
        raise InvalidCheckpoint(f"A margin is a number such as 0.01 or 1%, not '{stripped}'")
    try:
        number: Decimal | None = Decimal(stripped)
    except InvalidOperation:
        number = _constant(stripped)
    if number is None or not number.is_finite():
        raise InvalidCheckpoint(f"A margin is a number such as 0.01 or 1%, not '{stripped}'")
    if number < 0:
        raise InvalidCheckpoint(f"A margin cannot be negative ({stripped})")
    if number >= LEVEL_LIMIT:
        raise InvalidCheckpoint(f"A margin must be below {LEVEL_LIMIT} ({stripped})")
    exponent = number.normalize().as_tuple().exponent
    if isinstance(exponent, int) and exponent < -LEVEL_PLACES:
        raise InvalidCheckpoint(f"A margin has at most {LEVEL_PLACES} decimal places")
    return number


def _constant(text: str) -> Decimal | None:
    """The value of a formula of numbers only, None when it is not one or has no value."""
    try:
        return formulas.constant_value(formulas.parse(text, frozenset()))
    except FormulaError:
        return None


@dataclass(frozen=True)
class _Read:
    """One frequency's operands and the periods of its income statement, oldest first."""

    ops: Operands
    periods: list[Period]

    def evaluate(self, statement: Statement, margin: Decimal | None) -> Evaluation:
        return evaluate_checkpoint(statement, margin, self.ops, [p.point for p in self.periods])

    def period_of(self, evaluation: Evaluation) -> Period | None:
        """The period the evaluation was read at."""
        return next((p for p in self.periods if p.point == evaluation.point), None)


def _views(
    session: Session, company: Company, report: Filing | None, rows: list[ThesisCheckpoint]
) -> list[CheckpointView]:
    """One `ratio_inputs` load per frequency in use, now and before the report (at most four)."""
    parsed: dict[int, Statement | FormulaError] = {}
    for row in rows:
        try:
            parsed[row.id] = parse_statement(row.statement, formula_names())
        except FormulaError as error:
            parsed[row.id] = error
    freqs = {r.freq for r in rows if isinstance(parsed[r.id], Statement)}
    before = None if report is None else report.before_as_of
    now_reads = {f: _read(session, company, f, None) for f in freqs}
    before_reads = {} if before is None else {f: _read(session, company, f, before) for f in freqs}
    views = []
    for row in rows:
        statement = parsed[row.id]
        if isinstance(statement, FormulaError):
            views.append(CheckpointView(row, _UNKNOWN, None, None, str(statement), None))
            continue
        now = now_reads[row.freq]
        evaluation = now.evaluate(statement, row.margin)
        earlier = before_reads.get(row.freq)
        previous = None if earlier is None else earlier.evaluate(statement, row.margin).state
        period = now.period_of(evaluation)
        unit = statement_unit(statement, name_unit)
        views.append(CheckpointView(row, evaluation, period, previous, None, unit))
    return views


def _read(session: Session, company: Company, freq: RatioFreq, as_of: date | None) -> _Read:
    inputs = ratio_inputs(session, company, freq, "reported", as_of=as_of)
    return _Read(Operands(inputs, freq), list(inputs.income.periods))


def _committed(session: Session, company: Company, checkpoint_id: int) -> CheckpointView:
    """The checkpoint re-read after a commit expired it, with its states."""
    row = repo.get(session, company.id, checkpoint_id)
    assert row is not None
    report = facts_repo.latest_report(session, company.id)
    return _views(session, company, report, [row])[0]
