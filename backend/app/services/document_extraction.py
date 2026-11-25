import re
import unicodedata
from dataclasses import dataclass
from io import BytesIO
from pathlib import PurePath
from zipfile import BadZipFile, ZipFile

from backend.app.schemas.knowledge import DocumentPage, FileType

_MIME = {
    "pdf": {"application/pdf"},
    "docx": {"application/vnd.openxmlformats-officedocument.wordprocessingml.document", "application/zip"},
    "txt": {"text/plain"},
    "md": {"text/plain", "text/markdown", "text/x-markdown"},
}
_MAX_PAGES = 300
_MAX_TEXT = 300_000


class DocumentError(Exception):
    def __init__(self, code: str, message: str, status: int = 422):
        super().__init__(message)
        self.code = code
        self.status = status


@dataclass(frozen=True)
class Extraction:
    pages: list[DocumentPage]
    page_count: int | None


def validate_upload(filename: str, mime_type: str, content: bytes, max_bytes: int) -> tuple[str, FileType]:
    name = unicodedata.normalize("NFC", filename).strip()
    if not name or len(name) > 255 or any(char in '/\\:\x00' or ord(char) < 32 for char in name):
        raise DocumentError("INVALID_FILENAME", "Tên tệp không hợp lệ.")
    file_type = PurePath(name).suffix.removeprefix(".").lower()
    if file_type not in _MIME:
        raise DocumentError("UNSUPPORTED_FILE", "Kho hỗ trợ PDF, DOCX, TXT và Markdown (.md).", 415)
    mime = mime_type.partition(";")[0].strip().lower()
    if mime not in {"", "application/octet-stream", *_MIME[file_type]}:
        raise DocumentError("MIME_MISMATCH", "Loại nội dung của tệp không khớp phần mở rộng.", 415)
    if len(content) > max_bytes:
        raise DocumentError("UPLOAD_TOO_LARGE", "Tệp vượt quá giới hạn dung lượng tải lên.", 413)
    return name, file_type


def normalize(text: str) -> str:
    text = unicodedata.normalize("NFC", text).replace("\r\n", "\n").replace("\r", "\n")
    text = "".join(char for char in text if char in "\n\t" or unicodedata.category(char) not in {"Cc", "Cf"})
    lines = [" ".join(line.split()) for line in text.split("\n")]
    return re.sub(r"\n{3,}", "\n\n", "\n".join(lines)).strip()


def _pdf(content: bytes) -> Extraction:
    if not content.startswith(b"%PDF-"):
        raise DocumentError("INVALID_PDF", "Tệp không có chữ ký PDF hợp lệ.")
    try:
        from pypdf import PdfReader
    except ImportError:
        raise DocumentError("EXTRACTION_DEPENDENCY", "Cần cài pypdf để đọc PDF.", 503) from None
    try:
        reader = PdfReader(BytesIO(content))
        if reader.is_encrypted:
            raise DocumentError("PDF_ENCRYPTED", "Hãy cung cấp bản PDF không mã hóa.")
        if len(reader.pages) > _MAX_PAGES:
            raise DocumentError("DOCUMENT_TOO_LONG", "PDF vượt quá 300 trang.")
        pages = []
        size = 0
        for number, page in enumerate(reader.pages, 1):
            text = normalize(page.extract_text() or "")
            size += len(text)
            if size > _MAX_TEXT:
                raise DocumentError("DOCUMENT_TOO_LONG", "Văn bản vượt quá 300.000 ký tự.")
            pages.append(DocumentPage(page_number=number, text=text))
        if not any(_has_text(page.text) for page in pages):
            raise DocumentError("PDF_NO_TEXT", "PDF không có văn bản có thể trích xuất, cần OCR.")
        return Extraction(pages, len(pages))
    except DocumentError:
        raise
    except Exception:
        raise DocumentError("INVALID_PDF", "Không đọc được cấu trúc hoặc văn bản của PDF.") from None


def _docx(content: bytes) -> str:
    try:
        from docx import Document
        from docx.table import Table
    except ImportError:
        raise DocumentError("EXTRACTION_DEPENDENCY", "Cần cài python-docx để đọc DOCX.", 503) from None
    try:
        with ZipFile(BytesIO(content)) as package:
            entries = package.infolist()
            names = package.namelist()
            if len(entries) > 2000 or sum(item.file_size for item in entries) > 60 * 1024**2:
                raise DocumentError("DOCUMENT_TOO_LONG", "Gói DOCX vượt giới hạn kích thước sau giải nén.")
            if "[Content_Types].xml" not in names or "word/document.xml" not in names:
                raise DocumentError("INVALID_DOCX", "Tệp thiếu các thành phần bắt buộc của DOCX.")
            content_types = package.read("[Content_Types].xml").lower().replace(b"\x00", b"")
            if any("vbaproject" in name.lower() for name in names) or b"macroenabled" in content_types:
                raise DocumentError("DOCX_MACROS", "Kho chỉ nhận tài liệu DOCX không chứa macro.")
        blocks = []
        for block in Document(BytesIO(content)).iter_inner_content():
            if isinstance(block, Table):
                blocks.extend(" | ".join(cell.text for cell in row.cells) for row in block.rows)
            elif block.text.strip():
                style = block.style.name if block.style else ""
                heading = re.fullmatch(r"Heading ([1-6])", style)
                prefix = "#" * int(heading[1]) + " " if heading else "# " if style == "Title" else ""
                blocks.append(prefix + block.text)
        return "\n\n".join(blocks)
    except DocumentError:
        raise
    except (BadZipFile, ValueError, KeyError, OSError):
        raise DocumentError("INVALID_DOCX", "Không đọc được gói DOCX.") from None
    except Exception:
        raise DocumentError("INVALID_DOCX", "Không đọc được nội dung Word.") from None


def _has_text(text: str) -> bool:
    return any(char.isalnum() for char in text)


def extract(content: bytes, file_type: FileType) -> Extraction:
    if not content:
        raise DocumentError("EMPTY_DOCUMENT", "Tệp không chứa nội dung.")
    if file_type == "pdf":
        return _pdf(content)
    if file_type == "docx":
        text = _docx(content)
    else:
        if content.startswith((b"%PDF-", b"PK\x03\x04")):
            raise DocumentError("MIME_MISMATCH", "Nội dung tệp không khớp định dạng văn bản.")
        try:
            encoding = "utf-16" if content.startswith((b"\xff\xfe", b"\xfe\xff")) else "utf-8-sig"
            text = content.decode(encoding)
        except UnicodeError:
            raise DocumentError("INVALID_TEXT", "TXT và Markdown cần mã hóa UTF-8 hoặc UTF-16 có BOM.") from None
        if "\x00" in text:
            raise DocumentError("INVALID_TEXT", "Tệp chứa dữ liệu nhị phân thay vì văn bản.")
    normalized = normalize(text)
    if not _has_text(normalized):
        raise DocumentError("EMPTY_DOCUMENT", "Không tìm thấy nội dung văn bản có thể sử dụng.")
    if len(normalized) > _MAX_TEXT:
        raise DocumentError("DOCUMENT_TOO_LONG", "Văn bản vượt quá 300.000 ký tự.")
    return Extraction([DocumentPage(page_number=None, text=normalized)], None)
