from datetime import UTC, date, datetime
from enum import StrEnum

from sqlalchemy import (
    DDL, CheckConstraint, ForeignKey, ForeignKeyConstraint, Index, String,
    UniqueConstraint, event,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class TransactionType(StrEnum):
    INCOME = "INCOME"
    EXPENSE = "EXPENSE"


def utc_now() -> datetime:
    return datetime.now(UTC).replace(tzinfo=None)


class Base(DeclarativeBase):
    pass


class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(primary_key=True)
    username: Mapped[str] = mapped_column(String(64), unique=True)
    password_hash: Mapped[str] = mapped_column(String(255))
    created_at: Mapped[datetime] = mapped_column(default=utc_now)


class Category(Base):
    __tablename__ = "categories"
    __table_args__ = (
        UniqueConstraint("name", "type"),
        UniqueConstraint("id", "type"),
        CheckConstraint("type IN ('INCOME', 'EXPENSE')"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(100))
    type: Mapped[str] = mapped_column(String(7))


class Transaction(Base):
    __tablename__ = "transactions"
    __table_args__ = (
        ForeignKeyConstraint(["category_id", "type"], ["categories.id", "categories.type"]),
        UniqueConstraint("user_id", "idempotency_key"),
        CheckConstraint("typeof(amount) = 'integer' AND amount > 0"),
        CheckConstraint("type IN ('INCOME', 'EXPENSE')"),
        Index("ix_transactions_user_date", "user_id", "transaction_date", "id"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"))
    category_id: Mapped[int]
    type: Mapped[str] = mapped_column(String(7))
    amount: Mapped[int]
    note: Mapped[str | None] = mapped_column(String(500))
    transaction_date: Mapped[date]
    created_at: Mapped[datetime] = mapped_column(default=utc_now)
    deleted_at: Mapped[datetime | None]
    idempotency_key: Mapped[str | None] = mapped_column(String(128))


class Budget(Base):
    __tablename__ = "budgets"
    __table_args__ = (
        UniqueConstraint("user_id", "category_id", "year", "month"),
        CheckConstraint("typeof(amount) = 'integer' AND amount > 0"),
        CheckConstraint("year BETWEEN 1 AND 9999"),
        CheckConstraint("month BETWEEN 1 AND 12"),
        Index("ix_budgets_user_period", "user_id", "year", "month"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"))
    category_id: Mapped[int] = mapped_column(ForeignKey("categories.id"))
    year: Mapped[int]
    month: Mapped[int]
    amount: Mapped[int]


for operation, trigger in (("INSERT", "insert"), ("UPDATE OF category_id", "update")):
    event.listen(
        Budget.__table__,
        "after_create",
        DDL(f"""
            CREATE TRIGGER budgets_expense_category_{trigger}
            BEFORE {operation} ON budgets
            FOR EACH ROW
            WHEN NOT EXISTS (
                SELECT 1 FROM categories WHERE id = NEW.category_id AND type = 'EXPENSE'
            )
            BEGIN
                SELECT RAISE(ABORT, 'Budget requires an expense category');
            END
        """),
    )

event.listen(
    Budget.__table__,
    "after_create",
    DDL("""
        CREATE TRIGGER categories_preserve_budget_type
        BEFORE UPDATE OF type ON categories
        FOR EACH ROW
        WHEN NEW.type <> 'EXPENSE'
            AND EXISTS (SELECT 1 FROM budgets WHERE category_id = OLD.id)
        BEGIN
            SELECT RAISE(ABORT, 'Category has expense budgets');
        END
    """),
)
