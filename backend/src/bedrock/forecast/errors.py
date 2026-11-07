"""Forecast errors (docs/erd/forecasting.md)."""


class ForecastUnavailable(Exception):
    """The forecast cannot run for a reason the user can fix (missing drivers, no opening balance
    sheet, missing segment or KPI data, a resolved value out of bounds). The API maps it to a
    422 with `detail`."""

    def __init__(self, detail: str) -> None:
        super().__init__(detail)
        self.detail = detail


class ForecastIntegrityError(Exception):
    """A forecast failed one of its integrity checks (balance, cash or retained-earnings
    roll-forward, quarters summing to the year). Always a bug, never user input."""


class EngineFailed(Exception):
    """A statistical engine could not forecast a series (a fit that raised, a non-finite input or
    output, too few values). Callers fall back to the M4 mean; never surfaced as a 500."""

    def __init__(self, message: str) -> None:
        super().__init__(message)
        self.message = message
