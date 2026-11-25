import re
from hashlib import sha256
from uuid import UUID, uuid4

from sqlalchemy import delete, select
from sqlalchemy.engine import Engine
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from backend.app.agent.llm import AgentProblem
from backend.app.agent.rag import ChromaKnowledge, Chunk, KNOWLEDGE_DIRECTORY
from backend.app.core.config import Settings
from backend.app.core.observability import observe
from backend.app.models.knowledge import KnowledgeDocument, KnowledgeFile, KnowledgeRevision
from backend.app.schemas.chat import Source
from backend.app.schemas.knowledge import BuiltinDocument, DocumentItem, DocumentPage
from backend.app.services.document_extraction import DocumentError, extract, validate_upload
from backend.app.services.knowledge_migration import migrate_legacy_uploads
from backend.app.services.knowledge_storage import UploadStorage


def _segments(text: str, size: int):
    for sentence in re.split(r"(?<=[.!?…])\s+|\n+", text):
        line = sentence.strip()
        while len(line) > size:
            cut = line.rfind(" ", 0, size + 1)
            cut = cut if cut > 0 else size
            yield line[:cut]
            line = line[cut:].strip()
        if line:
            yield line


def _windows(text: str, size: int, overlap: int):
    units, length = [], 0
    for unit in _segments(text, size):
        if units and length + 1 + len(unit) > size:
            yield " ".join(units)
            while units and (length > overlap or length + 1 + len(unit) > size):
                length -= len(units.pop(0)) + bool(len(units))
        length += len(unit) + bool(units)
        units.append(unit)
    if units:
        yield " ".join(units)


def make_chunks(document_id: str, filename: str, pages: list[DocumentPage], size: int, overlap: int) -> list[Chunk]:
    chunks: list[Chunk] = []
    heading = ""
    for page in pages:
        sections = re.split(r"(?m)^(#{1,6}\s+.+)$", page.text)
        for part in sections:
            part = part.strip()
            if not part:
                continue
            if re.match(r"^#{1,6}\s+", part) and "\n" not in part:
                heading = part.lstrip("# ").strip()[:min(size // 4, 100)]
                continue
            prefix = f"{heading}\n" if heading else ""
            for text in _windows(part, size - len(prefix), overlap):
                text = prefix + text
                digest = sha256(text.encode()).hexdigest()[:12]
                chunk_id = f"{document_id}:file:{len(chunks) + 1}:{digest}"
                source = Source(
                    document_id=document_id, title=filename, source=filename,
                    document_title=filename, source_name=filename, original_filename=filename,
                    page_number=page.page_number, chunk_id=chunk_id,
                )
                chunks.append(Chunk(chunk_id, text, source))
    return chunks


def _get_file(session: Session, document_id: str) -> KnowledgeFile:
    item = session.get(KnowledgeFile, document_id)
    if item is None:
        raise DocumentError("DOCUMENT_NOT_FOUND", "Không tìm thấy tài liệu.", 404)
    return item


class KnowledgeService:
    def __init__(self, engine: Engine, settings: Settings, vector: ChromaKnowledge):
        self.engine, self.settings, self.vector = engine, settings, vector
        self.storage = UploadStorage(settings.rag_upload_directory)
        migrate_legacy_uploads(engine, self.storage)

    def builtin_documents(self) -> list[BuiltinDocument]:
        builtin_ids = [path.stem for path in sorted(KNOWLEDGE_DIRECTORY.glob("*.md"))]
        if not builtin_ids or not (self.settings.rag_directory / "chroma.sqlite3").is_file():
            return []
        try:
            with self.vector.lock, Session(self.engine) as session:
                name = self.vector.active_collection(session)
                ids = self.vector.indexed_document_ids(name, builtin_ids)
        except AgentProblem:
            return []
        return [
            BuiltinDocument(document_id=doc_id, original_filename=f"{doc_id}.md")
            for doc_id in builtin_ids if doc_id in ids
        ]

    def list_documents(self) -> list[DocumentItem]:
        with Session(self.engine) as session:
            documents = session.scalars(select(KnowledgeFile).order_by(
                KnowledgeFile.uploaded_at.desc(), KnowledgeFile.document_id,
            )).all()
            return [DocumentItem.model_validate(item) for item in documents]

    def upload(self, filename: str, mime: str, content: bytes) -> DocumentItem:
        name, kind = validate_upload(filename, mime, content, self.settings.rag_upload_max_bytes)
        digest = sha256(content).hexdigest()
        with self.vector.lock:
            with Session(self.engine) as session, session.begin():
                existing = session.scalar(select(KnowledgeFile).where(
                    KnowledgeFile.content_hash == digest,
                ).limit(1))
                if existing is None:
                    item = KnowledgeFile(
                        document_id=str(uuid4()), original_filename=name, file_type=kind,
                        file_size=len(content), content_hash=digest,
                    )
                    session.add(item)
                else:
                    if existing.indexing_status == "ready":
                        return DocumentItem.model_validate(existing)
                    self._check_retry(existing)
                    item = existing
                item.stored_relative_path = item.stored_relative_path or self.storage.relative_name(
                    item.document_id, item.original_filename, item.file_type,
                )
                item.indexing_status = "processing"
                item.error_code = item.error_message = None
                document_id = item.document_id
            return self._process(document_id, content, retry=existing is not None)

    def retry(self, document_id: UUID) -> DocumentItem:
        key = str(document_id)
        with self.vector.lock:
            with Session(self.engine) as session, session.begin():
                item = _get_file(session, key)
                if item.indexing_status == "ready":
                    return DocumentItem.model_validate(item)
                self._check_retry(item)
                if not item.stored_relative_path:
                    raise DocumentError("UPLOAD_REQUIRED", "Hãy tải lại tệp gốc để thử lại.", 409)
                item.indexing_status = "processing"
                item.error_code = item.error_message = None
            return self._process(key, retry=True)

    @staticmethod
    def _check_retry(item: KnowledgeFile) -> None:
        if item.indexing_status == "deleting":
            raise DocumentError("DELETE_PENDING", "Hãy hoàn tất xóa tệp trước khi tải lại.", 409)

    def _process(self, document_id: str, content: bytes | None = None, *, retry: bool) -> DocumentItem:
        with Session(self.engine) as session:
            item = _get_file(session, document_id)
            relative, size, digest = item.stored_relative_path, item.file_size, item.content_hash
            filename, file_type = item.original_filename, item.file_type
            collection = self.vector.active_collection(session)
        batch = uuid4().hex
        attempted_write = False
        try:
            if content is not None:
                self.storage.save(document_id, relative, content)
            saved = self.storage.read_verified(document_id, relative, size, digest)
            with observe("rag.extract", document_id=document_id):
                parsed = extract(saved, file_type)
                chunks = make_chunks(
                    document_id, filename, parsed.pages, self.settings.rag_chunk_size, self.settings.rag_chunk_overlap,
                )
            with observe("rag.index", document_id=document_id, model_name=self.settings.embedding_model):
                if retry:
                    self.vector.delete_document(document_id)
                attempted_write = True
                count = self.vector.write_chunks(collection, chunks, publication_id=batch)
            with Session(self.engine) as session, session.begin():
                item = _get_file(session, document_id)
                item.indexing_status, item.chunk_count = "ready", count
                item.published_collection, item.published_batch = collection, batch
                return DocumentItem.model_validate(item)
        except (DocumentError, AgentProblem) as error:
            code, message = error.code, str(error)
        except FileNotFoundError:
            code, message = "UPLOAD_REQUIRED", "Không tìm thấy tệp đã lưu. Hãy tải lại tệp gốc."
        except OSError:
            code, message = "FILE_STORAGE_ERROR", "Không thể lưu hoặc đọc tệp. Hãy kiểm tra thư mục upload."
        except SQLAlchemyError:
            code, message = "RAG_METADATA_ERROR", "Không lưu được trạng thái chỉ mục. Hãy thử lại."

        if attempted_write:
            try:
                with observe("rag.index.cleanup", document_id=document_id):
                    self.vector.delete_chunks(collection, {"publication_id": batch})
            except AgentProblem:
                # Unpublished vectors stay invisible. Retry removes them by document ID.
                pass
        with Session(self.engine) as session, session.begin():
            item = _get_file(session, document_id)
            item.indexing_status, item.chunk_count = "failed", 0
            item.published_collection = item.published_batch = None
            item.error_code, item.error_message = code, message
            return DocumentItem.model_validate(item)

    def remove(self, document_id: UUID) -> None:
        key = str(document_id)
        with self.vector.lock:
            with Session(self.engine) as session, session.begin():
                item = session.get(KnowledgeFile, key)
                if item is None:
                    return
                relative = item.stored_relative_path or self.storage.relative_name(
                    key, item.original_filename, item.file_type,
                )
                # Persist the tombstone first. A failed or interrupted cleanup cannot republish this file.
                item.indexing_status = "deleting"
                item.published_collection = item.published_batch = None
                item.error_code = "DELETE_PENDING"
                item.error_message = "Chưa hoàn tất xóa. Bấm Xóa để thử lại."
            try:
                with observe("rag.delete", document_id=key):
                    self.vector.delete_document(key)
                    self.storage.remove(key, relative)
                    with Session(self.engine) as session, session.begin():
                        session.execute(delete(KnowledgeRevision).where(KnowledgeRevision.document_id == key))
                        session.execute(delete(KnowledgeDocument).where(KnowledgeDocument.id == key))
                        session.delete(_get_file(session, key))
            except (DocumentError, AgentProblem, OSError, SQLAlchemyError):
                raise DocumentError(
                    "DELETE_PENDING", "Đã ẩn tài liệu khỏi Chat. Chưa xóa xong tệp hoặc vector. Bấm Xóa để thử lại.", 503,
                ) from None
