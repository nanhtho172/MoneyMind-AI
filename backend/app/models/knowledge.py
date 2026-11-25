from datetime import date, datetime

from sqlalchemy import ForeignKey, JSON, LargeBinary, String
from sqlalchemy.orm import Mapped, mapped_column

from backend.app.models.finance import Base, utc_now


class KnowledgeAdmin(Base):
    __tablename__ = "knowledge_admins"

    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), primary_key=True)


class KnowledgeDocument(Base):
    __tablename__ = "knowledge_documents"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    current_version: Mapped[int]
    published_version: Mapped[int | None]
    published_collection: Mapped[str | None]
    published_batch: Mapped[str | None] = mapped_column(index=True)
    archived_at: Mapped[datetime | None]


class KnowledgeRevision(Base):
    __tablename__ = "knowledge_revisions"

    document_id: Mapped[str] = mapped_column(ForeignKey("knowledge_documents.id"), primary_key=True)
    document_version: Mapped[int] = mapped_column(primary_key=True)
    title: Mapped[str]
    original_filename: Mapped[str]
    file_type: Mapped[str]
    source_name: Mapped[str]
    source_url: Mapped[str | None]
    topic: Mapped[str]
    language: Mapped[str]
    jurisdiction: Mapped[str]
    publication_date: Mapped[date | None]
    uploaded_at: Mapped[datetime] = mapped_column(default=utc_now)
    uploaded_by: Mapped[int] = mapped_column(ForeignKey("users.id"))
    content_hash: Mapped[str] = mapped_column(String(64), index=True)
    blob: Mapped[bytes] = mapped_column(LargeBinary, deferred=True)
    pages: Mapped[list[dict] | None] = mapped_column(JSON, deferred=True)
    page_count: Mapped[int | None]
    extraction_status: Mapped[str]
    review_status: Mapped[str]
    indexing_status: Mapped[str]
    reviewed_by: Mapped[int | None] = mapped_column(ForeignKey("users.id"))
    reviewed_at: Mapped[datetime | None]
    review_note: Mapped[str | None]
    indexed_at: Mapped[datetime | None]
    chunk_count: Mapped[int] = mapped_column(default=0)
    error_code: Mapped[str | None]
    error_message: Mapped[str | None]


class KnowledgeIndex(Base):
    __tablename__ = "knowledge_indexes"

    namespace: Mapped[str] = mapped_column(primary_key=True)
    collection_name: Mapped[str]
    signature: Mapped[str]
    chunk_count: Mapped[int]


class KnowledgeFile(Base):
    __tablename__ = "knowledge_files"

    document_id: Mapped[str] = mapped_column(String(36), primary_key=True)
    original_filename: Mapped[str]
    stored_relative_path: Mapped[str | None]
    file_type: Mapped[str]
    file_size: Mapped[int]
    content_hash: Mapped[str] = mapped_column(String(64), index=True)
    uploaded_at: Mapped[datetime] = mapped_column(default=utc_now)
    indexing_status: Mapped[str]
    chunk_count: Mapped[int] = mapped_column(default=0)
    published_collection: Mapped[str | None]
    published_batch: Mapped[str | None] = mapped_column(index=True)
    error_code: Mapped[str | None]
    error_message: Mapped[str | None]
