from datetime import datetime
from decimal import Decimal
from typing import Literal

from pydantic import BaseModel

from bedrock.models.statement_import import StatementImport
from bedrock.services.imports import ImportPreview, ImportResult


class ImportFileIssueOut(BaseModel):
    """A warning or an error of the file; `sheet`, `row` and `column` (a letter) say where."""

    sheet: str | None
    row: int | None
    column: str | None
    message: str


class ImportFileErrorsOut(BaseModel):
    """The 422 body of a file with errors."""

    detail: str
    errors: list[ImportFileIssueOut]


class CellChangeOut(BaseModel):
    statement: Literal["IS", "BS", "CF"]
    code: str
    label: str
    unit: str
    period_key: str
    value: Decimal  # displayed (sign applied), in units
    previous: Decimal | None  # what an earlier import gave the cell, when this one changes it


class IgnoredCellOut(BaseModel):
    statement: Literal["IS", "BS", "CF"]
    code: str
    label: str
    unit: str
    period_key: str
    existing_value: Decimal  # what the cell shows
    imported_value: Decimal  # what the file says
    reason: Literal["sec", "derived"]


class ImportPreviewOut(BaseModel):
    """What an import fills and leaves alone. `import_id` is null for a dry run and for a file
    that fills no cell."""

    dry_run: bool
    format: Literal["xlsx", "csv"]
    scale: Literal["units", "thousands", "millions", "billions"]
    import_id: int | None
    fills: list[CellChangeOut]
    ignored: list[IgnoredCellOut]
    unchanged: int
    warnings: list[ImportFileIssueOut]

    @classmethod
    def from_preview(
        cls, preview: ImportPreview, dry_run: bool, import_id: int | None
    ) -> "ImportPreviewOut":
        return cls(
            dry_run=dry_run,
            format=preview.format,
            scale=preview.scale,
            import_id=import_id,
            fills=[CellChangeOut(**vars(c)) for c in preview.fills],
            ignored=[IgnoredCellOut(**vars(i)) for i in preview.ignored],
            unchanged=preview.unchanged,
            warnings=[ImportFileIssueOut(**vars(w)) for w in preview.warnings],
        )

    @classmethod
    def from_result(cls, result: ImportResult) -> "ImportPreviewOut":
        return cls.from_preview(result.preview, False, result.import_id)


class StatementImportOut(BaseModel):
    id: int
    filename: str
    format: Literal["xlsx", "csv"]
    scale: Literal["units", "thousands", "millions", "billions"]
    imported_at: datetime  # UTC
    cells: int

    @classmethod
    def from_model(cls, row: StatementImport) -> "StatementImportOut":
        return cls(
            id=row.id,
            filename=row.filename,
            format=row.format,
            scale=row.scale,
            imported_at=row.imported_at,
            cells=row.cells,
        )
