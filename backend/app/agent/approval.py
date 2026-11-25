from sqlalchemy import select, text
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session

from backend.app.agent.llm import AgentProblem
from backend.app.core.observability import observe
from backend.app.models.chat import ChatConversation, ChatThread, ChatTurn
from backend.app.models.finance import utc_now
from backend.app.schemas.chat import ChatResponse, Decision, PendingAction, PendingBudget, PendingTransaction
from backend.app.schemas.finance import BudgetView, TransactionCreate, TransactionView
from backend.app.services import finance


def commit_confirmed_transaction(
    session: Session, owner_id: int, thread_id: str, action: PendingTransaction,
) -> TransactionView:
    transaction = TransactionCreate(**action.payload.model_dump(), idempotency_key=f"chat:{thread_id}")
    return finance.create_transaction(session, owner_id, transaction)


def commit_confirmed_budget(session: Session, owner_id: int, action: PendingBudget) -> BudgetView:
    return finance.set_budget(session, owner_id, action.payload)


def complete_decision(
    engine: Engine, user_id: int, thread_id: str, decision: Decision, action: PendingAction,
) -> ChatResponse:
    with Session(engine) as session, session.begin():

        session.execute(text("BEGIN IMMEDIATE"))
        thread = session.get(ChatThread, thread_id)
        if thread is None or thread.user_id != user_id or thread.decision != decision:
            raise AgentProblem("APPROVAL_REQUIRED", "Chưa có quyết định hợp lệ cho thao tác này.")
        if thread.receipt is not None:
            return ChatResponse.model_validate(thread.receipt)

        if decision == "CANCEL":
            response = ChatResponse(
                status="COMPLETED", thread_id=thread_id, message="Đã hủy thao tác.",
            )
        elif isinstance(action, PendingTransaction):
            with observe("financial.tool", tool_name="commit_confirmed_transaction"):
                result = commit_confirmed_transaction(session, user_id, thread_id, action)
            response = ChatResponse(
                status="COMPLETED", thread_id=thread_id, message="Đã lưu giao dịch.", structured_data=result,
            )
        else:
            with observe("financial.tool", tool_name="commit_confirmed_budget"):
                result = commit_confirmed_budget(session, user_id, action)
            response = ChatResponse(
                status="COMPLETED", thread_id=thread_id, message="Đã lưu ngân sách.", structured_data=result,
            )
        thread.receipt = response.model_dump(mode="json")
        conversation = session.scalar(select(ChatConversation).join(ChatTurn).where(ChatTurn.thread_id == thread_id))
        if conversation is not None:
            conversation.updated_at = utc_now()
        return response
