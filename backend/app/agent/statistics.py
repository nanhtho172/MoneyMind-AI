import re
from typing import Literal

from pydantic import Field, ValidationError

from backend.app.agent.dates import CALENDAR_LITERAL
from backend.app.agent.guardrails import folded, match_category
from backend.app.agent.llm import AgentProblem, ToolCall
from backend.app.core.formatting import money
from backend.app.core.calendar import local_today
from backend.app.models.finance import TransactionType
from backend.app.schemas.chat import FinancialData
from backend.app.schemas.finance import BudgetQuery, DateRange, TransactionQuery
from backend.app.tools.finance import FinancialTools


class SpendingQuery(DateRange):
    category: str | None = Field(default=None, max_length=100)
    limit: int | None = Field(default=None, ge=1, le=100, description="Số danh mục đứng đầu khi được yêu cầu.")


class BudgetStatusQuery(BudgetQuery):
    category: str | None = Field(default=None, max_length=100)


class TransactionToolQuery(DateRange):
    category: str | None = Field(default=None, max_length=100)
    type: Literal[TransactionType.INCOME, TransactionType.EXPENSE] | None = None
    page: int = Field(default=1, ge=1, le=1_000_000)
    page_size: int = Field(default=10, ge=1, le=20)


READ_TOOLS = {
    "get_financial_summary": (DateRange, "Tổng thu, tổng chi và dòng tiền ròng trong khoảng ngày."),
    "get_spending_by_category": (SpendingQuery, "Tổng chi theo danh mục, có thể lọc tên danh mục."),
    "get_budget_status": (BudgetStatusQuery, "Hạn mức và chi tiêu của một tháng; có thể lọc danh mục."),
    "list_transactions": (TransactionToolQuery, "Danh sách giao dịch, có thể lọc loại và tên danh mục."),
}


_READ_WORDS = re.compile(
    r"\b(?:toi|minh|em|da|vua|co|cho|ve|cua|trong|vao|la|va|giup|"
    r"nhung|cac|tat ca|khoan|gi|nao|bao nhieu|bang|con|lai|du|"
    r"xem|liet ke|giao dich|thu|nhap|chi|tieu|tien|tong|danh muc|"
    r"ngan sach|han muc|dung|phan tram|ky|nhom)\b|[\s,?.!]"
)


def simple_read(message: str, categories: list[str]) -> ToolCall | None:
    text = folded(message)
    if not CALENDAR_LITERAL.search(text) or not re.search(r"\b(?:liet ke|xem|gi|nao|bao nhieu|tong)\b", text):
        return None
    words = CALENDAR_LITERAL.sub(" ky ", text)
    words = re.sub(r"\bkhong(?=[?.! ]*$)", "", words)
    matches = [name for name in categories if re.search(rf"\b{re.escape(folded(name))}\b", words)]
    if len(matches) > 1:
        return None
    category = matches[0] if matches else None
    if category:
        words = re.sub(rf"\b{re.escape(folded(category))}\b", "nhom", words)

    if _READ_WORDS.sub("", words):
        return None
    args = {"category": category} if category else {}
    if re.search(r"\b(?:ngan sach|han muc)\b", words):
        return ToolCall("get_budget_status", args)
    if re.search(r"\b(?:liet ke|giao dich|(?:nhung |cac )?(?:khoan )?(?:gi|nao))\b", words):
        if re.search(r"\b(?:thu|nhap)\b", words) and re.search(r"\b(?:chi|tieu)\b", words):
            return None
        if re.search(r"\b(?:chi|tieu)\b", words):
            args["type"] = "EXPENSE"
        elif re.search(r"\b(?:thu|nhap)\b", words):
            args["type"] = "INCOME"
        return ToolCall("list_transactions", args)
    if re.search(r"\b(?:thu|chi|tieu)\b", words) and re.search(r"\b(?:bao nhieu|tong)\b", words):
        if category:
            return ToolCall("get_spending_by_category", args) if re.search(r"\b(?:chi|tieu)\b", words) else None
        return ToolCall("get_financial_summary", {})
    return None


def tool_definitions() -> list[dict]:
    tools = []
    for name, (schema, description) in READ_TOOLS.items():
        tools.append({
            "type": "function",
            "function": {"name": name, "description": description, "parameters": schema.model_json_schema()},
        })
    return tools


def execute_read(tools: FinancialTools, call: ToolCall) -> tuple[FinancialData, str]:
    if call.name not in READ_TOOLS:
        raise AgentProblem("INVALID_TOOL_CALL", "AI đã chọn công cụ hoặc bộ lọc không được phép.")
    schema, _ = READ_TOOLS[call.name]
    try:
        query = schema.model_validate(call.arguments)
    except ValidationError:
        raise AgentProblem("INVALID_TOOL_ARGUMENTS", "Bộ lọc thống kê chưa hợp lệ.") from None

    if isinstance(query, BudgetStatusQuery):
        today = local_today()
        period = f"Ngân sách tháng {query.month or today.month:02d}/{query.year or today.year}.\n"
    elif query.start_date and query.end_date:
        period = f"Kỳ thống kê {query.start_date:%d/%m/%Y} – {query.end_date:%d/%m/%Y}.\n"
    elif query.start_date:
        period = f"Từ ngày {query.start_date:%d/%m/%Y}.\n"
    elif query.end_date:
        period = f"Đến hết ngày {query.end_date:%d/%m/%Y}.\n"
    else:
        period = "Thống kê toàn bộ thời gian.\n"

    if call.name == "get_financial_summary":
        summary = tools.get_financial_summary(query)
        message = (
            f"Tổng thu {money(summary.total_income)}, tổng chi {money(summary.total_expense)}, "
            f"dòng tiền ròng {money(summary.net_cash_flow)}."
        )
        return summary, period + message

    category_type = query.type if isinstance(query, TransactionToolQuery) else TransactionType.EXPENSE
    category_id = None
    if query.category is not None:
        category_id = match_category(tools.list_categories(category_type), query.category).id
    if call.name == "get_spending_by_category":
        spending = tools.get_spending_by_category(DateRange(start_date=query.start_date, end_date=query.end_date))
        rows = [item for item in spending if category_id is None or item.category_id == category_id]
        rows = rows[:query.limit]
        parts = [f"{item.category_name} · {money(item.total_expense)}" for item in rows]
        return rows, period + ("\n".join(parts) if parts else "Không có khoản chi trong phạm vi đã chọn.")
    if call.name == "get_budget_status":
        budgets = tools.get_budget_status(BudgetQuery(**query.model_dump(exclude={"category"})))
        rows = [item for item in budgets if category_id is None or item.category_id == category_id]
        parts = [
            f"{item.category_name} đã dùng {money(item.spent)} trên {money(item.amount)} "
            f"({item.usage_percent:g}%), còn {money(item.remaining)}."
            for item in rows
        ]
        return rows, period + ("\n".join(parts) if parts else "Không có ngân sách trong phạm vi đã chọn.")
    page = tools.list_transactions(
        TransactionQuery(**query.model_dump(exclude={"category"}), category_id=category_id)
    )
    return page, period + f"Tìm thấy {page.total} giao dịch. Đang hiển thị {len(page.items)} giao dịch ở trang {page.page}."
