from datetime import date
from typing import Annotated, Literal
from uuid import UUID

from pydantic import AnyHttpUrl, Field, StringConstraints

from backend.app.models.finance import TransactionType
from backend.app.schemas.common import InputModel, StoredUTC
from backend.app.schemas.finance import (
    Amount, BudgetSet, BudgetStatus, BudgetView, CategoryId, CategorySpending,
    FinancialSummary, TransactionPage, TransactionView,
)

Intent = Literal[
    "CREATE_TRANSACTION", "QUERY_STATISTICS", "SET_BUDGET", "FINANCIAL_ADVICE", "PERSONAL_FINANCIAL_ADVICE", "UNKNOWN",
    "GENERAL_CONVERSATION", "GREETING", "DATE_TIME", "CLARIFICATION", "PENDING_ACTION_REQUEST",
]
Decision = Literal["CONFIRM", "CANCEL"]
ChatStatus = Literal["COMPLETED", "NEEDS_CLARIFICATION", "PENDING_CONFIRMATION", "ERROR"]
PendingState = Literal["collecting", "ready_for_confirmation", "confirmed", "cancelled", "superseded"]
TransactionField = Literal["amount", "date", "category", "type", "note"]
TransactionTiming = Literal["actual", "planned", "explicit_record"]
DialogueAction = Literal[
    "supplement_pending", "modify_pending", "cancel_pending", "confirm_request",
    "new_request", "general_chat", "clarification_needed",
]
FinancialData = FinancialSummary | list[CategorySpending] | list[BudgetStatus] | TransactionPage


class ChatRequest(InputModel):
    message: Annotated[str, StringConstraints(
        strict=True, strip_whitespace=True, min_length=1, max_length=1500
    )]
    conversation_id: UUID | None = None


class ChatConfirmation(InputModel):
    decision: Decision


class TransactionDraft(InputModel):
    category_id: CategoryId
    type: TransactionType
    amount: Amount
    note: Annotated[str, Field(max_length=500)] | None
    transaction_date: date


class PendingTransaction(InputModel):
    kind: Literal["CREATE_TRANSACTION"]
    category: str
    payload: TransactionDraft


class PendingBudget(InputModel):
    kind: Literal["SET_BUDGET"]
    category: str
    payload: BudgetSet


PendingAction = Annotated[PendingTransaction | PendingBudget, Field(discriminator="kind")]


class Source(InputModel):
    document_id: str
    title: str
    source: str
    document_title: str | None = None
    source_name: str | None = None
    source_url: AnyHttpUrl | None = None
    page_number: int | None = None
    chunk_id: str | None = None
    evidence: str | None = None
    original_filename: str | None = None


class AdvisoryScope(InputModel):
    start_date: date
    end_date: date
    topic: str


class ChatResponse(InputModel):
    status: ChatStatus
    thread_id: UUID
    conversation_id: UUID | None = None
    message: str
    pending_action: PendingAction | None = None
    structured_data: TransactionView | BudgetView | None = None
    financial_data: FinancialData | None = None
    sources: list[Source] = Field(default_factory=list)
    error_code: str | None = None
    pending_state: PendingState | None = None
    draft_version: int | None = None
    advisory_scope: AdvisoryScope | None = None


class ConversationTurn(InputModel):
    message: str
    response: ChatResponse


class ConversationHistory(InputModel):
    conversation_id: UUID | None = None
    turns: list[ConversationTurn] = Field(default_factory=list)


class ConversationPage(ConversationHistory):
    next_before: int | None = None
    earlier_pending: ConversationTurn | None = None


class ConversationItem(InputModel):
    conversation_id: UUID
    title: str
    updated_at: StoredUTC | None


class ConversationDeletion(InputModel):
    confirmed: Literal[True]


class IntentOutput(InputModel):
    intent: Intent


class GeneralReply(InputModel):
    message: str


class StandaloneQuestion(InputModel):
    question: str


class TransactionExtraction(InputModel):
    type: Literal["INCOME", "EXPENSE"] | None
    amount_text: str | None
    category: str | None
    date_text: str | None
    note: str | None
    multiple: bool


class TransactionProposal(TransactionExtraction):
    timing: TransactionTiming


class TransactionChanges(InputModel):
    amount_text: str | None
    date_text: str | None
    category: str | None
    type: Literal["INCOME", "EXPENSE"] | None
    note: str | None
    clear_note: bool
    timing: TransactionTiming | None


class DialogueUpdate(InputModel):
    action: DialogueAction
    changes: TransactionChanges
    needs_clarification: bool
    clarification_field: TransactionField | None


class BudgetExtraction(InputModel):
    amount_text: str | None
    category: str | None
    period_text: str | None
    multiple: bool


class AdviceSelection(InputModel):
    chunk_ids: list[str]


class GroundedStatement(InputModel):
    text: str
    chunk_id: str
    evidence: str


class GroundedAnswer(InputModel):
    coverage: Literal["full", "partial", "none"]
    statements: list[GroundedStatement]
