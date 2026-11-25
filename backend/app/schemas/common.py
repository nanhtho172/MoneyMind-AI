from datetime import UTC, datetime
from typing import Annotated

from pydantic import AfterValidator, BaseModel, ConfigDict

def _as_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)


StoredUTC = Annotated[datetime, AfterValidator(_as_utc)]


class InputModel(BaseModel):
    model_config = ConfigDict(extra="forbid")
