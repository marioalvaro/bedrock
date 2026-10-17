from bedrock.ingest.protocol import SourceNotConfigured, SourceUnavailable, UnknownTicker


class CompanyNotFound(Exception):
    """The ticker is not a followed company."""


class CompanyExists(Exception):
    """The company is already followed."""


class CellNotFound(Exception):
    """No such statement cell: an unknown item code or a period the company does not have."""


class AdjustmentNotFound(Exception):
    """No adjustment with this id on the company (an id of another company counts as unknown)."""


class InvalidAdjustment(Exception):
    """The adjustment breaks a rule; the message says which."""


class RuleNotFound(Exception):
    """No quality-of-earnings rule with this code in `qoe_rules.yaml`."""


class InvalidThreshold(Exception):
    """A threshold override breaks a rule (levels out of order, not finite); the message says
    which."""


class OffBalanceItemNotFound(Exception):
    """No off-balance-sheet item with this id on the company (another company's id counts as
    unknown)."""


class InvalidOffBalanceItem(Exception):
    """The off-balance-sheet item breaks a rule; the message says which."""


# What a use-case can raise on purpose; the API maps these to statuses, the CLI prints them.
DOMAIN_ERRORS = (
    CompanyNotFound,
    CompanyExists,
    CellNotFound,
    AdjustmentNotFound,
    InvalidAdjustment,
    RuleNotFound,
    InvalidThreshold,
    OffBalanceItemNotFound,
    InvalidOffBalanceItem,
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
        case AdjustmentNotFound():
            return f"No such adjustment: {error}"
        case RuleNotFound():
            return f"No such quality-of-earnings rule: {error}"
        case OffBalanceItemNotFound():
            return f"No such off-balance-sheet item: {error}"
        case CompanyExists():
            return f"{error} is already followed"
        case SourceNotConfigured():
            return f"Data source not configured: {error}"
        case SourceUnavailable():
            return f"Data source unavailable: {error}"
        case _:
            return str(error)
