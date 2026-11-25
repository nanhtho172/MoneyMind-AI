from collections.abc import Iterator
from typing import Annotated

from fastapi import Depends, HTTPException, Request, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from itsdangerous import BadData
from sqlalchemy.orm import Session

from backend.app.core.config import Settings
from backend.app.core.security import read_access_token
from backend.app.models.finance import User
from backend.app.repositories.users import find_user_by_id

bearer = HTTPBearer(auto_error=False)


def get_settings(request: Request) -> Settings:
    return request.app.state.settings


def get_session(request: Request) -> Iterator[Session]:
    with Session(request.app.state.engine) as session:
        yield session


DatabaseSession = Annotated[Session, Depends(get_session)]
AppSettings = Annotated[Settings, Depends(get_settings)]


def unauthorized(detail: str) -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail=detail,
        headers={"WWW-Authenticate": "Bearer"},
    )


def get_current_user(
    session: DatabaseSession,
    settings: AppSettings,
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(bearer)],
) -> User:
    if credentials is None:
        raise unauthorized("Bearer token required")
    try:
        user_id = read_access_token(credentials.credentials, settings)
    except BadData:
        raise unauthorized("Invalid or expired access token") from None
    user = find_user_by_id(session, user_id)
    if user is None:
        raise unauthorized("Invalid access token")
    return user


CurrentUser = Annotated[User, Depends(get_current_user)]
