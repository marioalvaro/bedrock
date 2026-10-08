from bedrock.ingest.protocol import SourceNotConfigured, SourceUnavailable, UnknownTicker


class CompanyNotFound(Exception):
    """The ticker is not a followed company."""


class CompanyExists(Exception):
    """The company is already followed."""


class CellNotFound(Exception):
    """No such statement cell: an unknown item code or a period the company does not have."""


# What a use-case can raise on purpose; the API maps these to statuses, the CLI prints them.
DOMAIN_ERRORS = (
    CompanyNotFound,
    CompanyExists,
    CellNotFound,
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
        case CompanyExists():
            return f"{error} is already followed"
        case SourceNotConfigured():
            return f"Data source not configured: {error}"
        case SourceUnavailable():
            return f"Data source unavailable: {error}"
        case _:
            return str(error)
