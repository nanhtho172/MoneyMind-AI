from sqlalchemy import select, update
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session

from backend.app.core.observability import observe
from backend.app.models.knowledge import KnowledgeDocument, KnowledgeFile, KnowledgeRevision
from backend.app.services.document_extraction import DocumentError
from backend.app.services.knowledge_storage import UploadStorage


def migrate_legacy_uploads(engine: Engine, storage: UploadStorage) -> None:
    """Copy and verify the displayed revision of each legacy document, retaining its original BLOB."""
    with Session(engine) as session, session.begin():
        session.execute(update(KnowledgeFile).where(KnowledgeFile.indexing_status == "processing").values(
            indexing_status="failed", error_code="PROCESSING_INTERRUPTED",
            error_message="Lần xử lý trước bị gián đoạn. Bạn có thể thử lại.",
        ))
        documents = session.scalars(select(KnowledgeDocument).where(KnowledgeDocument.archived_at.is_(None))).all()
        for document in documents:
            item = session.get(KnowledgeFile, document.id)
            if item is not None and (item.stored_relative_path or item.indexing_status == "deleting"):
                continue
            version = document.published_version or document.current_version
            revision = session.get(KnowledgeRevision, (document.id, version))
            if revision is None:
                continue

            is_published = bool(
                document.published_version and document.published_collection and document.published_batch
                and revision.indexing_status == "indexed" and revision.review_status == "approved"
            )
            if item is None:
                item = KnowledgeFile(
                    document_id=document.id, original_filename=revision.original_filename,
                    file_type=revision.file_type, content_hash=revision.content_hash, file_size=len(revision.blob),
                    uploaded_at=revision.uploaded_at, indexing_status="ready" if is_published else "failed",
                    chunk_count=revision.chunk_count if is_published else 0,
                    published_collection=document.published_collection if is_published else None,
                    published_batch=document.published_batch if is_published else None,
                )
                session.add(item)
            relative = storage.relative_name(document.id, revision.original_filename, revision.file_type)
            try:
                with observe("rag.migrate_file", document_id=document.id):
                    if sha256(revision.blob).hexdigest() != item.content_hash or len(revision.blob) != item.file_size:
                        raise DocumentError("FILE_INTEGRITY_ERROR", "Bản gốc legacy không khớp hash.")
                    try:
                        storage.read_verified(document.id, relative, item.file_size, item.content_hash)
                    except FileNotFoundError:
                        storage.save(document.id, relative, revision.blob)
                        storage.read_verified(document.id, relative, item.file_size, item.content_hash)
            except (DocumentError, OSError):
                item.error_code = "LEGACY_MIGRATION_PENDING"
                item.error_message = "Chưa chuyển được bản gốc legacy. SQLite vẫn giữ bản gốc."
            else:
                item.stored_relative_path = relative
                item.error_code = None if is_published else "LEGACY_NOT_INDEXED"
                item.error_message = None if is_published else "Tài liệu cũ chưa được xuất bản. Bấm Thử lại để xử lý."
from hashlib import sha256

