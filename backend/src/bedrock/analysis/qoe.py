"""Quality-of-earnings flags (FR-ANL-05; docs/erd/analysis.md "Quality-of-earnings flags (M2)").

Pure apart from reading the rules file. Rule values read their operands through
`ratios/calculator.py::Operands` (the ratio calculator's operand rules), never a copy of them.
Custom rules and formula levels (FR-ANL-10) are `analysis/formula.py` formulas over the same
operands.
"""

from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, replace
from decimal import Decimal, InvalidOperation
from functools import cache
from pathlib import Path
from typing import Literal, get_args

import yaml

from bedrock.analysis import formula as formulas
from bedrock.analysis.formula import Formula
from bedrock.ratios.calculator import Operands, Point, RatioFreq, RatioInputs, year_earlier
from bedrock.ratios.registry import CANONICAL_CODES, METRICS, RATIOS
from bedrock.statements.build import RATIO_PLACES, growth
from bedrock.statements.periods import Period

DEFAULT_RULES_PATH = Path(__file__).parent / "qoe_rules.yaml"

Direction = Literal["above", "below"]
RuleUnit = Literal["pct", "x"]
Severity = Literal["none", "warn", "alert"]

# Levels are stored as Numeric(28, 10) (Gotcha G21): |level| must stay below this bound, with at
# most LEVEL_PLACES decimal places.
LEVEL_LIMIT = Decimal(10) ** 6
LEVEL_PLACES = 10


class RuleError(ValueError):
    """The rules file, or a threshold pair, breaks a rule; the message names the rule code."""


Level = Decimal | Formula | None


@dataclass(frozen=True)
class Thresholds:
    """One rule's levels; None means the rule has no such level. A Formula level is evaluated per
    company and period (FR-ANL-10)."""

    warn: Level
    alert: Level


@dataclass(frozen=True)
class Rule:
    """One entry of `qoe_rules.yaml`, or a custom rule. `rule` is the human-readable formula shown
    in the UI. `thresholds` are the effective ones (the YAML default, or an override after
    `effective_rules`); `default` is always the YAML pair (a custom rule's own levels).

    A built-in rule has `formula` None and a value function in this module. A custom rule
    (`custom`, code `custom_<id>`) has its value `formula`, or None when its stored text no longer
    parses. `error` (a `FormulaError` message) is set when a stored formula of the rule (its value
    or a level) no longer parses; such a rule has only None values."""

    code: str
    label: str
    rule: str
    direction: Direction
    unit: RuleUnit
    thresholds: Thresholds
    default: Thresholds
    formula: Formula | None = None
    custom: bool = False
    error: str | None = None


@dataclass(frozen=True)
class FlagRow:
    code: str
    label: str
    rule: str
    direction: Direction
    unit: RuleUnit
    thresholds: Thresholds  # the effective ones the severities were judged on
    values: list[Decimal | None]  # aligned with FlagTable.periods; quantized to RATIO_PLACES
    severity: list[Severity | None]  # None exactly where the value is None
    # Each level's value per period, aligned with `values`: a number level repeated, a formula
    # level evaluated and quantized to RATIO_PLACES, None where there is no level (or no value).
    warn_levels: list[Decimal | None]
    alert_levels: list[Decimal | None]
    custom: bool
    error: str | None


@dataclass(frozen=True)
class FlagTable:
    freq: RatioFreq
    periods: list[Period]
    rows: list[FlagRow]


@cache
def formula_names() -> frozenset[str]:
    """The names a formula may use: every canonical line code (`ratios/registry.py::
    CANONICAL_CODES`), metric code and ratio code, i.e. what `Operands.value` resolves. QoE rule
    codes are not names."""
    return CANONICAL_CODES | {m.code for m in METRICS} | {r.code for r in RATIOS}


def validate_thresholds(code: str, direction: Direction, thresholds: Thresholds) -> None:
    """Formula levels are not checked here (they are checked when parsed). Raises RuleError when
    both levels are numbers and out of order: for `above` alert must be
    >= warn, for `below` alert must be <= warn. A non-finite level, one with |level| >=
    LEVEL_LIMIT, or one with more than LEVEL_PLACES decimal places is also a RuleError."""
    warn, alert = thresholds.warn, thresholds.alert
    for level in (warn, alert):
        if not isinstance(level, Decimal):
            continue
        if not level.is_finite():
            raise RuleError(f"{code}: threshold {level} is not finite")
        if abs(level) >= LEVEL_LIMIT:
            raise RuleError(f"{code}: threshold {level} must be below {LEVEL_LIMIT} in size")
        exponent = level.normalize().as_tuple().exponent
        if isinstance(exponent, int) and exponent < -LEVEL_PLACES:
            raise RuleError(f"{code}: threshold {level} has more than {LEVEL_PLACES} decimals")
    if not isinstance(warn, Decimal) or not isinstance(alert, Decimal):
        return
    if direction == "above" and alert < warn:
        raise RuleError(f"{code}: an 'above' rule needs alert >= warn ({alert} < {warn})")
    if direction == "below" and alert > warn:
        raise RuleError(f"{code}: a 'below' rule needs alert <= warn ({alert} > {warn})")


def load_rules(path: Path = DEFAULT_RULES_PATH) -> tuple[Rule, ...]:
    """The rules of the YAML file, in file order, with `thresholds == default`.

    Raises RuleError for: a file that is not a list of mappings; a missing or unknown key; a
    duplicate code; a code with no value function in this module, or a value function with no
    entry; an unknown `direction` or `unit`; a non-numeric threshold; thresholds out of order
    (`validate_thresholds`)."""
    entries = yaml.safe_load(path.read_text())
    if not isinstance(entries, list):
        raise RuleError(f"{path.name}: the rules file must be a list of rules")
    rules: list[Rule] = []
    for entry in entries:
        rule = _parse_rule(entry)
        if any(r.code == rule.code for r in rules):
            raise RuleError(f"{rule.code}: duplicate rule code")
        rules.append(rule)
    missing = [code for code in _VALUES if code not in {r.code for r in rules}]
    if missing:
        raise RuleError(f"{', '.join(missing)}: value function with no rule entry")
    return tuple(rules)


_KEYS = frozenset({"code", "label", "rule", "direction", "unit", "warn", "alert"})


def _parse_rule(entry: object) -> Rule:
    if not isinstance(entry, dict):
        raise RuleError(f"each rule must be a mapping, got {entry!r}")
    code = entry.get("code")
    name = code if isinstance(code, str) else repr(code)
    keys = set(entry)
    if keys != _KEYS:
        missing, unknown = sorted(_KEYS - keys), sorted(map(str, keys - _KEYS))
        raise RuleError(f"{name}: missing keys {missing}, unknown keys {unknown}")
    for key in ("code", "label", "rule"):
        if not isinstance(entry[key], str) or not entry[key]:
            raise RuleError(f"{name}: '{key}' must be a non-empty string")
    if code not in _VALUES:
        raise RuleError(f"{name}: no value function for this rule")
    direction, unit = entry["direction"], entry["unit"]
    if direction not in get_args(Direction):
        raise RuleError(f"{name}: unknown direction {direction!r}")
    if unit not in get_args(RuleUnit):
        raise RuleError(f"{name}: unknown unit {unit!r}")
    levels = Thresholds(_level(name, entry["warn"]), _level(name, entry["alert"]))
    validate_thresholds(name, direction, levels)
    return Rule(
        code=name,
        label=entry["label"],
        rule=entry["rule"],
        direction=direction,
        unit=unit,
        thresholds=levels,
        default=levels,
    )


def _level(code: str, raw: object) -> Decimal | None:
    """A YAML threshold as an exact Decimal (via str, so 0.05 is Decimal("0.05"))."""
    if raw is None:
        return None
    if isinstance(raw, bool) or not isinstance(raw, int | float):
        raise RuleError(f"{code}: threshold {raw!r} is not a number")
    return Decimal(str(raw))


def effective_rules(rules: Sequence[Rule], overrides: Mapping[str, Thresholds]) -> tuple[Rule, ...]:
    """`rules` with `thresholds` replaced by the override of the same code, when there is one (the
    whole pair wins, a None level included). An override of an unknown code is ignored."""
    return tuple(
        replace(r, thresholds=overrides[r.code]) if r.code in overrides else r for r in rules
    )


def evaluate_flags(inputs: RatioInputs, rules: Sequence[Rule], freq: RatioFreq) -> FlagTable:
    """One row per rule, in order, over the periods of `inputs.income`.

    Postconditions: built-in values follow the ERD rule table (YoY is `statements/build.py::growth`;
    the previous period of `goodwill_impairment` is a year earlier: the prior FY end, or in TTM the
    same quarter a year earlier); a custom rule's value is `formula.evaluate(rule.formula, …)`; a
    rule with `error` has only None values. Values are quantized to RATIO_PLACES (a value too
    large to quantize is None) and severities judged on the quantized value against that
    period's level values (`warn_levels` / `alert_levels`; formula levels evaluated and quantized
    the same way): `above` flags value > level, `below` flags value < level, alert wins over
    warn, a None level (or level value) never flags, a None value has severity None. A period in
    which no rule has a value is left out. Raises ValueError when `freq` is `ttm` and
    `quarterly_income` is None; RuleError for a non-custom rule with no value function, or a
    custom rule with neither a formula nor an error."""
    if freq == "ttm" and inputs.quarterly_income is None:
        raise ValueError("TTM flags need the quarterly income statement")
    for r in rules:
        if r.custom:
            if r.formula is None and r.error is None:
                raise RuleError(f"{r.code}: custom rule has neither a formula nor an error")
        elif r.code not in _VALUES:
            raise RuleError(f"{r.code}: no value function for this rule")
    operands = Operands(inputs, freq)
    periods = inputs.income.periods
    points = [(p.fiscal_year, p.fiscal_period) for p in periods]
    grid = [[_rule_value(r, operands, pt) for pt in points] for r in rules]
    kept = [i for i in range(len(periods)) if any(row[i] is not None for row in grid)]
    rows = []
    for r, row in zip(rules, grid, strict=True):
        values = [row[i] for i in kept]
        warn_levels = [_level_value(r.thresholds.warn, operands, points[i], row[i]) for i in kept]
        alert_levels = [_level_value(r.thresholds.alert, operands, points[i], row[i]) for i in kept]
        rows.append(
            FlagRow(
                code=r.code,
                label=r.label,
                rule=r.rule,
                direction=r.direction,
                unit=r.unit,
                thresholds=r.thresholds,
                values=values,
                severity=[
                    _severity(v, r.direction, warn, alert)
                    for v, warn, alert in zip(values, warn_levels, alert_levels, strict=True)
                ],
                warn_levels=warn_levels,
                alert_levels=alert_levels,
                custom=r.custom,
                error=r.error,
            )
        )
    return FlagTable(freq=freq, periods=[periods[i] for i in kept], rows=rows)


def _rule_value(rule: Rule, ops: Operands, point: Point) -> Decimal | None:
    if rule.error is not None:
        return None
    if rule.custom:
        assert rule.formula is not None
        return _quantize(formulas.evaluate(rule.formula, ops, point))
    return _quantize(_VALUES[rule.code](ops, point))


def _level_value(
    level: Level, ops: Operands, point: Point, value: Decimal | None
) -> Decimal | None:
    """The level at `point`; None where the rule has no value there or no level."""
    if value is None or level is None:
        return None
    if isinstance(level, Decimal):
        return level
    return _quantize(formulas.evaluate(level, ops, point))


def _quantize(value: Decimal | None) -> Decimal | None:
    if value is None:
        return None
    try:
        return value.quantize(RATIO_PLACES)
    except InvalidOperation:
        return None


def _severity(
    value: Decimal | None,
    direction: Direction,
    warn: Decimal | None,
    alert: Decimal | None,
) -> Severity | None:
    if value is None:
        return None

    def breached(level: Decimal | None) -> bool:
        if level is None:
            return False
        return value > level if direction == "above" else value < level

    if breached(alert):
        return "alert"
    if breached(warn):
        return "warn"
    return "none"


# --- rule values ---------------------------------------------------------------------------------

ValueFn = Callable[[Operands, Point], Decimal | None]


def _divide(numerator: Decimal | None, denominator: Decimal | None) -> Decimal | None:
    """numerator / denominator; None when either is None or the denominator is <= 0."""
    if numerator is None or denominator is None or denominator <= 0:
        return None
    return numerator / denominator


def _yoy(ops: Operands, code: str, point: Point) -> Decimal | None:
    return growth(ops.value(code, point), ops.value(code, year_earlier(point)))


def _yoy_gap(code: str) -> ValueFn:
    """YoY(code) - YoY(revenue)."""

    def value(ops: Operands, point: Point) -> Decimal | None:
        line, revenue = _yoy(ops, code, point), _yoy(ops, "revenue", point)
        if line is None or revenue is None:
            return None
        return line - revenue

    return value


def _accruals_ratio(ops: Operands, point: Point) -> Decimal | None:
    accruals = ops.operand("net_income - cfo", point)
    return _divide(accruals, ops.operand("total_assets", point, average=True))


def _cfo_to_net_income(ops: Operands, point: Point) -> Decimal | None:
    return _divide(ops.value("cfo", point), ops.value("net_income", point))


def _goodwill_to_assets(ops: Operands, point: Point) -> Decimal | None:
    return _divide(ops.value("goodwill", point), ops.value("total_assets", point))


def _goodwill_impairment(ops: Operands, point: Point) -> Decimal | None:
    prior_goodwill = ops.value("goodwill", year_earlier(point))
    if prior_goodwill is None or prior_goodwill <= 0:
        return None
    impairment = ops.value("goodwill_impairment", point)
    if impairment is not None:
        return _divide(impairment, prior_goodwill)
    goodwill = ops.value("goodwill", point)
    if goodwill is None or goodwill <= 0:
        return None
    return Decimal(0)


def _sbc_to_revenue(ops: Operands, point: Point) -> Decimal | None:
    return _divide(ops.value("sbc", point), ops.value("revenue", point))


def _sbc_to_cfo(ops: Operands, point: Point) -> Decimal | None:
    return _divide(ops.value("sbc", point), ops.value("cfo", point))


_VALUES: dict[str, ValueFn] = {
    "accruals_ratio": _accruals_ratio,
    "cfo_to_net_income": _cfo_to_net_income,
    "receivables_vs_revenue": _yoy_gap("receivables"),
    "inventory_vs_revenue": _yoy_gap("inventory"),
    "goodwill_to_assets": _goodwill_to_assets,
    "goodwill_impairment": _goodwill_impairment,
    "sbc_to_revenue": _sbc_to_revenue,
    "sbc_to_cfo": _sbc_to_cfo,
}
