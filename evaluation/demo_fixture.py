"""Create a fresh, disposable MoneyMind demo. All paths and accounts belong to this fixture."""

import argparse
import secrets
from datetime import date
from pathlib import Path

from fastapi.testclient import TestClient
from pydantic import SecretStr
from sqlalchemy.orm import Session

from backend.app.core.config import Settings
from backend.app.core.database import initialize_database, make_engine
from backend.app.core.security import hash_password
from backend.app.main import create_app
from backend.app.models.finance import Category, User
from backend.app.schemas.finance import BudgetSet, TransactionCreate
from backend.app.services import finance
from scripts.seed_demo import CATEGORIES, DEMO_PASSWORD

DOCUMENTS = {
    "phan-bo.md": (
        "# Quy tắc 50/30/20 và quản lý chi tiêu\n"
        "Quy tắc 50/30/20 gợi ý phân bổ 50% thu nhập cho nhu cầu thiết yếu, "
        "30% cho mong muốn và 20% cho tiết kiệm. Để quản lý chi tiêu, hãy xem nhóm chi lớn "
        "nhất trước, rồi chọn một khoản linh hoạt có thể giảm để dành tiền tiết kiệm."
    ),
    "du-phong.md": (
        "# Quỹ dự phòng\nQuỹ dự phòng dùng cho biến cố bất ngờ như mất thu nhập hoặc khám bệnh. "
        "Để bắt đầu, hãy dành riêng một khoản nhỏ đều đặn ở nơi dễ rút khi cần."
    ),
    "chi-khong-deu.md": (
        "# Cân đối các khoản chi không đều trong tháng\n"
        "Với các khoản chi không đều, hãy ước tính tổng chi cả năm và chia thành khoản để dành hàng tháng."
    ),
}
ENTRIES = (
    ("Lương", "INCOME", 12_000_000, 20, "Lương tháng"),
    ("Ăn uống", "EXPENSE", 50_000, 21, "Ăn sáng"),
    ("Đi lại", "EXPENSE", 30_000, 21, "Đi lại"),
    ("Mua sắm", "EXPENSE", 90_000, 22, "Mua sách"),
)


def isolated_settings(directory: Path, *, live: bool = False) -> Settings:
    # Never inherit persistence or tracing destinations from .env.
    return Settings(
        app_env="test",
        database_url=f"sqlite:///{(directory / 'demo.db').as_posix()}",
        auth_secret_key=SecretStr(secrets.token_urlsafe(40)),
        agent_checkpoint_path=directory / "graph.db",
        rag_directory=directory / "chroma",
        rag_upload_directory=directory / "uploads",
        langsmith_tracing=False,
        langsmith_api_key=None,
        **({} if live else {"llm_api_key": SecretStr("offline-demo-placeholder")}),
    )


def login(client, username="demo_a"):
    response = client.post("/api/auth/login", json={"username": username, "password": DEMO_PASSWORD})
    response.raise_for_status()
    return {"Authorization": "Bearer " + response.json()["access_token"]}


def upload(client, headers, filename, content):
    response = client.post(
        "/api/knowledge/documents",
        headers=headers,
        files={"file": (filename, content.encode("utf-8"), "text/markdown")},
    )
    response.raise_for_status()
    return response.json()


def seed(settings, profile="full"):
    engine = make_engine(settings.database_url)
    try:
        initialize_database(engine)
        with Session(engine) as session, session.begin():
            categories = {name: Category(name=name, type=kind) for name, kind in CATEGORIES}
            a, b = (
                User(username=name, password_hash=hash_password(DEMO_PASSWORD))
                for name in ("demo_a", "demo_b")
            )
            session.add_all([a, b, *categories.values()])
            session.flush()
            for name, kind, amount, day, note in ENTRIES:
                if profile == "stage" and name in {"Ăn uống", "Mua sắm"}:
                    continue
                finance.create_transaction(
                    session,
                    a.id,
                    TransactionCreate(
                        type=kind,
                        amount=amount,
                        category_id=categories[name].id,
                        transaction_date=date(2026, 11, day),
                        note=note,
                    ),
                )
            if profile == "full":
                finance.set_budget(
                    session,
                    a.id,
                    BudgetSet(
                        category_id=categories["Ăn uống"].id,
                        year=2026,
                        month=11,
                        amount=200_000,
                    ),
                )
            finance.create_transaction(
                session,
                b.id,
                TransactionCreate(
                    type="EXPENSE",
                    amount=777_777,
                    category_id=categories["Đi lại"].id,
                    transaction_date=date(2026, 11, 21),
                    note="Kiểm tra cách ly",
                ),
            )
    finally:
        engine.dispose()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("directory", type=Path, help="A new directory; existing directories are refused.")
    parser.add_argument("--profile", choices=["stage", "full"], default="stage")
    parser.add_argument(
        "--serve",
        action="store_true",
        help="Serve this new demo on loopback using the configured Groq model.",
    )
    parser.add_argument("--port", type=int, default=8011)
    args = parser.parse_args()
    directory = args.directory.resolve()
    directory.mkdir(parents=True, exist_ok=False)
    settings = isolated_settings(directory)
    seed(settings, args.profile)
    with TestClient(create_app(settings, enable_chat=True)) as client:
        headers = login(client)
        for name, body in DOCUMENTS.items():
            item = upload(client, headers, name, body)
            print(name, item["indexing_status"], item["chunk_count"], item["error_code"] or "")
            if item["indexing_status"] != "ready":
                raise SystemExit("Fixture indexing failed; see the document error above.")
    print(f"Demo ready: {directory} ({args.profile})")
    if args.serve:
        import uvicorn

        uvicorn.run(
            create_app(isolated_settings(directory, live=True), enable_chat=True),
            host="127.0.0.1",
            port=args.port,
            access_log=False,
        )


if __name__ == "__main__":
    main()
