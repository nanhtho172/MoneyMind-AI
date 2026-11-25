from collections import Counter

from sqlalchemy.orm import Session

from backend.app.core.calendar import local_today, month_dates
from backend.app.models.finance import TransactionType
from backend.app.repositories import finance as repository
from backend.app.schemas.finance import (
    BudgetAlert, BudgetQuery, BudgetSet, BudgetStatus, BudgetView, CategorySpending,
    CategoryView, DateRange, FinancialSummary, TransactionCreate, TransactionPage,
    TransactionQuery, TransactionView,
)


class CategoryNotFound(ValueError):
    pass


class CategoryTypeMismatch(ValueError):
    pass


class IdempotencyConflict(ValueError):
    pass


def _require_category(session: Session, category_id: int, category_type: TransactionType) -> None:
    category = repository.find_category(session, category_id)
    if category is None:
        raise CategoryNotFound("Category not found")
    if category.type != category_type:
        raise CategoryTypeMismatch(f"Category must be of type {category_type.value}")


def list_categories(
    session: Session, category_type: TransactionType | None = None
) -> list[CategoryView]:
    return [CategoryView.model_validate(row) for row in repository.list_categories(session, category_type)]


def create_transaction(session: Session, user_id: int, data: TransactionCreate) -> TransactionView:
    _require_category(session, data.category_id, data.type)
    transaction_date = data.transaction_date or local_today()
    transaction = repository.insert_transaction(session, user_id, data, transaction_date)
    if transaction is not None:
        return TransactionView.model_validate(transaction)

    existing = repository.find_transaction_by_key(session, user_id, data.idempotency_key)
    if existing is None or existing.deleted_at is not None:
        raise IdempotencyConflict("Idempotency key is unavailable")
    submitted = data.model_dump(exclude={"idempotency_key"})
    if data.transaction_date is None:
        del submitted["transaction_date"]
    if any(getattr(existing, key) != value for key, value in submitted.items()):
        raise IdempotencyConflict("Idempotency key already belongs to a different transaction")
    return TransactionView.model_validate(existing)


def list_transactions(session: Session, user_id: int, query: TransactionQuery) -> TransactionPage:
    rows, total = repository.list_transactions(session, user_id, query)
    return TransactionPage(
        items=[TransactionView.model_validate(row) for row in rows],
        total=total,
        page=query.page,
        page_size=query.page_size,
    )


def get_financial_summary(session: Session, user_id: int, period: DateRange) -> FinancialSummary:
    totals: Counter[str] = Counter()
    for transaction_type, amount in repository.transaction_amounts(session, user_id, period):
        totals[transaction_type] += amount
    income = totals[TransactionType.INCOME]
    expense = totals[TransactionType.EXPENSE]
    return FinancialSummary(total_income=income, total_expense=expense, net_cash_flow=income - expense)


def get_spending_by_category(
    session: Session, user_id: int, period: DateRange
) -> list[CategorySpending]:
    totals: Counter[tuple[int, str]] = Counter()
    for category_id, name, amount in repository.expense_amounts(session, user_id, period):
        totals[category_id, name] += amount
    return [
        CategorySpending(category_id=category_id, category_name=name, total_expense=amount)
        for (category_id, name), amount in sorted(
            totals.items(), key=lambda item: (-item[1], item[0][1], item[0][0])
        )
    ]


def set_budget(session: Session, user_id: int, data: BudgetSet) -> BudgetView:
    _require_category(session, data.category_id, TransactionType.EXPENSE)
    return BudgetView.model_validate(repository.upsert_budget(session, user_id, data))


def _budget_period(query: BudgetQuery) -> tuple[int, int]:
    today = local_today()
    return query.year or today.year, query.month or today.month


def list_budgets(session: Session, user_id: int, query: BudgetQuery) -> list[BudgetView]:
    year, month = _budget_period(query)
    return [
        BudgetView.model_validate(row)
        for row, _ in repository.list_budgets(session, user_id, year, month)
    ]


def check_budget_alert(spent: int, limit: int) -> BudgetAlert:
    if spent >= limit:
        return BudgetAlert.EXCEEDED
    if spent * 5 >= limit * 4:
        return BudgetAlert.WARNING
    return BudgetAlert.NORMAL


def get_budget_status(session: Session, user_id: int, query: BudgetQuery) -> list[BudgetStatus]:
    year, month = _budget_period(query)
    budgets = repository.list_budgets(session, user_id, year, month)
    if not budgets:
        return []
    start, end = month_dates(year, month)
    period = DateRange(start_date=start, end_date=end)
    spending = {
        item.category_id: item.total_expense
        for item in get_spending_by_category(session, user_id, period)
    }

    statuses = []
    for row, category_name in budgets:
        budget = BudgetView.model_validate(row)
        spent = spending.get(budget.category_id, 0)
        statuses.append(
            BudgetStatus(
                **budget.model_dump(),
                category_name=category_name,
                spent=spent,
                remaining=budget.amount - spent,
                usage_percent=spent * 100 / budget.amount,
                alert=check_budget_alert(spent, budget.amount),
            )
        )
    return statuses
