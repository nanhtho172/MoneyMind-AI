from sqlalchemy import select
from sqlalchemy.orm import Session

from backend.app.models.finance import User


def find_user_by_username(session: Session, username: str) -> User | None:
    return session.scalar(select(User).where(User.username == username))


def find_user_by_id(session: Session, user_id: int) -> User | None:
    return session.get(User, user_id)
