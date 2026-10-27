from datetime import datetime
from typing import Literal

from fastapi import APIRouter, Depends, File, Form, Response, UploadFile
from sqlalchemy.orm import Session

from bedrock.api.deps import get_clock, get_session
from bedrock.api.v1.statements import followed_company
from bedrock.ingest.manual_import import ImportIssue
from bedrock.models.company import Company
from bedrock.schemas.imports import ImportFileErrorsOut, ImportPreviewOut, StatementImportOut
from bedrock.services import imports as service
from bedrock.services.errors import InvalidStatementImport

router = APIRouter(tags=["imports"])

Scale = Literal["units", "thousands", "millions", "billions"]
MAX_BYTES = 10 * 1024 * 1024
_MEDIA = {
    "xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    "csv": "text/csv; charset=utf-8",
}


@router.get("/companies/{ticker}/import-template")
def download_template(
    format: Literal["xlsx", "csv"] = "xlsx",
    prefill: bool = False,
    scale: Scale = "millions",
    company: Company = Depends(followed_company),
    session: Session = Depends(get_session),
    now: datetime = Depends(get_clock),
) -> Response:
    content = service.import_template(session, company, format, scale, prefill, now.date())
    name = f"{company.ticker}-import-template.{format}"
    return Response(
        content,
        media_type=_MEDIA[format],
        headers={"Content-Disposition": f'attachment; filename="{name}"'},
    )


@router.post("/companies/{ticker}/imports", responses={422: {"model": ImportFileErrorsOut}})
async def import_statements(
    file: UploadFile = File(),
    dry_run: bool = Form(False),
    scale: Scale | None = Form(None),
    company: Company = Depends(followed_company),
    session: Session = Depends(get_session),
    now: datetime = Depends(get_clock),
) -> ImportPreviewOut:
    content = await file.read(MAX_BYTES + 1)
    if len(content) > MAX_BYTES:
        raise InvalidStatementImport(
            [ImportIssue(None, None, None, "The file is larger than 10 MB")]
        )
    filename = file.filename or "import"
    if dry_run:
        preview = service.preview_import(session, company, content, filename, scale)
        return ImportPreviewOut.from_preview(preview, True, None)
    result = service.confirm_import(session, company, content, filename, scale, now)
    return ImportPreviewOut.from_result(result)


@router.get("/companies/{ticker}/imports")
def list_imports(
    company: Company = Depends(followed_company), session: Session = Depends(get_session)
) -> list[StatementImportOut]:
    return [StatementImportOut.from_model(i) for i in service.list_imports(session, company)]


@router.delete("/companies/{ticker}/imports/{import_id}", status_code=204)
def delete_import(
    import_id: int,
    company: Company = Depends(followed_company),
    session: Session = Depends(get_session),
) -> None:
    service.delete_import(session, company, import_id)
