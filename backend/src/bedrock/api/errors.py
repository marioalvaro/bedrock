"""Domain errors -> HTTP statuses. Routers stay thin: they let these propagate."""

import math
from typing import Any

from fastapi import FastAPI, Request
from fastapi.encoders import jsonable_encoder
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse

from bedrock.classify.protocol import ClassifierError, ClassifierUnavailable
from bedrock.forecast.errors import ForecastUnavailable
from bedrock.ingest.protocol import SourceNotConfigured, SourceUnavailable, UnknownTicker
from bedrock.services.errors import (
    AdjustmentNotFound,
    AuditRowNotFound,
    BackfillRunning,
    BudgetExceeded,
    CellNotFound,
    CheckpointNotFound,
    ClassificationNotFound,
    ClassificationRunning,
    CompanyArchived,
    CompanyExists,
    CompanyNotArchived,
    CompanyNotFound,
    CompsSetNotFound,
    CustomRuleNotFound,
    FilingNotFound,
    GuidanceLocked,
    GuidanceNotFound,
    ImportNotFound,
    InvalidAdjustment,
    InvalidAuditRow,
    InvalidBacktest,
    InvalidCheckpoint,
    InvalidClassification,
    InvalidCompsSet,
    InvalidCustomRule,
    InvalidDriverFile,
    InvalidDrivers,
    InvalidEngineChoice,
    InvalidFormula,
    InvalidGuidance,
    InvalidImport,
    InvalidNote,
    InvalidOffBalanceItem,
    InvalidScenario,
    InvalidSeasonality,
    InvalidSensitivity,
    InvalidSeries,
    InvalidSnapshot,
    InvalidStatementImport,
    InvalidThreshold,
    InvalidValuationInput,
    NoteNotFound,
    NothingToClassify,
    OffBalanceItemNotFound,
    RatioCellNotFound,
    RuleNotFound,
    ScenarioConflict,
    ScenarioNotFound,
    SeriesNotFound,
    SnapshotNotFound,
    StaleEstimate,
    UnknownLineItem,
    user_message,
)

_STATUS: dict[type[Exception], int] = {
    CompanyNotFound: 404,
    UnknownTicker: 404,
    CellNotFound: 404,
    FilingNotFound: 404,
    RatioCellNotFound: 404,
    AdjustmentNotFound: 404,
    InvalidAdjustment: 422,
    RuleNotFound: 404,
    OffBalanceItemNotFound: 404,
    InvalidThreshold: 422,
    InvalidOffBalanceItem: 422,
    CustomRuleNotFound: 404,
    InvalidFormula: 422,
    InvalidCustomRule: 422,
    CheckpointNotFound: 404,
    InvalidCheckpoint: 422,
    SeriesNotFound: 404,
    InvalidSeries: 422,
    CompsSetNotFound: 404,
    InvalidCompsSet: 422,
    GuidanceNotFound: 404,
    InvalidGuidance: 422,
    GuidanceLocked: 409,
    NoteNotFound: 404,
    ImportNotFound: 404,
    InvalidNote: 422,
    CompanyExists: 409,
    CompanyArchived: 409,
    CompanyNotArchived: 409,
    BackfillRunning: 409,
    ScenarioNotFound: 404,
    ScenarioConflict: 409,
    InvalidScenario: 422,
    InvalidDrivers: 422,
    InvalidEngineChoice: 422,
    InvalidSeasonality: 422,
    InvalidValuationInput: 422,
    InvalidSensitivity: 422,
    SnapshotNotFound: 404,
    InvalidSnapshot: 422,
    InvalidBacktest: 422,
    AuditRowNotFound: 404,
    InvalidAuditRow: 422,
    UnknownLineItem: 422,
    ForecastUnavailable: 422,
    SourceNotConfigured: 503,
    SourceUnavailable: 502,
    ClassificationNotFound: 404,
    InvalidClassification: 422,
    ClassifierError: 502,
}

# The reasons a classification run does not start (docs/erd/face-tree.md "Routes"): 409, with a
# `code` beside the message so the panel can tell them apart.
_CONFLICT_CODES: dict[type[Exception], str] = {
    ClassifierUnavailable: "classifier_unavailable",
    NothingToClassify: "nothing_to_classify",
    StaleEstimate: "stale_estimate",
    BudgetExceeded: "budget_exceeded",
    ClassificationRunning: "classification_running",
}


def register_error_handlers(app: FastAPI) -> None:
    async def handle(_: Request, error: Exception) -> JSONResponse:
        return JSONResponse(
            status_code=_STATUS[type(error)], content={"detail": user_message(error)}
        )

    async def handle_conflict(_: Request, error: Exception) -> JSONResponse:
        return JSONResponse(
            status_code=409,
            content={"detail": user_message(error), "code": _CONFLICT_CODES[type(error)]},
        )

    async def handle_import(_: Request, error: Exception) -> JSONResponse:
        assert isinstance(error, InvalidImport)
        return JSONResponse(
            status_code=422,
            content={
                "detail": user_message(error),
                "errors": [
                    {"row": i.row, "column": i.column, "message": i.message} for i in error.issues
                ],
            },
        )

    async def handle_driver_file(_: Request, error: Exception) -> JSONResponse:
        assert isinstance(error, InvalidDriverFile)
        return JSONResponse(
            status_code=422,
            content={
                "detail": user_message(error),
                "errors": [
                    {"row": i.row, "column": i.column, "message": i.message} for i in error.issues
                ],
            },
        )

    async def handle_statement_import(_: Request, error: Exception) -> JSONResponse:
        assert isinstance(error, InvalidStatementImport)
        return JSONResponse(
            status_code=422,
            content={
                "detail": user_message(error),
                "errors": [
                    {"sheet": i.sheet, "row": i.row, "column": i.column, "message": i.message}
                    for i in error.issues
                ],
            },
        )

    async def handle_validation(_: Request, error: Exception) -> JSONResponse:
        # FastAPI's own handler echoes the input back, and a JSON number such as 1e400 parses to
        # an infinite float that the response encoder refuses (a 500 instead of the 422).
        assert isinstance(error, RequestValidationError)
        return JSONResponse(
            status_code=422, content={"detail": _json_safe(jsonable_encoder(error.errors()))}
        )

    for error_type in _STATUS:
        app.add_exception_handler(error_type, handle)
    for error_type in _CONFLICT_CODES:
        app.add_exception_handler(error_type, handle_conflict)
    app.add_exception_handler(InvalidImport, handle_import)
    app.add_exception_handler(InvalidStatementImport, handle_statement_import)
    app.add_exception_handler(InvalidDriverFile, handle_driver_file)
    app.add_exception_handler(RequestValidationError, handle_validation)


def _json_safe(value: Any) -> Any:
    """`value` with every non-finite float replaced by its text ("inf", "nan")."""
    if isinstance(value, float) and not math.isfinite(value):
        return str(value)
    if isinstance(value, list):
        return [_json_safe(v) for v in value]
    if isinstance(value, dict):
        return {k: _json_safe(v) for k, v in value.items()}
    return value
