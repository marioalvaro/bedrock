"""Domain errors -> HTTP statuses. Routers stay thin: they let these propagate."""

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from bedrock.ingest.protocol import SourceNotConfigured, SourceUnavailable, UnknownTicker
from bedrock.services.errors import (
    AdjustmentNotFound,
    CellNotFound,
    CompanyExists,
    CompanyNotFound,
    CustomRuleNotFound,
    InvalidAdjustment,
    InvalidCustomRule,
    InvalidFormula,
    InvalidOffBalanceItem,
    InvalidThreshold,
    OffBalanceItemNotFound,
    RuleNotFound,
    user_message,
)

_STATUS: dict[type[Exception], int] = {
    CompanyNotFound: 404,
    UnknownTicker: 404,
    CellNotFound: 404,
    AdjustmentNotFound: 404,
    InvalidAdjustment: 422,
    RuleNotFound: 404,
    OffBalanceItemNotFound: 404,
    InvalidThreshold: 422,
    InvalidOffBalanceItem: 422,
    CustomRuleNotFound: 404,
    InvalidFormula: 422,
    InvalidCustomRule: 422,
    CompanyExists: 409,
    SourceNotConfigured: 503,
    SourceUnavailable: 502,
}


def register_error_handlers(app: FastAPI) -> None:
    async def handle(_: Request, error: Exception) -> JSONResponse:
        return JSONResponse(
            status_code=_STATUS[type(error)], content={"detail": user_message(error)}
        )

    for error_type in _STATUS:
        app.add_exception_handler(error_type, handle)
