import os
import re
from hashlib import sha256
from pathlib import Path, PurePosixPath
from tempfile import NamedTemporaryFile
from uuid import UUID

from backend.app.services.document_extraction import DocumentError


class UploadStorage:
    def __init__(self, root: Path):
        self.root = root.resolve()
        self.root.mkdir(parents=True, exist_ok=True)

    @staticmethod
    def relative_name(document_id: str, filename: str, file_type: str) -> str:
        stem = filename.rsplit(".", 1)[0]
        # Bound the stored component, reserve a safe prefix and retain the validated suffix.
        stem = re.sub(r"[^A-Za-z0-9_-]+", "-", stem).strip("-_")[:80] or "tai-lieu"
        suffix = file_type if file_type in {"pdf", "docx", "txt", "md"} else "bin"
        return f"{UUID(document_id)}/file-{stem}.{suffix}"

    def _folder(self, document_id: str) -> Path:
        path = self.root / str(UUID(document_id))
        if path.resolve() != path:
            raise DocumentError("UNSAFE_STORAGE_PATH", "Thư mục tài liệu không phải đường dẫn lưu trữ hợp lệ.")
        return path

    def _file(self, document_id: str, relative_path: str) -> Path:
        relative = PurePosixPath(relative_path)
        if len(relative.parts) != 2 or relative.parts[0] != str(UUID(document_id)) or not re.fullmatch(
            r"file-[A-Za-z0-9_-]{1,80}\.(pdf|docx|md|txt|bin)", relative.name,
        ):
            raise DocumentError("UNSAFE_STORAGE_PATH", "Đường dẫn tệp nằm ngoài thư mục tài liệu.")
        target = self._folder(document_id) / relative.name
        if target.resolve() != target:
            raise DocumentError("UNSAFE_STORAGE_PATH", "Tệp lưu trữ không phải tệp cục bộ hợp lệ.")
        return target

    def save(self, document_id: str, relative_path: str, content: bytes) -> None:
        target = self._file(document_id, relative_path)
        target.parent.mkdir(parents=True, exist_ok=True)
        # A crash before replace leaves only a scoped temporary file, never a partial original.
        temporary = None
        try:
            with NamedTemporaryFile(dir=target.parent, prefix=".upload-", suffix=".tmp", delete=False) as stream:
                temporary = Path(stream.name)
                stream.write(content)
                stream.flush()
                os.fsync(stream.fileno())
            temporary.replace(target)
        finally:
            if temporary is not None:
                temporary.unlink(missing_ok=True)

    def read_verified(self, document_id: str, relative_path: str, size: int, digest: str) -> bytes:
        target = self._file(document_id, relative_path)
        with target.open("rb") as stream:
            content = stream.read(size + 1)
        if len(content) != size or sha256(content).hexdigest() != digest:
            raise DocumentError("FILE_INTEGRITY_ERROR", "Kích thước hoặc hash của tệp lưu không khớp.")
        return content

    def remove(self, document_id: str, relative_path: str | None) -> None:
        folder = self._folder(document_id)
        if relative_path is not None:
            self._file(document_id, relative_path).unlink(missing_ok=True)
        if folder.is_dir():
            for temporary in folder.glob(".upload-*.tmp"):
                temporary.unlink(missing_ok=True)
            folder.rmdir()
