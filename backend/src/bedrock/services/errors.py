from bedrock.forecast.driver_io import DriverFileIssue
from bedrock.forecast.errors import ForecastUnavailable
from bedrock.ingest.manual_import import ImportIssue as FileIssue
from bedrock.ingest.protocol import SourceNotConfigured, SourceUnavailable, UnknownTicker
from bedrock.statements.segments import ImportIssue


class CompanyNotFound(Exception):
    """The ticker is not a followed company."""


class CompanyExists(Exception):
    """The company is already followed."""


class CellNotFound(Exception):
    """No such statement cell: an unknown item code or a period the company does not have."""


class RatioCellNotFound(Exception):
    """No such ratio cell: an unknown ratio code or a period that is not a column of the table."""


class AdjustmentNotFound(Exception):
    """No adjustment with this id on the company (an id of another company counts as unknown)."""


class InvalidAdjustment(Exception):
    """The adjustment breaks a rule; the message says which."""


class RuleNotFound(Exception):
    """No quality-of-earnings rule with this code in `qoe_rules.yaml`."""


class InvalidThreshold(Exception):
    """A threshold override breaks a rule (levels out of order, not finite); the message says
    which."""


class CustomRuleNotFound(Exception):
    """No custom quality-of-earnings rule with this id."""


class InvalidFormula(Exception):
    """A formula (a custom rule's value or a level) does not parse; the message is the
    `FormulaError` text with its position, e.g. "Unknown name 'revenu' at 0"."""


class InvalidCustomRule(Exception):
    """A custom rule breaks a rule other than its formula (e.g. a blank label); the message says
    which."""


class OffBalanceItemNotFound(Exception):
    """No off-balance-sheet item with this id on the company (another company's id counts as
    unknown)."""


class InvalidOffBalanceItem(Exception):
    """The off-balance-sheet item breaks a rule; the message says which."""


class SeriesNotFound(Exception):
    """No segment or KPI series with this id on the company (another company's id counts as
    unknown)."""


class InvalidSeries(Exception):
    """The series or one of its values breaks a rule; the message says which."""


class CompsSetNotFound(Exception):
    """No comps set with this id on the company (another company's id counts as unknown)."""


class InvalidCompsSet(Exception):
    """The comps set breaks a rule (name, members); the message says which."""


class GuidanceNotFound(Exception):
    """No guidance entry with this id on the company (another company's id counts as unknown)."""


class InvalidGuidance(Exception):
    """The guidance entry breaks a rule (metric, period, range); the message says which."""


class NoteNotFound(Exception):
    """No note with this id on the company (another company's id counts as unknown)."""


class InvalidNote(Exception):
    """The note breaks a rule (body, link, filter); the message says which."""


class InvalidImport(Exception):
    """A segment import has errors; nothing was written. `issues` lists every one."""

    def __init__(self, issues: list[ImportIssue]) -> None:
        super().__init__(f"The import has {len(issues)} error(s)")
        self.issues = issues


class InvalidStatementImport(Exception):
    """A statement import file has errors; nothing was written. `issues` lists every one, each
    with its sheet, row and column where it has them."""

    def __init__(self, issues: list[FileIssue]) -> None:
        super().__init__(f"The file has {len(issues)} error(s)")
        self.issues = issues


class InvalidDriverFile(Exception):
    """A driver file has errors; nothing was written. `issues` lists every one, each with its row
    and column where it has them."""

    def __init__(self, issues: list[DriverFileIssue]) -> None:
        super().__init__(f"The file has {len(issues)} error(s)")
        self.issues = issues


class ImportNotFound(Exception):
    """No statement import with this id on the company (another company's id counts as
    unknown)."""


class ScenarioNotFound(Exception):
    """No scenario with this id on the company (another company's id counts as unknown)."""


class ScenarioConflict(Exception):
    """The scenario write clashes with another one: a duplicate name, or deleting Base."""


class InvalidScenario(Exception):
    """The scenario's name or settings break a rule; the message says which."""


class InvalidDrivers(Exception):
    """A driver PUT breaks a rule (unknown code, a year that is not a forecast year, a bound, an
    offset on Base); the message says which. Nothing was written."""


class InvalidEngineChoice(Exception):
    """An engine PUT or inspection breaks a rule (unknown engine, a driver outside the scenario's
    method, `stl` on a driver that is not seasonal, a driver twice); the message says which.
    Nothing was written."""


class InvalidSeasonality(Exception):
    """A seasonality request cannot be answered (no quarterly history, an unknown line, a line with
    fewer than 12 consecutive quarters); the message says which."""


class InvalidValuationInput(Exception):
    """A valuation-inputs PUT breaks a rule (unknown or repeated code, a value its kind cannot
    parse, a bound, a choice not offered, a comps set that is not the company's); the message
    says which. Nothing was written."""


class InvalidSensitivity(Exception):
    """A sensitivity request names an unknown or inapplicable input, or the same input twice."""


class UnknownLineItem(Exception):
    """A requested line item code is not a canonical IS, BS or CF line."""


# What a use-case can raise on purpose; the API maps these to statuses, the CLI prints them.
DOMAIN_ERRORS = (
    CompanyNotFound,
    CompanyExists,
    CellNotFound,
    RatioCellNotFound,
    AdjustmentNotFound,
    InvalidAdjustment,
    RuleNotFound,
    InvalidThreshold,
    CustomRuleNotFound,
    InvalidFormula,
    InvalidCustomRule,
    OffBalanceItemNotFound,
    InvalidOffBalanceItem,
    SeriesNotFound,
    InvalidSeries,
    CompsSetNotFound,
    InvalidCompsSet,
    GuidanceNotFound,
    InvalidGuidance,
    InvalidNote,
    InvalidImport,
    InvalidStatementImport,
    ImportNotFound,
    NoteNotFound,
    ScenarioNotFound,
    ScenarioConflict,
    InvalidScenario,
    InvalidDrivers,
    InvalidEngineChoice,
    InvalidSeasonality,
    InvalidValuationInput,
    InvalidSensitivity,
    UnknownLineItem,
    ForecastUnavailable,
    UnknownTicker,
    SourceNotConfigured,
    SourceUnavailable,
)


def user_message(error: Exception) -> str:
    """The reason to show a person for one of `DOMAIN_ERRORS`."""
    match error:
        case CompanyNotFound():
            return f"{error} is not a followed company"
        case UnknownTicker():
            return f"Unknown ticker {error}: no SEC filer has it"
        case CellNotFound():
            return f"No such statement cell: {error}"
        case RatioCellNotFound():
            return f"No such ratio cell: {error}"
        case AdjustmentNotFound():
            return f"No such adjustment: {error}"
        case RuleNotFound():
            return f"No such quality-of-earnings rule: {error}"
        case CustomRuleNotFound():
            return f"No such custom quality-of-earnings rule: {error}"
        case OffBalanceItemNotFound():
            return f"No such off-balance-sheet item: {error}"
        case SeriesNotFound():
            return f"No such segment or KPI series: {error}"
        case CompsSetNotFound():
            return f"No such comps set: {error}"
        case GuidanceNotFound():
            return f"No such guidance entry: {error}"
        case NoteNotFound():
            return f"No such note: {error}"
        case ImportNotFound():
            return f"No such import: {error}"
        case ScenarioNotFound():
            return f"No such scenario: {error}"
        case ForecastUnavailable():
            return error.detail
        case CompanyExists():
            return f"{error} is already followed"
        case SourceNotConfigured():
            return f"Data source not configured: {error}"
        case SourceUnavailable():
            return f"Data source unavailable: {error}"
        case _:
            return str(error)
