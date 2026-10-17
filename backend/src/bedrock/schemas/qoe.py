from decimal import Decimal

from pydantic import BaseModel

from bedrock.analysis.qoe import Direction, RuleUnit, Thresholds
from bedrock.services.qoe import RuleSetting


class QoeRuleOut(BaseModel):
    """A quality-of-earnings rule with its effective levels (`warn`, `alert`) and the shipped
    defaults. Levels are fractions for `pct` rules; a null level means the rule has none."""

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

    @classmethod
    def from_setting(cls, setting: RuleSetting) -> "QoeRuleOut":
        rule = setting.rule
        return cls(
            code=rule.code,
            label=rule.label,
            rule=rule.rule,
            direction=rule.direction,
            unit=rule.unit,
            warn=rule.thresholds.warn,
            alert=rule.thresholds.alert,
            default_warn=rule.default.warn,
            default_alert=rule.default.alert,
            overridden=setting.overridden,
        )


class QoeThresholdsIn(BaseModel):
    """Both levels are required keys; null removes that level."""

    warn: Decimal | None
    alert: Decimal | None

    def to_thresholds(self) -> Thresholds:
        return Thresholds(warn=self.warn, alert=self.alert)
