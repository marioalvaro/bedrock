"""Quality-of-earnings rules and their global threshold overrides (FR-ANL-05)."""

from dataclasses import dataclass
from datetime import UTC, datetime
from functools import cache

from sqlalchemy.orm import Session

from bedrock.analysis.qoe import (
    Rule,
    RuleError,
    Thresholds,
    effective_rules,
    load_rules,
    validate_thresholds,
)
from bedrock.models.qoe_threshold import QoeThreshold
from bedrock.repositories import qoe_thresholds as repo
from bedrock.services.errors import InvalidThreshold, RuleNotFound


@dataclass(frozen=True)
class RuleSetting:
    """A rule with its effective thresholds (`rule.thresholds`), the YAML default
    (`rule.default`), and whether a `qoe_threshold` row overrides it."""

    rule: Rule
    overridden: bool


@cache
def default_rules() -> tuple[Rule, ...]:
    """The shipped rules (`analysis/qoe.py::load_rules` on the default path), loaded once."""
    return load_rules()


def effective(session: Session) -> tuple[Rule, ...]:
    """The shipped rules with the stored overrides applied (`effective_rules`)."""
    return effective_rules(default_rules(), _overrides(session))


def list_rules(session: Session) -> list[RuleSetting]:
    """Every shipped rule in YAML order, with its effective thresholds and override flag."""
    overrides = _overrides(session)
    return [
        RuleSetting(rule, rule.code in overrides)
        for rule in effective_rules(default_rules(), overrides)
    ]


def set_thresholds(
    session: Session, code: str, thresholds: Thresholds, now: datetime
) -> RuleSetting:
    """Creates or replaces the override of `code` (both levels; a None level means no such level)
    and commits. `updated_at` is `now` as naive UTC. Raises RuleNotFound for a code not in the
    YAML, InvalidThreshold when `validate_thresholds` rejects the pair (nothing is stored)."""
    rule = _rule(code)
    try:
        validate_thresholds(code, rule.direction, thresholds)
    except RuleError as error:
        raise InvalidThreshold(str(error)) from error
    stamp = _naive_utc(now)
    stored = repo.get(session, code)
    if stored is None:
        repo.add(
            session,
            QoeThreshold(
                rule_code=code, warn=thresholds.warn, alert=thresholds.alert, updated_at=stamp
            ),
        )
    else:
        stored.warn, stored.alert, stored.updated_at = thresholds.warn, thresholds.alert, stamp
    session.commit()
    return _setting(session, code)


def reset(session: Session, code: str) -> None:
    """Deletes the override of `code`, if any, and commits: the rule is back to its default.
    Raises RuleNotFound for a code not in the YAML."""
    _rule(code)
    stored = repo.get(session, code)
    if stored is not None:
        repo.delete(session, stored)
    session.commit()


def _overrides(session: Session) -> dict[str, Thresholds]:
    return {t.rule_code: Thresholds(warn=t.warn, alert=t.alert) for t in repo.list_all(session)}


def _rule(code: str) -> Rule:
    rule = next((r for r in default_rules() if r.code == code), None)
    if rule is None:
        raise RuleNotFound(code)
    return rule


def _setting(session: Session, code: str) -> RuleSetting:
    """The rule's setting after a commit (which expires the rows), with plain-decimal levels."""
    return next(s for s in list_rules(session) if s.rule.code == code)


def _naive_utc(moment: datetime) -> datetime:
    # SQLite keeps no time zone: the columns hold UTC without one.
    return moment.astimezone(UTC).replace(tzinfo=None)
