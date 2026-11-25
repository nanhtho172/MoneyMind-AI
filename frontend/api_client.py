from pathlib import Path
from typing import TypeVar
from uuid import UUID

import httpx
from pydantic import AnyHttpUrl, BaseModel, TypeAdapter, ValidationError
from pydantic_settings import BaseSettings, SettingsConfigDict

from backend.app.schemas.auth import LoginRequest, TokenResponse, UserView
from backend.app.schemas.chat import (
    ChatConfirmation, ChatRequest, ChatResponse, ConversationDeletion, ConversationHistory, ConversationItem, ConversationPage,
)
from backend.app.schemas.finance import (
    BudgetQuery, BudgetSet, BudgetStatus, BudgetView, CategoryView, CategorySpending,
    DateRange, FinancialSummary, TransactionCreate, TransactionPage, TransactionQuery,
    TransactionType, TransactionView,
)
from backend.app.schemas.knowledge import BuiltinDocument, DocumentItem

Output = TypeVar("Output")
HTTP_MESSAGES = {
    401: "Phiên đăng nhập đã hết hạn. Vui lòng đăng nhập lại.",
    403: "Bạn không có quyền thực hiện yêu cầu này.",
    404: "Không tìm thấy dữ liệu hoặc phiên yêu cầu.",
    409: "Yêu cầu xung đột với dữ liệu hiện tại. Hãy kiểm tra lại trạng thái.",
    413: "Tệp vượt quá giới hạn dung lượng tải lên.",
    415: "Loại tài liệu không được hỗ trợ.",
    422: "Dữ liệu không hợp lệ. Hãy kiểm tra lại các trường đã nhập.",
    429: "Có quá nhiều yêu cầu. Hãy thử lại sau.",
    503: "Backend đang bận. Hãy kiểm tra trạng thái trước khi thử lại.",
}


class FrontendSettings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=Path(__file__).resolve().parents[1] / ".env", env_file_encoding="utf-8", extra="ignore",
    )
    backend_url: AnyHttpUrl = "http://127.0.0.1:8000"


class ApiError(Exception):
    def __init__(self, message: str, status_code: int | None = None):
        super().__init__(message)
        self.status_code = status_code


class ApiClient:
    def __init__(self, base_url: str, token: str | None = None, *, transport: httpx.BaseTransport | None = None):
        self._http = httpx.Client(
            base_url=base_url, headers={"Authorization": f"Bearer {token}"} if token else {},
            timeout=httpx.Timeout(75, connect=4), transport=transport, trust_env=False,
        )

    def __enter__(self):
        return self

    def __exit__(self, *_):
        self._http.close()

    def _request(
        self, method: str, path: str, schema: type[Output] | TypeAdapter[Output],
        *, body: BaseModel | None = None, query: BaseModel | None = None,
        files: dict | None = None,
    ) -> Output:
        try:
            response = self._http.request(
                method, path, json=body.model_dump(mode="json", exclude_none=True) if body else None,
                params=query.model_dump(mode="json", exclude_none=True) if query else None,
                files=files,
            )
        except httpx.TimeoutException:
            raise ApiError("Backend phản hồi quá chậm. Hãy thử lại.") from None
        except httpx.RequestError:
            raise ApiError("Không kết nối được Backend. Hãy kiểm tra Uvicorn và BACKEND_URL.") from None
        if not response.is_success:
            fallback = "Backend gặp lỗi. Hãy thử lại sau." if response.status_code >= 500 else "Backend từ chối yêu cầu."
            message = HTTP_MESSAGES.get(response.status_code, fallback)
            if path.startswith("/api/knowledge/"):
                try:
                    detail = response.json().get("detail")
                    if isinstance(detail, dict) and isinstance(detail.get("message"), str):
                        message = detail["message"]
                except (ValueError, AttributeError):
                    pass
            raise ApiError(message, response.status_code)
        if response.status_code == 204 and schema is type(None):
            return None
        try:
            adapter = schema if isinstance(schema, TypeAdapter) else TypeAdapter(schema)
            return adapter.validate_json(response.content)
        except ValidationError:
            raise ApiError("Backend trả dữ liệu khác cấu trúc API mong đợi.") from None

    def login(self, request: LoginRequest) -> TokenResponse:
        return self._request("POST", "/api/auth/login", TokenResponse, body=request)

    def me(self) -> UserView:
        return self._request("GET", "/api/auth/me", UserView)

    def categories(self) -> list[CategoryView]:
        return self._request("GET", "/api/categories", TypeAdapter(list[CategoryView]))

    def transactions(self, query: TransactionQuery) -> TransactionPage:
        return self._request("GET", "/api/transactions", TransactionPage, query=query)

    def create_transaction(self, request: TransactionCreate) -> TransactionView:
        return self._request("POST", "/api/transactions", TransactionView, body=request)

    def summary(self, query: DateRange) -> FinancialSummary:
        return self._request("GET", "/api/reports/summary", FinancialSummary, query=query)

    def spending(self, query: DateRange) -> list[CategorySpending]:
        return self._request("GET", "/api/reports/by-category", TypeAdapter(list[CategorySpending]), query=query)

    def budget_status(self, query: BudgetQuery) -> list[BudgetStatus]:
        return self._request("GET", "/api/budgets/status", TypeAdapter(list[BudgetStatus]), query=query)

    def set_budget(self, request: BudgetSet) -> BudgetView:
        return self._request("PUT", "/api/budgets", BudgetView, body=request)

    def chat(self, request: ChatRequest) -> ChatResponse:
        return self._request("POST", "/api/chat", ChatResponse, body=request)

    def current_conversation(self) -> ConversationHistory:
        return self._request("GET", "/api/chat/conversations/current", ConversationHistory)

    def reset_conversation(self) -> ConversationHistory:
        return self._request("POST", "/api/chat/conversations", ConversationHistory)

    def conversations(self) -> list[ConversationItem]:
        return self._request("GET", "/api/chat/conversations", TypeAdapter(list[ConversationItem]))

    def conversation_page(self, conversation_id: UUID, before: int | None = None) -> ConversationPage:
        suffix = f"?before={int(before)}" if before is not None else ""
        return self._request("GET", f"/api/chat/conversations/{conversation_id}{suffix}", ConversationPage)

    def delete_conversation(self, conversation_id: UUID) -> None:
        self._request("DELETE", f"/api/chat/conversations/{conversation_id}", type(None),
                      body=ConversationDeletion(confirmed=True))

    def confirm(self, thread_id: UUID, request: ChatConfirmation) -> ChatResponse:
        return self._request("POST", f"/api/chat/{thread_id}/confirm", ChatResponse, body=request)

    def chat_state(self, thread_id: UUID) -> ChatResponse:
        return self._request("GET", f"/api/chat/{thread_id}/state", ChatResponse)

    def knowledge_documents(self) -> list[DocumentItem]:
        return self._request("GET", "/api/knowledge/documents", TypeAdapter(list[DocumentItem]))

    def knowledge_builtins(self) -> list[BuiltinDocument]:
        return self._request("GET", "/api/knowledge/builtin", TypeAdapter(list[BuiltinDocument]))

    def knowledge_upload(self, filename: str, mime: str, content: bytes) -> DocumentItem:
        return self._request(
            "POST", "/api/knowledge/documents", DocumentItem,
            files={"file": (filename, content, mime or "application/octet-stream")},
        )

    def knowledge_retry(self, document_id: UUID) -> DocumentItem:
        return self._request("POST", f"/api/knowledge/documents/{document_id}/retry", DocumentItem)

    def knowledge_remove(self, document_id: UUID) -> None:
        self._request("DELETE", f"/api/knowledge/documents/{document_id}", type(None))
