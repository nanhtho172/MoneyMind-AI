import re
from datetime import date as Date

from backend.app.agent.guardrails import checked_amount, checked_date, clarify, folded, match_category, sanitize
from backend.app.agent.llm import AgentProblem
from backend.app.core.formatting import money
from backend.app.models.finance import TransactionType
from backend.app.schemas.chat import (
    PendingTransaction, TransactionChanges, TransactionDraft, TransactionField, TransactionProposal, TransactionTiming,
)
from backend.app.schemas.common import InputModel
from backend.app.schemas.finance import Amount, CategoryView


class TransactionWork(InputModel):
    amount: Amount | None = None
    date: Date | None = None
    category: str | None = None
    type: TransactionType | None = None
    note: str | None = None
    timing: TransactionTiming = "actual"

    @classmethod
    def from_draft(cls, draft: PendingTransaction) -> "TransactionWork":
        payload = draft.payload
        return cls(amount=payload.amount, date=payload.transaction_date, category=draft.category,
                   type=payload.type, note=payload.note, timing="explicit_record")


FIELD_QUESTIONS: dict[TransactionField, tuple[str, str]] = {
    "amount": ("AMOUNT_REQUIRED", "Khoản này là bao nhiêu tiền? Hãy ghi rõ đơn vị nếu dùng cách nói rút gọn."),
    "date": ("DATE_REQUIRED", "Khoản này ghi vào ngày nào?"),
    "category": ("CATEGORY_REQUIRED", "Khoản này thuộc danh mục nào trong MoneyMind?"),
    "type": ("TYPE_REQUIRED", "Đây là khoản thu hay khoản chi?"),
    "note": ("NOTE_REQUIRED", "Bạn muốn ghi chú nội dung gì?"),
}


def ask_for(field: TransactionField | None) -> AgentProblem:
    if field is None:
        return clarify("PENDING_DETAILS_REQUIRED", "Bạn muốn bổ sung hoặc sửa thông tin nào của khoản này?")
    return clarify(*FIELD_QUESTIONS[field])


def available_category(categories: list[CategoryView], name: str | None, kind: TransactionType | None) -> str | None:
    if name and kind is not None:
        return match_category([item for item in categories if item.type == kind], name).name
    if name and any(folded(item.name) == folded(name) for item in categories):
        return name
    return None


def collect_transaction(
    message: str, proposal: TransactionProposal, categories: list[CategoryView], today: Date,
) -> tuple[TransactionWork, AgentProblem | None]:
    amount, day, category, amount_error = None, None, None, None
    kind = TransactionType(proposal.type) if proposal.type else None
    try:
        amount = checked_amount(message, proposal.amount_text, proposal.multiple)
    except AgentProblem as error:
        if error.code == "MULTIPLE_ACTIONS":
            raise
        amount_error = error
    try:
        day = checked_date(message, today)
    except AgentProblem:
        pass
    try:
        category = available_category(categories, proposal.category, kind)
    except AgentProblem:
        pass
    return TransactionWork(
        amount=amount, date=day, category=category, type=kind, timing=proposal.timing,
        note=sanitize(proposal.note.strip())[:500] if proposal.note else None,
    ), amount_error


def quoted_field(message: str, proposed: str, field: TransactionField) -> str:
    token = folded(proposed)
    if not token or re.search(rf"(?<!\w){re.escape(token)}(?!\w)", folded(message)) is None:
        raise ask_for(field)
    return proposed


def apply_changes(
    work: TransactionWork, message: str, changes: TransactionChanges, categories: list[CategoryView], today: Date,
) -> TransactionWork:
    values = work.model_dump()
    if changes.amount_text is not None:
        values["amount"] = checked_amount(message, changes.amount_text, False, correction=True)
    if changes.date_text is not None:
        values["date"] = checked_date(quoted_field(message, changes.date_text, "date"), today)
    if changes.type is not None:
        values["type"] = TransactionType(changes.type)
    if changes.category is not None:
        values["category"] = available_category(categories, changes.category, values["type"])
        if values["category"] is None:
            raise ask_for("category")
    elif values["type"] != work.type:
        try:
            values["category"] = available_category(categories, work.category, values["type"])
        except AgentProblem:
            values["category"] = None
    if changes.clear_note and changes.note is not None:
        raise ask_for("note")
    if changes.clear_note:
        values["note"] = None
    elif changes.note is not None:
        values["note"] = sanitize(quoted_field(message, changes.note, "note").strip())[:500]
    if changes.timing is not None:
        values["timing"] = changes.timing
    elif values["date"] != work.date and values["date"] is not None and values["date"] > today:
        values["timing"] = "planned"
    return TransactionWork.model_validate(values)


def prepare_transaction(
    work: TransactionWork, categories: list[CategoryView], today: Date,
) -> PendingTransaction:
    if work.amount is None:
        raise ask_for("amount")
    if work.timing == "planned" or (work.date is not None and work.date > today and work.timing != "explicit_record"):
        raise clarify(
            "PLANNED_TRANSACTION",
            f"Mình đã hiểu đây là khoản dự kiến {money(work.amount)}. MoneyMind chưa theo dõi khoản dự kiến. "
            "Bạn muốn bàn cách lên kế hoạch hay yêu cầu ghi khoản này vào sổ?",
        )
    for field in ("type", "category", "date"):
        if getattr(work, field) is None:
            raise ask_for(field)
    category = match_category([item for item in categories if item.type == work.type], work.category)
    return PendingTransaction(
        kind="CREATE_TRANSACTION", category=category.name,
        payload=TransactionDraft(
            type=work.type, category_id=category.id, amount=work.amount,
            transaction_date=work.date, note=work.note,
        ),
    )
