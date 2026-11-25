from typing import Literal
from uuid import UUID

from pydantic import ConfigDict

from backend.app.schemas.common import InputModel, StoredUTC

FileType = Literal["pdf", "docx", "txt", "md"]


class DocumentPage(InputModel):
    page_number: int | None
    text: str


class DocumentItem(InputModel):
    model_config = ConfigDict(from_attributes=True, extra="forbid")

    document_id: UUID
    original_filename: str
    stored_relative_path: str | None
    file_type: str
    file_size: int
    uploaded_at: StoredUTC
    indexing_status: Literal["processing", "ready", "failed", "deleting"]
    chunk_count: int
    error_code: str | None
    error_message: str | None


class BuiltinDocument(InputModel):
    document_id: str
    original_filename: str
