from pydantic import BaseModel, ConfigDict, Field

from backend.app.schemas.common import InputModel, StoredUTC


class HealthResponse(BaseModel):
    status: str


class LoginRequest(InputModel):
    username: str = Field(min_length=1, max_length=64)
    password: str = Field(min_length=1, max_length=256)


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"


class UserView(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    username: str
    created_at: StoredUTC
    can_manage_knowledge: bool = False
