from typing import Annotated

from fastapi import APIRouter, Query, status

from backend.app.api.dependencies import CurrentUser, DatabaseSession
from backend.app.schemas.finance import (
    BudgetQuery, BudgetSet, BudgetStatus, BudgetView, CategoryQuery, CategorySpending,
    CategoryView, DateRange, FinancialSummary, TransactionCreate, TransactionPage,
    TransactionQuery, TransactionView,
)
from backend.app.services import finance

router = APIRouter(responses={401: {"description": "Missing or invalid bearer token"}})


@router.get("/categories", tags=["Categories"])
def categories(
    query: Annotated[CategoryQuery, Query()], session: DatabaseSession, user: CurrentUser
) -> list[CategoryView]:
    return finance.list_categories(session, query.type)


@router.post(
    "/transactions",
    tags=["Transactions"],
    status_code=status.HTTP_201_CREATED,
    responses={
        404: {"description": "Category not found"},
        409: {"description": "Idempotency key is unavailable or has a different payload"},
    },
)
def create_transaction(
    data: TransactionCreate, session: DatabaseSession, user: CurrentUser
) -> TransactionView:
    result = finance.create_transaction(session, user.id, data)
    session.commit()
    return result


@router.get("/transactions", tags=["Transactions"])
def transactions(
    query: Annotated[TransactionQuery, Query()], session: DatabaseSession, user: CurrentUser
) -> TransactionPage:
    return finance.list_transactions(session, user.id, query)


@router.get("/reports/summary", tags=["Reports"])
def financial_summary(
    period: Annotated[DateRange, Query()], session: DatabaseSession, user: CurrentUser
) -> FinancialSummary:
    return finance.get_financial_summary(session, user.id, period)


@router.get("/reports/by-category", tags=["Reports"])
def spending_by_category(
    period: Annotated[DateRange, Query()], session: DatabaseSession, user: CurrentUser
) -> list[CategorySpending]:
    return finance.get_spending_by_category(session, user.id, period)


@router.get("/budgets", tags=["Budgets"])
def budgets(
    query: Annotated[BudgetQuery, Query()], session: DatabaseSession, user: CurrentUser
) -> list[BudgetView]:
    return finance.list_budgets(session, user.id, query)


@router.put(
    "/budgets", tags=["Budgets"], responses={404: {"description": "Category not found"}}
)
def set_budget(data: BudgetSet, session: DatabaseSession, user: CurrentUser) -> BudgetView:
    result = finance.set_budget(session, user.id, data)
    session.commit()
    return result


@router.get("/budgets/status", tags=["Budgets"])
def budget_status(
    query: Annotated[BudgetQuery, Query()], session: DatabaseSession, user: CurrentUser
) -> list[BudgetStatus]:
    return finance.get_budget_status(session, user.id, query)
