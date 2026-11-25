from datetime import date

from sqlalchemy.dialects.sqlite import insert
from sqlalchemy.orm import Session

from backend.app.core.calendar import local_today
from backend.app.core.config import Settings
from backend.app.core.database import initialize_database, make_engine
from backend.app.core.security import hash_password
from backend.app.models.finance import Category, TransactionType, User
from backend.app.repositories.finance import find_transaction_by_key
from backend.app.repositories.users import find_user_by_username
from backend.app.schemas.finance import BudgetQuery, BudgetSet, TransactionCreate
from backend.app.services import finance

DEMO_PASSWORD = "demo1234"
CATEGORIES = (
    ("Lương", TransactionType.INCOME),
    ("Thu nhập khác", TransactionType.INCOME),
    ("Ăn uống", TransactionType.EXPENSE),
    ("Đi lại", TransactionType.EXPENSE),
    ("Nhà ở", TransactionType.EXPENSE),
    ("Mua sắm", TransactionType.EXPENSE),
)


def demo_months(today: date) -> list[tuple[int, int]]:
    current = (today.year - 1) * 12 + today.month - 1
    return [
        (index // 12 + 1, index % 12 + 1)
        for index in range(max(0, current - 2), current + 1)
    ]


def seed_demo(settings: Settings) -> None:
    if settings.app_env.lower() not in {"development", "local", "test"}:
        raise ValueError("Demo seed is available only in development, local, or test")

    engine = make_engine(settings.database_url)
    try:
        initialize_database(engine)
        with Session(engine) as session, session.begin():
            seed_data(session, local_today())
    finally:
        engine.dispose()


def seed_data(session: Session, today: date) -> None:
    statement = insert(Category).values(
        [{"name": name, "type": category_type} for name, category_type in CATEGORIES]
    )
    session.execute(statement.on_conflict_do_nothing(index_elements=[Category.name, Category.type]))
    categories = {(item.name, item.type): item.id for item in finance.list_categories(session)}
    food_id = categories["Ăn uống", TransactionType.EXPENSE]

    profiles = (("demo_a", 15_000_000, 850_000), ("demo_b", 18_000_000, 1_050_000))
    salary_id = categories["Lương", TransactionType.INCOME]
    transport_id = categories["Đi lại", TransactionType.EXPENSE]

    for username, salary, food in profiles:
        user = find_user_by_username(session, username)
        if user is None:
            user = User(username=username, password_hash=hash_password(DEMO_PASSWORD))
            session.add(user)
            session.flush()

        samples = (
            ("salary", salary_id, TransactionType.INCOME, salary, 1, "Lương tháng"),
            ("food", food_id, TransactionType.EXPENSE, food, 1, "Chi phí ăn uống"),
            ("transport", transport_id, TransactionType.EXPENSE, 220_000, 8, "Chi phí đi lại"),
        )
        for year, month in demo_months(today):
            for label, category_id, kind, amount, day, note in samples:
                transaction_date = date(year, month, day)
                key = f"seed:v1:{year}-{month:02d}:{label}"
                if transaction_date > today:
                    continue
                if find_transaction_by_key(session, user.id, key) is not None:
                    continue
                finance.create_transaction(
                    session, user.id,
                    TransactionCreate(
                        category_id=category_id, type=kind, amount=amount, note=note,
                        transaction_date=transaction_date, idempotency_key=key,
                    ),
                )

        period = BudgetQuery(year=today.year, month=today.month)
        if all(item.category_id != food_id for item in finance.list_budgets(session, user.id, period)):
            finance.set_budget(
                session, user.id,
                BudgetSet(category_id=food_id, year=today.year, month=today.month, amount=1_000_000),
            )


def main() -> None:
    seed_demo(Settings())
    print("Demo data is ready (demo_a, demo_b).")


if __name__ == "__main__":
    main()
