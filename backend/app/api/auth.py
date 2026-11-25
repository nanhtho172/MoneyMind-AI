from fastapi import APIRouter

from backend.app.api.dependencies import AppSettings, CurrentUser, DatabaseSession, unauthorized
from backend.app.core.security import issue_access_token, verify_password
from backend.app.models.knowledge import KnowledgeAdmin
from backend.app.repositories.users import find_user_by_username
from backend.app.schemas.auth import LoginRequest, TokenResponse, UserView

router = APIRouter(prefix="/auth", tags=["Authentication"])


@router.post("/login", responses={401: {"description": "Invalid credentials"}})
def login(data: LoginRequest, session: DatabaseSession, settings: AppSettings) -> TokenResponse:
    user = find_user_by_username(session, data.username)
    if user is None or not verify_password(data.password, user.password_hash):
        raise unauthorized("Invalid username or password")
    return TokenResponse(access_token=issue_access_token(user.id, settings))


@router.get("/me", responses={401: {"description": "Missing or invalid bearer token"}})
def me(user: CurrentUser, session: DatabaseSession) -> UserView:
    can_manage = session.get(KnowledgeAdmin, user.id) is not None
    return UserView.model_validate(user).model_copy(update={"can_manage_knowledge": can_manage})
