from datetime import UTC, datetime
from decimal import Decimal
from typing import cast

from pydantic import BaseModel, field_validator

from bedrock.analysis.qoe import Direction, RuleUnit
from bedrock.services.qoe import CustomRuleInput, CustomRuleView, RuleSetting, custom_code

# A level as sent: a number (a JSON string or number) or a formula string; null means no level.
LevelIn = str | Decimal | None


def _level_text(level: LevelIn) -> str | None:
    return None if level is None else str(level)


def _number(level: object) -> Decimal | None:
    """A level that is a number, else None (a formula level, or no level)."""
    return level if isinstance(level, Decimal) else None


class QoeRuleOut(BaseModel):
    """A quality-of-earnings rule with its effective levels and the shipped defaults. Levels are
    fractions for `pct` rules; a null level means the rule has none. A formula level is in
    `warn_formula` / `alert_formula` (as typed), with `warn` / `alert` null. A custom rule has
    `custom`, its `formula` (also in `rule`) and null defaults; `error` is set when a stored
    formula no longer parses."""

    code: str
    label: str
    rule: str
    direction: Direction
    unit: RuleUnit
    warn: Decimal | None
    alert: Decimal | None
    default_warn: Decimal | None
    default_alert: Decimal | None
    overridden: bool
    custom: bool
    formula: str | None
    warn_formula: str | None
    alert_formula: str | None
    error: str | None

    @classmethod
    def from_setting(cls, setting: RuleSetting) -> "QoeRuleOut":
        rule = setting.rule
        return cls(
            code=rule.code,
            label=rule.label,
            rule=rule.rule,
            direction=rule.direction,
            unit=rule.unit,
            warn=_number(rule.thresholds.warn),
            alert=_number(rule.thresholds.alert),
            default_warn=None if rule.custom else _number(rule.default.warn),
            default_alert=None if rule.custom else _number(rule.default.alert),
            overridden=setting.overridden,
            custom=rule.custom,
            formula=rule.rule if rule.custom else None,
            warn_formula=setting.warn_formula,
            alert_formula=setting.alert_formula,
            error=rule.error,
        )


class QoeThresholdsIn(BaseModel):
    """Both levels are required keys; null removes that level. A level is a number (a fraction
    for `pct` rules) or a formula string."""

    warn: LevelIn
    alert: LevelIn

    def level_texts(self) -> tuple[str | None, str | None]:
        return _level_text(self.warn), _level_text(self.alert)


class QoeCustomRuleIn(BaseModel):
    label: str
    formula: str
    direction: Direction
    unit: RuleUnit
    warn: LevelIn = None
    alert: LevelIn = None

    def to_input(self) -> CustomRuleInput:
        return CustomRuleInput(
            label=self.label,
            formula=self.formula,
            direction=self.direction,
            unit=self.unit,
            warn=_level_text(self.warn),
            alert=_level_text(self.alert),
        )


class QoeCustomRuleOut(BaseModel):
    """A stored custom rule. A number level is in `warn` / `alert`, a formula level in
    `warn_formula` / `alert_formula` (as typed); `error` is set when a stored formula no longer
    parses."""

    id: int
    code: str
    label: str
    formula: str
    direction: Direction
    unit: RuleUnit
    warn: Decimal | None
    alert: Decimal | None
    warn_formula: str | None
    alert_formula: str | None
    error: str | None
    created_at: datetime
    updated_at: datetime

    @field_validator("created_at", "updated_at")
    @classmethod
    def _is_utc(cls, value: datetime) -> datetime:
        # SQLite keeps no time zone: without a zone in the JSON a browser reads local time.
        return value if value.tzinfo else value.replace(tzinfo=UTC)

    @classmethod
    def from_view(cls, view: CustomRuleView) -> "QoeCustomRuleOut":
        row = view.row
        return cls(
            id=row.id,
            code=custom_code(row.id),
            label=row.label,
            formula=row.formula,
            direction=cast(Direction, row.direction),  # the table's CHECK keeps it valid
            unit=cast(RuleUnit, row.unit),
            warn=row.warn,
            alert=row.alert,
            warn_formula=row.warn_formula,
            alert_formula=row.alert_formula,
            error=view.error,
            created_at=row.created_at,
            updated_at=row.updated_at,
        )
