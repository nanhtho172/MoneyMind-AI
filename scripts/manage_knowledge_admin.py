import argparse

from sqlalchemy.orm import Session

from backend.app.core.config import Settings
from backend.app.core.database import make_engine, migrate_knowledge_schema
from backend.app.models.knowledge import KnowledgeAdmin
from backend.app.repositories.users import find_user_by_username


def main() -> int:
    parser = argparse.ArgumentParser(description="Apply the knowledge migration and manage existing users' grants.")
    parser.add_argument("action", choices=["migrate", "grant", "revoke"])
    parser.add_argument("username", nargs="?")
    args = parser.parse_args()
    if args.action != "migrate" and not args.username:
        parser.error("grant and revoke require an existing username")

    engine = make_engine(Settings().database_url)
    try:
        migrate_knowledge_schema(engine)
        if args.action != "migrate":
            with Session(engine) as session, session.begin():
                user = find_user_by_username(session, args.username)
                if user is None:
                    print("User not found. Seed or create the user first.")
                    return 1
                grant = session.get(KnowledgeAdmin, user.id)
                if args.action == "grant" and grant is None:
                    session.add(KnowledgeAdmin(user_id=user.id))
                if args.action == "revoke" and grant is not None:
                    session.delete(grant)
    finally:
        engine.dispose()
    print("Knowledge administration updated.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
