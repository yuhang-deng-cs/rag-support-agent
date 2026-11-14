"""Knowledge-base documents. Every query is scoped to the caller's tenant."""

from __future__ import annotations

import contextlib
import logging

from fastapi import APIRouter, BackgroundTasks, HTTPException, UploadFile, status
from sqlalchemy import select

from app.api.deps import AdminUser, CurrentUser, Services, ServicesDep
from app.api.schemas import DocumentOut
from app.db.models import Document
from app.ingestion.service import ingest_document
from app.rag.parsing import UnsupportedFileError, content_type_for, extract_text

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/documents", tags=["documents"])


def _not_found() -> HTTPException:
    # Same response for "doesn't exist" and "belongs to another tenant": no existence oracle.
    return HTTPException(status.HTTP_404_NOT_FOUND, "Document not found")


async def _ingest_inline(services: Services, tenant_id: str, document_id: int) -> None:
    # Failures are logged and recorded on the document row; don't crash the worker loop.
    with contextlib.suppress(Exception):
        await ingest_document(
            services.db, services.embedder, services.settings, tenant_id, document_id
        )


def dispatch_ingestion(
    services: Services, background: BackgroundTasks, tenant_id: str, document_id: int
) -> None:
    if services.settings.ingestion_backend == "celery":
        from app.ingestion.celery_app import ingest_document_task

        ingest_document_task.delay(tenant_id, document_id)
    else:
        background.add_task(_ingest_inline, services, tenant_id, document_id)


@router.post("", status_code=status.HTTP_202_ACCEPTED)
async def upload_document(
    file: UploadFile, admin: AdminUser, services: ServicesDep, background: BackgroundTasks
) -> DocumentOut:
    """Upload a .txt, .md or .pdf file. Processing happens in the background; poll its status."""
    filename = (file.filename or "").strip()
    limit = services.settings.max_upload_mb * 1024 * 1024
    data = await file.read(limit + 1)
    if len(data) > limit:
        raise HTTPException(status.HTTP_413_CONTENT_TOO_LARGE, "File too large")
    try:
        content_type = content_type_for(filename)
        text = extract_text(filename, data)
    except UnsupportedFileError as exc:
        raise HTTPException(status.HTTP_415_UNSUPPORTED_MEDIA_TYPE, str(exc)) from exc

    async with services.db.tenant_session(admin.tenant_id) as session:
        doc = Document(
            tenant_id=admin.tenant_id,
            filename=filename[:255],
            content_type=content_type,
            source_text=text,
            uploaded_by=admin.user_id,
        )
        session.add(doc)
        await session.flush()
        out = DocumentOut.model_validate(doc)

    dispatch_ingestion(services, background, admin.tenant_id, doc.id)
    return out


@router.get("")
async def list_documents(user: CurrentUser, services: ServicesDep) -> list[DocumentOut]:
    async with services.db.tenant_session(user.tenant_id) as session:
        docs = await session.scalars(
            select(Document)
            .where(Document.tenant_id == user.tenant_id)
            .order_by(Document.created_at.desc(), Document.id.desc())
        )
        return [DocumentOut.model_validate(d) for d in docs]


@router.get("/{document_id}")
async def get_document(document_id: int, user: CurrentUser, services: ServicesDep) -> DocumentOut:
    async with services.db.tenant_session(user.tenant_id) as session:
        doc = await session.scalar(
            select(Document).where(Document.id == document_id, Document.tenant_id == user.tenant_id)
        )
        if doc is None:
            raise _not_found()
        return DocumentOut.model_validate(doc)


@router.delete("/{document_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_document(document_id: int, admin: AdminUser, services: ServicesDep) -> None:
    async with services.db.tenant_session(admin.tenant_id) as session:
        doc = await session.scalar(
            select(Document).where(
                Document.id == document_id, Document.tenant_id == admin.tenant_id
            )
        )
        if doc is None:
            raise _not_found()
        await session.delete(doc)
