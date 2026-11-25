from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response
from sqlalchemy.exc import OperationalError

from backend.app.agent.runtime import ChatRuntime, ConversationNotFound, ThreadConflict, ThreadNotFound
from backend.app.api.dependencies import CurrentUser
from backend.app.schemas.chat import (
    ChatConfirmation, ChatRequest, ChatResponse, ConversationDeletion, ConversationHistory, ConversationItem, ConversationPage,
)

router = APIRouter(prefix="/chat", tags=["Chat"], responses={401: {"description": "Bearer token required"}})


def get_chat_runtime(request: Request) -> ChatRuntime:
    return request.app.state.chat_runtime


ChatAgent = Annotated[ChatRuntime, Depends(get_chat_runtime)]


@router.post("")
def start_chat(data: ChatRequest, user: CurrentUser, agent: ChatAgent) -> ChatResponse:
    try:
        return agent.start(user.id, data.message, data.conversation_id)
    except ConversationNotFound:
        raise HTTPException(status_code=404, detail="Không tìm thấy cuộc hội thoại.") from None
    except OperationalError:
        raise HTTPException(status_code=503, detail="Chat đang bận. Hãy kiểm tra trạng thái rồi thử lại.") from None


@router.get("/conversations/current")
def current_conversation(user: CurrentUser, agent: ChatAgent) -> ConversationHistory:
    return agent.history(user.id)


@router.get("/conversations")
def list_conversations(user: CurrentUser, agent: ChatAgent) -> list[ConversationItem]:
    return agent.list_conversations(user.id)


@router.delete("/conversations/{conversation_id}", status_code=204)
def delete_conversation(conversation_id: UUID, data: ConversationDeletion, user: CurrentUser, agent: ChatAgent) -> Response:
    try:
        agent.delete_conversation(user.id, conversation_id)
    except ConversationNotFound:
        raise HTTPException(status_code=404, detail="Không tìm thấy cuộc hội thoại.") from None
    return Response(status_code=204)


@router.get("/conversations/{conversation_id}")
def conversation_history(conversation_id: UUID, user: CurrentUser, agent: ChatAgent,
                         before: Annotated[int | None, Query(gt=0)] = None,
                         limit: Annotated[int, Query(ge=1, le=100)] = 50) -> ConversationPage:
    try:
        return agent.history_page(user.id, conversation_id, before, limit)
    except ConversationNotFound:
        raise HTTPException(status_code=404, detail="Không tìm thấy cuộc hội thoại.") from None


@router.post("/conversations", status_code=201)
def reset_conversation(user: CurrentUser, agent: ChatAgent) -> ConversationHistory:
    return agent.new_conversation(user.id)


@router.post(
    "/{thread_id}/confirm",
    responses={404: {"description": "Thread not found"}, 409: {"description": "Decision conflicts with thread state"}},
)
def confirm_chat(
    thread_id: UUID, data: ChatConfirmation, user: CurrentUser, agent: ChatAgent,
) -> ChatResponse:
    try:
        return agent.confirm(user.id, thread_id, data.decision)
    except ThreadNotFound:
        raise HTTPException(status_code=404, detail="Không tìm thấy phiên chat.") from None
    except ThreadConflict as error:
        raise HTTPException(status_code=409, detail=str(error)) from None
    except OperationalError:
        raise HTTPException(status_code=503, detail="Chưa thể xử lý xác nhận. Hãy gửi lại cùng quyết định.") from None


@router.get("/{thread_id}/state", responses={404: {"description": "Thread not found"}})
def chat_state(thread_id: UUID, user: CurrentUser, agent: ChatAgent) -> ChatResponse:
    try:
        return agent.state(user.id, thread_id)
    except ThreadNotFound:
        raise HTTPException(status_code=404, detail="Không tìm thấy phiên chat.") from None
