from sqlalchemy.orm import Session

from backend.app.schemas.finance import (
    BudgetQuery, BudgetStatus, BudgetView, CategorySpending, CategoryView, DateRange,
    FinancialSummary, TransactionPage, TransactionQuery,
)
from backend.app.models.finance import TransactionType
from backend.app.services import finance


class FinancialTools:
    """Bind a caller-owned session and a user ID from trusted application context."""

    def __init__(self, session: Session, *, authenticated_user_id: int):
        self._session = session
        self._user_id = authenticated_user_id

    def list_categories(self, category_type: TransactionType | None = None) -> list[CategoryView]:
        return finance.list_categories(self._session, category_type)

    def list_transactions(self, query: TransactionQuery) -> TransactionPage:
        return finance.list_transactions(self._session, self._user_id, query)

    def get_financial_summary(self, period: DateRange) -> FinancialSummary:
        return finance.get_financial_summary(self._session, self._user_id, period)

    def get_spending_by_category(self, period: DateRange) -> list[CategorySpending]:
        return finance.get_spending_by_category(self._session, self._user_id, period)

    def list_budgets(self, query: BudgetQuery) -> list[BudgetView]:
        return finance.list_budgets(self._session, self._user_id, query)

    def get_budget_status(self, query: BudgetQuery) -> list[BudgetStatus]:
        return finance.get_budget_status(self._session, self._user_id, query)
