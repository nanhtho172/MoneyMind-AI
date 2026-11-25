from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Request, Response
from python_multipart.exceptions import MultipartParseError
from starlette.concurrency import run_in_threadpool
from starlette.datastructures import UploadFile
from starlette.formparsers import MultiPartException, MultiPartParser

from backend.app.api.dependencies import CurrentUser
from backend.app.schemas.knowledge import BuiltinDocument, DocumentItem
from backend.app.services.document_extraction import DocumentError
from backend.app.services.knowledge import KnowledgeService

router = APIRouter(prefix="/knowledge", tags=["Knowledge"])
_MULTIPART = {
    "requestBody": {"required": True, "content": {"multipart/form-data": {"schema": {
        "type": "object", "required": ["file"], "properties": {"file": {"type": "string", "format": "binary"}},
    }}}},
}


def get_knowledge(request: Request) -> KnowledgeService:
    return request.app.state.knowledge


Knowledge = Annotated[KnowledgeService, Depends(get_knowledge)]


async def _read_upload(request: Request, limit: int) -> tuple[str, str, bytes]:
    if request.headers.get("content-type", "").partition(";")[0].strip().lower() != "multipart/form-data":
        raise DocumentError("INVALID_UPLOAD", "Yêu cầu cần có multipart/form-data.", 415)
    max_request = limit + 32 * 1024
    declared = request.headers.get("content-length")
    if declared and declared.isdecimal() and int(declared) > max_request:
        raise DocumentError("UPLOAD_TOO_LARGE", "Tệp vượt quá giới hạn dung lượng tải lên.", 413)
    size = 0

    async def limited_stream():
        nonlocal size
        async for chunk in request.stream():
            size += len(chunk)
            if size > max_request:
                raise MultiPartException("Upload limit exceeded")
            yield chunk

    parser = MultiPartParser(request.headers, limited_stream(), max_files=1, max_fields=0, max_part_size=16 * 1024)
    try:
        data = await parser.parse()
    except (MultiPartException, MultipartParseError):
        if size > max_request:
            raise DocumentError("UPLOAD_TOO_LARGE", "Tệp vượt quá giới hạn dung lượng tải lên.", 413) from None
        raise DocumentError("INVALID_UPLOAD", "Không đọc được dữ liệu tải lên.") from None
    try:
        upload = data.get("file")
        if not isinstance(upload, UploadFile):
            raise DocumentError("FILE_REQUIRED", "Cần chọn một tệp tài liệu.")
        content = await upload.read(limit + 1)
        return upload.filename or "", upload.content_type or "", content
    finally:
        await data.close()


@router.get("/documents")
def list_documents(user: CurrentUser, service: Knowledge) -> list[DocumentItem]:
    return service.list_documents()


@router.get("/builtin")
def builtin_documents(user: CurrentUser, service: Knowledge) -> list[BuiltinDocument]:
    return service.builtin_documents()


@router.post("/documents", status_code=201, openapi_extra=_MULTIPART)
async def upload_document(request: Request, user: CurrentUser, service: Knowledge) -> DocumentItem:
    args = await _read_upload(request, service.settings.rag_upload_max_bytes)
    return await run_in_threadpool(service.upload, *args)


@router.post("/documents/{document_id}/retry")
def retry(document_id: UUID, user: CurrentUser, service: Knowledge) -> DocumentItem:
    return service.retry(document_id)


@router.delete("/documents/{document_id}", status_code=204)
def remove(document_id: UUID, user: CurrentUser, service: Knowledge) -> Response:
    service.remove(document_id)
    return Response(status_code=204)
