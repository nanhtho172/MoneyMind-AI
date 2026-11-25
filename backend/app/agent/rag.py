import re
import sys
from dataclasses import dataclass
from hashlib import sha256
from pathlib import Path
from threading import RLock
from typing import Protocol

from sqlalchemy import select
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session

from backend.app.agent.guardrails import folded
from backend.app.agent.llm import AgentProblem
from backend.app.core.config import PROJECT_ROOT, Settings
from backend.app.core.observability import observe
from backend.app.models.knowledge import KnowledgeFile, KnowledgeIndex
from backend.app.schemas.chat import Source

KNOWLEDGE_DIRECTORY = PROJECT_ROOT / "docs" / "knowledge"


@dataclass(frozen=True)
class Chunk:
    chunk_id: str
    text: str
    source: Source


class Retriever(Protocol):
    def retrieve(self, question: str) -> list[Chunk]: ...


def load_documents(directory: Path = KNOWLEDGE_DIRECTORY) -> list[Chunk]:
    chunks = []
    for path in sorted(directory.glob("*.md")):
        header, _, body = path.read_text(encoding="utf-8").strip().partition("\n")
        if not header.startswith("# ") or not body.strip():
            raise ValueError(f"Thiếu tiêu đề hoặc nội dung trong {path.name}")
        source = Source(
            document_id=path.stem, title=header.removeprefix("# ").strip(),
            source=f"MoneyMind AI · docs/knowledge/{path.name}",
        )
        paragraphs = re.split(r"\n\s*\n", body.strip())
        for paragraph in paragraphs:
            text = " ".join(paragraph.split())
            while len(text) > 650:
                end = text.rfind(" ", 0, 650)
                end = end if end > 0 else 650
                pieces = text[:end], text[end:].strip()
                chunks.append(_chunk(source, pieces[0]))
                text = pieces[1]
            chunks.append(_chunk(source, text))
    return list({chunk.chunk_id: chunk for chunk in chunks}.values())


def _chunk(source: Source, text: str) -> Chunk:
    fingerprint = sha256(text.encode()).hexdigest()[:20]
    return Chunk(f"{source.document_id}:{fingerprint}", text, source)


def restore_query_accents(question: str, candidates: list[Chunk]) -> str:
    """Restore only unambiguous multiword matches found in the semantic candidates."""
    tokens = list(re.finditer(r"\w+", question))
    phrases: dict[tuple[str, ...], set[tuple[str, ...]]] = {}
    for chunk in candidates:
        words = re.findall(r"\w+", f"{chunk.source.title} {chunk.text}".casefold())
        for size in (2, 3):
            for start in range(len(words) - size + 1):
                original = tuple(words[start:start + size])
                if all(word.isascii() for word in original):
                    continue
                phrases.setdefault(tuple(folded(word) for word in original), set()).add(original)

    replacements = []
    start = 0
    while start < len(tokens):
        for size in (3, 2):
            group = tokens[start:start + size]
            if len(group) < size or any(question[a.end():b.start()].strip() for a, b in zip(group, group[1:])):
                continue
            options = phrases.get(tuple(word.group().casefold() for word in group), set())
            if len(options) == 1:
                for token, restored in zip(group, next(iter(options)), strict=True):
                    if not restored.isascii():
                        replacements.append((token.start(), token.end(), restored))
                start += size
                break
        else:
            start += 1
    for low, high, value in reversed(replacements):
        question = question[:low] + value + question[high:]
    return question


class ChromaKnowledge:
    def __init__(self, settings: Settings, engine: Engine | None = None):
        self.settings = settings
        self.engine = engine
        self.lock = RLock()
        self._model = None
        self._chroma = None
        fingerprint = sha256(settings.embedding_model.encode()).hexdigest()[:16]
        self.collection_name = f"moneymind_knowledge_{fingerprint}"

    def _embed(self, texts: list[str], *, download: bool = False) -> list[list[float]]:
        with self.lock:
            if self._model is None:

                if sys.platform == "win32":
                    try:
                        import pyarrow
                    except ImportError:
                        pass
                try:
                    from sentence_transformers import SentenceTransformer
                except ImportError:
                    raise AgentProblem("RAG_DEPENDENCIES_MISSING", "Chưa cài thư viện embedding.") from None
                try:
                    self._model = SentenceTransformer(
                        self.settings.embedding_model, device="cpu", local_files_only=not download,
                    )
                except (OSError, ValueError, RuntimeError):
                    raise AgentProblem(
                        "RAG_MODEL_UNAVAILABLE", "Model embedding chưa có sẵn hoặc không tải được.",
                    ) from None
            try:
                return self._model.encode(
                    texts, normalize_embeddings=True, show_progress_bar=False,
                ).tolist()
            except (ValueError, OSError, RuntimeError):
                raise AgentProblem("RAG_EMBEDDING_FAILED", "Không tạo được embedding cho văn bản.") from None

    def _client(self):
        try:
            import chromadb
            from chromadb.config import Settings as ChromaSettings
        except ImportError:
            raise AgentProblem("RAG_DEPENDENCIES_MISSING", "Chưa cài ChromaDB.") from None
        if self._chroma is None:
            self._chroma = chromadb.PersistentClient(
                path=str(self.settings.rag_directory),
                settings=ChromaSettings(anonymized_telemetry=False),
            )
        return self._chroma

    def active_collection(self, session: Session) -> str:
        return session.scalar(select(KnowledgeIndex.collection_name).where(
            KnowledgeIndex.namespace == self.collection_name,
        )) or self.collection_name

    def _visible(self) -> tuple[str, dict | None, dict[str, str]]:
        collection = self.collection_name
        filters = []
        filenames = {}
        builtin_ids = sorted(path.stem for path in KNOWLEDGE_DIRECTORY.glob("*.md"))
        if builtin_ids:
            filters.append({"document_id": {"$in": builtin_ids}})
            filenames.update({doc_id: f"{doc_id}.md" for doc_id in builtin_ids})
        if self.engine is not None:
            with Session(self.engine) as session:
                collection = self.active_collection(session)
                files = session.execute(select(
                    KnowledgeFile.document_id, KnowledgeFile.original_filename, KnowledgeFile.published_batch,
                ).where(
                    KnowledgeFile.published_collection == collection,
                    KnowledgeFile.published_batch.is_not(None),
                    KnowledgeFile.indexing_status == "ready",
                )).all()
            if files:
                filters.append({"publication_id": {"$in": [batch for _, _, batch in files]}})
                filenames.update({document_id: filename for document_id, filename, _ in files})
        where = {"$or": filters} if len(filters) > 1 else filters[0] if filters else None
        return collection, where, filenames

    def _collection(self, name: str, *, create: bool = False):
        try:
            client = self._client()
            if create:
                return client.get_or_create_collection(
                    name, embedding_function=None, configuration={"hnsw": {"space": "cosine"}},
                )
            return client.get_collection(name, embedding_function=None)
        except AgentProblem:
            raise
        except Exception as error:
            from chromadb.errors import NotFoundError

            if isinstance(error, NotFoundError):
                raise AgentProblem("RAG_NOT_INITIALIZED", "Chưa có chỉ mục cho model embedding hiện tại.") from None
            raise AgentProblem("RAG_CHROMA_ERROR", "Hiện chưa mở được chỉ mục ChromaDB.") from None

    def write_chunks(
        self, name: str, chunks: list[Chunk], *, publication_id: str | None = None, download_model: bool = False,
    ) -> int:
        if not chunks:
            raise AgentProblem("RAG_EMPTY_INDEX", "Không có nội dung văn bản để lập chỉ mục.")
        # Load and run the model before creating a collection for a fresh install.
        vectors = self._embed([f"{chunk.source.title}. {chunk.text}" for chunk in chunks], download=download_model)
        ids = [chunk.chunk_id for chunk in chunks]
        if len(ids) != len(set(ids)) or len(vectors) != len(ids):
            raise AgentProblem("RAG_INDEX_VERIFY_FAILED", "Số vector không khớp các đoạn cần lập chỉ mục.")
        collection = self._collection(name, create=True)
        try:
            for start in range(0, len(chunks), 128):
                stop = start + 128
                part = chunks[start:stop]
                metadata = [chunk.source.model_dump(mode="json", exclude_none=True) for chunk in part]
                if publication_id is not None:
                    for record in metadata:
                        record["publication_id"] = publication_id
                collection.upsert(
                    ids=ids[start:stop], documents=[chunk.text for chunk in part],
                    embeddings=vectors[start:stop], metadatas=metadata,
                )
                where = {"publication_id": publication_id} if publication_id else None
                saved = collection.get(ids=ids[start:stop], where=where, include=[])["ids"]
                if set(saved) != set(ids[start:stop]):
                    raise AgentProblem("RAG_INDEX_VERIFY_FAILED", "ChromaDB chưa lưu đủ vector.")
            return len(ids)
        except AgentProblem:
            raise
        except Exception:
            raise AgentProblem("RAG_CHROMA_ERROR", "Ghi hoặc xác minh vector trong ChromaDB thất bại.") from None

    def delete_chunks(self, name: str, where: dict) -> None:
        if not (self.settings.rag_directory / "chroma.sqlite3").is_file():
            return
        try:
            collection = self._collection(name)
        except AgentProblem as error:
            if error.code == "RAG_NOT_INITIALIZED":
                return
            raise
        try:
            collection.delete(where=where)
            if collection.get(where=where, limit=1, include=[])["ids"]:
                raise AgentProblem("RAG_CHROMA_ERROR", "ChromaDB vẫn còn vector cần xóa.")
        except AgentProblem:
            raise
        except Exception:
            raise AgentProblem("RAG_CHROMA_ERROR", "Không dọn được các vector khỏi ChromaDB.") from None

    def discard_collection(self, name: str) -> None:
        try:
            self._client().delete_collection(name)
        except Exception:
            raise AgentProblem("RAG_CHROMA_ERROR", "Không dọn được collection dựng tạm.") from None

    def delete_document(self, document_id: str) -> None:
        if not (self.settings.rag_directory / "chroma.sqlite3").is_file():
            return
        try:
            for collection in self._client().list_collections():
                name = collection.name
                if re.fullmatch(r"moneymind_knowledge_[0-9a-f]{16}(?:_g_[0-9a-f]{32})?", name):
                    self.delete_chunks(name, {"document_id": document_id})
        except AgentProblem:
            raise
        except Exception:
            raise AgentProblem("RAG_CHROMA_ERROR", "Không dọn được vector của tài liệu.") from None

    def ingest(self, chunks: list[Chunk], *, download_model: bool = False) -> int:
        with self.lock:
            name = self.collection_name
            if self.engine is not None:
                with Session(self.engine) as session:
                    name = self.active_collection(session)
            return self.write_chunks(name, chunks, download_model=download_model)

    def indexed_document_ids(self, name: str, document_ids: list[str]) -> set[str]:
        collection = self._collection(name)
        try:
            result = collection.get(where={"document_id": {"$in": document_ids}}, include=["metadatas"])
            return {metadata["document_id"] for metadata in result["metadatas"]}
        except Exception:
            raise AgentProblem("RAG_CHROMA_ERROR", "Không đọc được tài liệu trong chỉ mục.") from None

    def retrieve(self, question: str) -> list[Chunk]:
        with observe("rag.retrieval", model_name=self.settings.embedding_model) as span:
            results = [
                (chunk, score) for chunk, score in self.rank(question)
                if score >= self.settings.rag_min_similarity
            ]
            span.rag_hits = [(chunk.source.document_id, chunk.chunk_id, score) for chunk, score in results]
            if not results:
                span.status = "NO_CONTEXT"
            return [chunk for chunk, _ in results]

    def missing_index(self) -> AgentProblem:
        if self.engine is not None:
            with Session(self.engine) as session:
                statuses = set(session.scalars(select(KnowledgeFile.indexing_status).distinct()))
                has_pointer = session.get(KnowledgeIndex, self.collection_name) is not None
            if "ready" in statuses or has_pointer:
                return AgentProblem("RAG_INDEX_MISMATCH", "Kho có thông tin xuất bản nhưng chưa mở được collection "
                                    "tương ứng. Hãy kiểm tra đường dẫn Chroma và model embedding của Backend.")
            if statuses:
                return AgentProblem("RAG_INDEX_PENDING", "Tài liệu chưa có vector sẵn sàng. Hãy xem trạng thái "
                                    "trong Kho tài liệu và thử lập chỉ mục lại cho tệp báo lỗi.")
        return AgentProblem("RAG_NOT_INITIALIZED", "Kho kiến thức chưa có chỉ mục. Hãy tải tài liệu lên "
                            "Kho tài liệu và chờ trạng thái Sẵn sàng.")

    def rank(self, question: str, *, top_k: int | None = None) -> list[tuple[Chunk, float]]:
        if not (self.settings.rag_directory / "chroma.sqlite3").is_file():
            raise self.missing_index()
        with self.lock:
            name, where, filenames = self._visible()
            if where is None:
                return []
            try:
                collection = self._collection(name)
            except AgentProblem as error:
                if error.code == "RAG_NOT_INITIALIZED":
                    raise self.missing_index() from None
                raise
            limit = top_k or self.settings.rag_top_k
            if not question.isascii():
                return self._query(collection, question, where, limit, filenames)
            primary = self._query(collection, question, where, max(limit, 5), filenames)
            restored = restore_query_accents(question, [chunk for chunk, _ in primary])
            if restored == question:
                return primary[:limit]
            secondary = self._query(collection, restored, where, limit, filenames)
            merged = {}
            for chunk, score in [*primary, *secondary]:
                if chunk.chunk_id not in merged or score > merged[chunk.chunk_id][1]:
                    merged[chunk.chunk_id] = (chunk, score)
            return sorted(merged.values(), key=lambda item: -item[1])[:limit]

    def _query(
        self, collection, question: str, where: dict, top_k: int, filenames: dict[str, str],
    ) -> list[tuple[Chunk, float]]:
        vector = self._embed([question])
        try:
            matches = collection.query(
                query_embeddings=vector, where=where,
                n_results=top_k, include=["documents", "metadatas", "distances"],
            )
            return [
                (Chunk(chunk_id, text, Source.model_validate({
                    **{key: value for key, value in metadata.items() if key in Source.model_fields},
                    "original_filename": filenames.get(metadata["document_id"], metadata.get("original_filename")),
                })), 1 - distance)
                for chunk_id, text, metadata, distance in zip(
                    matches["ids"][0], matches["documents"][0],
                    matches["metadatas"][0], matches["distances"][0], strict=True,
                )
            ]
        except Exception:
            raise AgentProblem("RAG_CHROMA_ERROR", "Không truy vấn được các đoạn trong ChromaDB.") from None
