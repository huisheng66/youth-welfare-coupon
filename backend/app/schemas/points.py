from datetime import datetime
from decimal import Decimal

from pydantic import BaseModel, Field, field_serializer, field_validator

from app.schemas.common import ORMModel
from app.schemas.coupon import CouponOut, TemplateOut
from app.services.points import quantize_hours


def _as_float_hours(v) -> float:
    return float(quantize_hours(v))


class PointAccountOut(BaseModel):
    user_id: str
    balance: Decimal
    updated_at: datetime | None = None

    @field_validator("balance", mode="before")
    @classmethod
    def _bal(cls, v):
        return quantize_hours(v)

    @field_serializer("balance")
    def _ser_bal(self, v: Decimal) -> float:
        return _as_float_hours(v)


class PointLedgerOut(ORMModel):
    id: str
    user_id: str
    change: Decimal
    balance_after: Decimal
    reason: str
    operator_id: str | None
    ref_type: str
    ref_id: str
    created_at: datetime

    @field_validator("change", "balance_after", mode="before")
    @classmethod
    def _hours(cls, v):
        return quantize_hours(v)

    @field_serializer("change", "balance_after")
    def _ser_hours(self, v: Decimal) -> float:
        return _as_float_hours(v)


class GrantPointsIn(BaseModel):
    user_id: str
    # 正数入账，负数扣减（调整）；支持两位小数
    amount: Decimal = Field(ge=-100000, le=100000, max_digits=12, decimal_places=2)
    reason: str = Field(default="志愿服务时长入账", max_length=255)

    @field_validator("amount", mode="before")
    @classmethod
    def _amount(cls, v):
        d = quantize_hours(v)
        if d == 0:
            raise ValueError("时长不能为 0")
        return d


class BatchGrantPointsIn(BaseModel):
    user_ids: list[str] = Field(min_length=1, max_length=100)
    amount: Decimal = Field(ge=-100000, le=100000, max_digits=12, decimal_places=2)
    reason: str = Field(default="志愿服务时长入账", max_length=255)

    @field_validator("amount", mode="before")
    @classmethod
    def _amount(cls, v):
        d = quantize_hours(v)
        if d == 0:
            raise ValueError("时长不能为 0")
        return d


class ExchangeIn(BaseModel):
    template_id: str


class ExchangeOut(BaseModel):
    message: str
    balance: Decimal
    coupon: CouponOut

    @field_validator("balance", mode="before")
    @classmethod
    def _bal(cls, v):
        return quantize_hours(v)

    @field_serializer("balance")
    def _ser_bal(self, v: Decimal) -> float:
        return _as_float_hours(v)


class CatalogItem(TemplateOut):
    pass
