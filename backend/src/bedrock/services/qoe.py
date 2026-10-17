"""Quality-of-earnings rules, their global threshold overrides (FR-ANL-05) and the custom rules
and formula levels (FR-ANL-10; docs/erd/analysis.md "Custom rules and formula levels (M2)")."""

from dataclasses import dataclass, replace
from datetime import UTC, datetime
from decimal import Decimal, InvalidOperation
from functools import cache
from typing import Any, cast

from sqlalchemy.orm import Session

from bedrock.analysis import formula as formulas
from bedrock.analysis.formula import Formula, FormulaError
from bedrock.analysis.qoe import (
    Direction,
    Level,
    Rule,
    RuleError,
    RuleUnit,
    Thresholds,
    formula_names,
    load_rules,
    validate_thresholds,
)
from bedrock.models.qoe_custom_rule import QoeCustomRule
from bedrock.models.qoe_threshold import QoeThreshold
from bedrock.repositories import qoe_custom_rules as custom_repo
from bedrock.repositories import qoe_thresholds as repo
from bedrock.services.errors import (
    CustomRuleNotFound,
    InvalidCustomRule,
    InvalidFormula,
    InvalidThreshold,
    RuleNotFound,
)


@dataclass(frozen=True)
class RuleSetting:
    """A rule with its effective thresholds (`rule.thresholds`), the YAML default
    (`rule.default`), and whether a `qoe_threshold` row overrides it (always False for a custom
    rule). `warn_formula` / `alert_formula` are the stored text of a formula level, as typed (also
    when it no longer parses; the level is then None in `rule.thresholds` and `rule.error` is
    set), None for a number level or no level."""

    rule: Rule
    overridden: bool
    warn_formula: str | None
    alert_formula: str | None


@dataclass(frozen=True)
class CustomRuleInput:
    """A custom rule as the user sends it. Levels are strings: a number (a fraction for `pct`)
    or a formula; None means no such level."""

    label: str
    formula: str
    direction: Direction
    unit: RuleUnit
    warn: str | None
    alert: str | None


@dataclass(frozen=True)
class CustomRuleView:
    """A stored custom rule (levels as plain decimals, `repositories/numeric.py::plain`) with
    `error`, the `FormulaError` message of its first stored formula (value, then warn, then
    alert) that no longer parses, else None. Its code is `custom_<row.id>`."""

    row: QoeCustomRule
    error: str | None


@cache
def default_rules() -> tuple[Rule, ...]:
    """The shipped rules (`analysis/qoe.py::load_rules` on the default path), loaded once."""
    return load_rules()


def custom_code(rule_id: int) -> str:
    """The rule code of a custom rule: `custom_<id>`."""
    return f"custom_{rule_id}"


def parse_level(code: str, text: str | None) -> Decimal | Formula | None:
    """One level as the user sends it. None or blank -> None. Text that is a Decimal literal is a
    number; other text is parsed (`analysis/formula.py::parse` with `formula_names()`) and a
    constant formula becomes its `constant_value`. Numbers must pass the `LEVEL_LIMIT` /
    `LEVEL_PLACES` checks of `validate_thresholds` (a constant with no value, e.g. "1/0", is
    invalid). Raises InvalidFormula (the FormulaError text with its position) when it does not
    parse, InvalidThreshold for a number that is out of range or missing."""
    if text is None or not text.strip():
        return None
    stripped = text.strip()
    try:
        number = Decimal(stripped)
    except InvalidOperation:
        try:
            parsed = formulas.parse(stripped, formula_names())
        except FormulaError as error:
            raise InvalidFormula(str(error)) from error
        if not formulas.is_constant(parsed):
            return parsed
        constant = formulas.constant_value(parsed)
        if constant is None:
            raise InvalidThreshold(f"{code}: level '{stripped}' has no value") from None
        number = constant
    _check_number(code, number)
    return number


def _check_number(code: str, number: Decimal) -> None:
    try:
        validate_thresholds(code, "above", Thresholds(number, None))
    except RuleError as error:
        raise InvalidThreshold(str(error)) from error


def _check_order(code: str, direction: Direction, warn: Level, alert: Level) -> None:
    try:
        validate_thresholds(code, direction, Thresholds(warn, alert))
    except RuleError as error:
        raise InvalidThreshold(str(error)) from error


def _store(level: Level) -> tuple[Decimal | None, str | None]:
    """(number column, formula column) of a parsed level."""
    if isinstance(level, Formula):
        return None, level.text
    return level, None


def _load_level(text: str | None, number: Decimal | None) -> tuple[Level, str | None]:
    """A stored level and the FormulaError message when its formula no longer parses."""
    if text is None:
        return number, None
    try:
        return formulas.parse(text, formula_names()), None
    except FormulaError as error:
        return None, str(error)


def _first(*errors: str | None) -> str | None:
    return next((e for e in errors if e is not None), None)


def _overridden(rule: Rule, row: QoeThreshold) -> Rule:
    warn, warn_error = _load_level(row.warn_formula, row.warn)
    alert, alert_error = _load_level(row.alert_formula, row.alert)
    return replace(rule, thresholds=Thresholds(warn, alert), error=_first(warn_error, alert_error))


def _custom_rule(row: QoeCustomRule) -> Rule:
    value: Formula | None = None
    try:
        value = formulas.parse(row.formula, formula_names())
        value_error = None
    except FormulaError as error:
        value_error = str(error)
    warn, warn_error = _load_level(row.warn_formula, row.warn)
    alert, alert_error = _load_level(row.alert_formula, row.alert)
    levels = Thresholds(warn, alert)
    return Rule(
        code=custom_code(row.id),
        label=row.label,
        rule=row.formula,
        direction=cast(Direction, row.direction),
        unit=cast(RuleUnit, row.unit),
        thresholds=levels,
        default=levels,
        formula=value,
        custom=True,
        error=_first(value_error, warn_error, alert_error),
    )


def effective(session: Session) -> tuple[Rule, ...]:
    """The rules flags are judged with: the shipped rules with their stored overrides (number
    and formula levels), then the custom rules in id order (`custom=True`, `rule` = the stored
    formula text, `default` = their own levels). A stored formula that no longer parses never
    raises: the rule gets `error` and None for that formula (value or level)."""
    return tuple(s.rule for s in list_rules(session))


def list_rules(session: Session) -> list[RuleSetting]:
    """Every shipped rule in YAML order, then every custom rule in id order, as `effective`."""
    overrides = {t.rule_code: t for t in repo.list_all(session)}
    settings = []
    for rule in default_rules():
        row = overrides.get(rule.code)
        if row is None:
            settings.append(RuleSetting(rule, False, None, None))
        else:
            settings.append(
                RuleSetting(_overridden(rule, row), True, row.warn_formula, row.alert_formula)
            )
    for custom in custom_repo.list_all(session):
        settings.append(
            RuleSetting(_custom_rule(custom), False, custom.warn_formula, custom.alert_formula)
        )
    return settings


def set_thresholds(
    session: Session, code: str, warn: str | None, alert: str | None, now: datetime
) -> RuleSetting:
    """Creates or replaces the override of the shipped rule `code` (both levels, each through
    `parse_level`; None means no such level) and commits. A number level is stored in `warn` /
    `alert`, a formula level as the text as typed (stripped) in `warn_formula` /
    `alert_formula`. `updated_at` is `now` as naive UTC. Raises RuleNotFound for a code not in
    the YAML (custom codes included), InvalidFormula / InvalidThreshold from `parse_level`, and
    InvalidThreshold when both levels are numbers out of order (`validate_thresholds`); nothing is
    stored then."""
    rule = _rule(code)
    warn_level, alert_level = parse_level(code, warn), parse_level(code, alert)
    _check_order(code, rule.direction, warn_level, alert_level)
    (warn_number, warn_text), (alert_number, alert_text) = _store(warn_level), _store(alert_level)
    stamp = _naive_utc(now)
    stored = repo.get(session, code)
    if stored is None:
        repo.add(
            session,
            QoeThreshold(
                rule_code=code,
                warn=warn_number,
                alert=alert_number,
                warn_formula=warn_text,
                alert_formula=alert_text,
                updated_at=stamp,
            ),
        )
    else:
        stored.warn, stored.warn_formula = warn_number, warn_text
        stored.alert, stored.alert_formula = alert_number, alert_text
        stored.updated_at = stamp
    session.commit()
    return next(s for s in list_rules(session) if s.rule.code == code)


def reset(session: Session, code: str) -> None:
    """Deletes the override of `code`, if any, and commits: the rule is back to its default.
    Raises RuleNotFound for a code not in the YAML (custom codes included)."""
    _rule(code)
    stored = repo.get(session, code)
    if stored is not None:
        repo.delete(session, stored)
    session.commit()


def list_custom_rules(session: Session) -> list[CustomRuleView]:
    """Every custom rule, in id order. Unpaginated by design: a handful of user rules."""
    return [_view(row) for row in custom_repo.list_all(session)]


def create_custom_rule(session: Session, data: CustomRuleInput, now: datetime) -> CustomRuleView:
    """Validates, stores and commits a custom rule: the label stripped (blank -> InvalidCustomRule),
    the formula parsed with `formula_names()` (InvalidFormula) and stored as typed (stripped),
    the levels through `parse_level` and, when both are numbers, `validate_thresholds`
    (InvalidThreshold). `created_at` / `updated_at` are `now` as naive UTC."""
    stamp = _naive_utc(now)
    row = custom_repo.add(
        session, QoeCustomRule(created_at=stamp, updated_at=stamp, **_fields(data))
    )
    rule_id = row.id
    session.commit()
    return _committed(session, rule_id)


def update_custom_rule(
    session: Session, rule_id: int, data: CustomRuleInput, now: datetime
) -> CustomRuleView:
    """Replaces every field of the custom rule `rule_id`, validated as `create_custom_rule`, and
    commits; `updated_at` is `now`. Raises CustomRuleNotFound for an unknown id (before
    validating)."""
    row = custom_repo.get(session, rule_id)
    if row is None:
        raise CustomRuleNotFound(rule_id)
    for field, value in _fields(data).items():
        setattr(row, field, value)
    row.updated_at = _naive_utc(now)
    session.commit()
    return _committed(session, rule_id)


def delete_custom_rule(session: Session, rule_id: int) -> None:
    """Deletes the custom rule and commits. Raises CustomRuleNotFound for an unknown id."""
    row = custom_repo.get(session, rule_id)
    if row is None:
        raise CustomRuleNotFound(rule_id)
    custom_repo.delete(session, row)
    session.commit()


def _fields(data: CustomRuleInput) -> dict[str, Any]:
    """The validated column values of a custom rule (nothing is stored when this raises)."""
    label = data.label.strip()
    if not label:
        raise InvalidCustomRule("A custom rule needs a label")
    formula = data.formula.strip()
    try:
        formulas.parse(formula, formula_names())
    except FormulaError as error:
        raise InvalidFormula(str(error)) from error
    warn, alert = parse_level("custom rule", data.warn), parse_level("custom rule", data.alert)
    _check_order("custom rule", data.direction, warn, alert)
    (warn_number, warn_text), (alert_number, alert_text) = _store(warn), _store(alert)
    return {
        "label": label,
        "formula": formula,
        "direction": data.direction,
        "unit": data.unit,
        "warn": warn_number,
        "alert": alert_number,
        "warn_formula": warn_text,
        "alert_formula": alert_text,
    }


def _view(row: QoeCustomRule) -> CustomRuleView:
    return CustomRuleView(row, _custom_rule(row).error)


def _committed(session: Session, rule_id: int) -> CustomRuleView:
    """The rule re-read with plain-decimal levels after a commit expired it."""
    row = custom_repo.get(session, rule_id)
    assert row is not None
    return _view(row)


def _rule(code: str) -> Rule:
    rule = next((r for r in default_rules() if r.code == code), None)
    if rule is None:
        raise RuleNotFound(code)
    return rule


def _naive_utc(moment: datetime) -> datetime:
    # SQLite keeps no time zone: the columns hold UTC without one.
    return moment.astimezone(UTC).replace(tzinfo=None)
