from datetime import date
from enum import StrEnum
from typing import Annotated, Self

from pydantic import BaseModel, ConfigDict, Field, StringConstraints, model_validator

from backend.app.models.finance import TransactionType
from backend.app.schemas.common import InputModel, StoredUTC

Year = Annotated[int, Field(ge=1, le=9999)]
Month = Annotated[int, Field(ge=1, le=12)]
CategoryId = Annotated[int, Field(gt=0, le=2**63 - 1)]
Amount = Annotated[int, Field(strict=True, gt=0, le=2**63 - 1)]


class DateRange(InputModel):
    start_date: date | None = Field(default=None, description="Ngày bắt đầu, tính cả ngày này")
    end_date: date | None = Field(default=None, description="Ngày kết thúc, tính cả ngày này")

    @model_validator(mode="after")
    def validate_order(self) -> Self:
        if self.start_date and self.end_date and self.start_date > self.end_date:
            raise ValueError("start_date must be on or before end_date")
        return self


class TransactionQuery(DateRange):
    category_id: CategoryId | None = None
    type: TransactionType | None = None
    page: int = Field(default=1, ge=1, le=1_000_000)
    page_size: int = Field(default=20, ge=1, le=100)


class CategoryQuery(InputModel):
    type: TransactionType | None = None


class CategoryView(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    name: str
    type: TransactionType


class TransactionCreate(InputModel):
    category_id: CategoryId
    type: TransactionType
    amount: Amount
    note: Annotated[str, Field(max_length=500)] | None = None
    transaction_date: date | None = None
    idempotency_key: Annotated[
        str, StringConstraints(strip_whitespace=True, min_length=1, max_length=128)
    ] | None = None


class TransactionView(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    category_id: int
    type: TransactionType
    amount: int
    note: str | None
    transaction_date: date
    created_at: StoredUTC
    idempotency_key: str | None


class TransactionPage(BaseModel):
    items: list[TransactionView]
    total: int
    page: int
    page_size: int


class FinancialSummary(BaseModel):
    total_income: int
    total_expense: int
    net_cash_flow: int


class CategorySpending(BaseModel):
    category_id: int
    category_name: str
    total_expense: int


class BudgetQuery(InputModel):
    year: Year | None = None
    month: Month | None = None


class BudgetSet(InputModel):
    category_id: CategoryId
    year: Year
    month: Month
    amount: Amount


class BudgetView(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    category_id: int
    year: int
    month: int
    amount: int


class BudgetAlert(StrEnum):
    NORMAL = "NORMAL"
    WARNING = "WARNING"
    EXCEEDED = "EXCEEDED"


class BudgetStatus(BudgetView):
    category_name: str
    spent: int
    remaining: int
    usage_percent: float
    alert: BudgetAlert
