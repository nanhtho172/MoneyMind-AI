from datetime import date

from sqlalchemy import func, select
from sqlalchemy.dialects.sqlite import insert
from sqlalchemy.orm import Session

from backend.app.models.finance import Budget, Category, Transaction, TransactionType
from backend.app.schemas.finance import BudgetSet, DateRange, TransactionCreate, TransactionQuery


def find_category(session: Session, category_id: int) -> Category | None:
    return session.get(Category, category_id)


def list_categories(session: Session, category_type: TransactionType | None):
    statement = select(Category).order_by(Category.name, Category.id)
    if category_type is not None:
        statement = statement.where(Category.type == category_type)
    return session.scalars(statement).all()


def insert_transaction(
    session: Session, user_id: int, data: TransactionCreate, transaction_date: date
) -> Transaction | None:
    statement = insert(Transaction).values(
        **data.model_dump(exclude={"transaction_date"}),
        user_id=user_id,
        transaction_date=transaction_date,
    )
    if data.idempotency_key is not None:
        statement = statement.on_conflict_do_nothing(
            index_elements=[Transaction.user_id, Transaction.idempotency_key]
        )
    return session.scalar(statement.returning(Transaction))


def find_transaction_by_key(session: Session, user_id: int, key: str) -> Transaction | None:
    return session.scalar(
        select(Transaction).where(
            Transaction.user_id == user_id, Transaction.idempotency_key == key
        )
    )


def _transaction_filters(user_id: int, period: DateRange):
    filters = [Transaction.user_id == user_id, Transaction.deleted_at.is_(None)]
    if period.start_date is not None:
        filters.append(Transaction.transaction_date >= period.start_date)
    if period.end_date is not None:
        filters.append(Transaction.transaction_date <= period.end_date)
    return filters


def list_transactions(session: Session, user_id: int, query: TransactionQuery):
    filters = _transaction_filters(user_id, query)
    if query.type is not None:
        filters.append(Transaction.type == query.type)
    if query.category_id is not None:
        filters.append(Transaction.category_id == query.category_id)
    total = session.scalar(select(func.count()).select_from(Transaction).where(*filters))
    statement = (
        select(Transaction)
        .where(*filters)
        .order_by(Transaction.transaction_date.desc(), Transaction.id.desc())
        .offset((query.page - 1) * query.page_size)
        .limit(query.page_size)
    )
    return session.scalars(statement).all(), total


def transaction_amounts(session: Session, user_id: int, period: DateRange):
    statement = (
        select(Transaction.type, Transaction.amount)
        .where(*_transaction_filters(user_id, period))
        .execution_options(yield_per=500)
    )
    return session.execute(statement)


def expense_amounts(session: Session, user_id: int, period: DateRange):
    statement = (
        select(Transaction.category_id, Category.name, Transaction.amount)
        .join(Category, Transaction.category_id == Category.id)
        .where(*_transaction_filters(user_id, period), Transaction.type == TransactionType.EXPENSE)
        .execution_options(yield_per=500)
    )
    return session.execute(statement)


def upsert_budget(session: Session, user_id: int, data: BudgetSet) -> Budget:
    statement = insert(Budget).values(**data.model_dump(), user_id=user_id)
    statement = statement.on_conflict_do_update(
        index_elements=[Budget.user_id, Budget.category_id, Budget.year, Budget.month],
        set_={"amount": statement.excluded.amount},
    )
    return session.scalars(
        statement.returning(Budget), execution_options={"populate_existing": True}
    ).one()


def list_budgets(session: Session, user_id: int, year: int, month: int):
    statement = (
        select(Budget, Category.name)
        .join(Category, Budget.category_id == Category.id)
        .where(Budget.user_id == user_id, Budget.year == year, Budget.month == month)
        .order_by(Category.name, Budget.id)
    )
    return session.execute(statement).all()
