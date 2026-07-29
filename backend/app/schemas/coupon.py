from datetime import datetime
from decimal import Decimal

from pydantic import BaseModel, Field, field_serializer, field_validator

from app.models.entities import CouponStatus
from app.schemas.common import ORMModel
from app.services.points import quantize_hours


class TemplateCreate(BaseModel):
    name: str = Field(min_length=1, max_length=128)
    description: str = ""
    merchant_id: str
    valid_days: int = Field(default=30, ge=1, le=3650)
    cost_points: Decimal = Field(default=Decimal("0"), ge=0, le=100000, max_digits=12, decimal_places=2)

    @field_validator("cost_points", mode="before")
    @classmethod
    def _cost(cls, v):
        return quantize_hours(v) if v is not None else Decimal("0.00")


class TemplateUpdate(BaseModel):
    name: str | None = None
    description: str | None = None
    valid_days: int | None = Field(default=None, ge=1, le=3650)
    cost_points: Decimal | None = Field(default=None, ge=0, le=100000, max_digits=12, decimal_places=2)
    is_active: bool | None = None

    @field_validator("cost_points", mode="before")
    @classmethod
    def _cost(cls, v):
        if v is None:
            return None
        return quantize_hours(v)


class TemplateOut(ORMModel):
    id: str
    name: str
    description: str
    merchant_id: str
    merchant_name: str | None = None
    valid_days: int
    cost_points: Decimal = Decimal("0.00")
    is_active: bool
    created_at: datetime

    @field_validator("cost_points", mode="before")
    @classmethod
    def _cost(cls, v):
        return quantize_hours(v) if v is not None else Decimal("0.00")

    @field_serializer("cost_points")
    def _ser_cost(self, v: Decimal) -> float:
        return float(quantize_hours(v) if v is not None else Decimal("0.00"))


class LiveCodeOut(BaseModel):
    coupon_id: str
    live_code: str
    expires_in: int
    expires_at: datetime
    permanent_code: str
    template_name: str | None = None
    merchant_name: str | None = None


class IssueCouponIn(BaseModel):
    user_id: str
    template_id: str
    quantity: int = Field(default=1, ge=1, le=50)


class BatchIssueCouponIn(BaseModel):
    user_ids: list[str] = Field(min_length=1, max_length=100)
    template_id: str
    quantity: int = Field(default=1, ge=1, le=10)


class VoidCouponIn(BaseModel):
    reason: str = ""


class CouponOut(ORMModel):
    id: str
    code: str
    user_id: str
    username: str | None = None
    template_id: str
    template_name: str | None = None
    merchant_id: str
    merchant_name: str | None = None
    status: CouponStatus
    issued_by: str
    issued_at: datetime
    expires_at: datetime
    redeemed_by: str | None
    redeemed_at: datetime | None
    void_reason: str


class BatchIssueResult(BaseModel):
    issued: list[CouponOut]
    failed: list[dict]


class RedeemIn(BaseModel):
    code: str = Field(min_length=4, max_length=4096)


class RedeemOut(BaseModel):
    message: str
    coupon: CouponOut


class RedemptionLogOut(ORMModel):
    id: str
    coupon_id: str | None
    merchant_id: str
    merchant_name: str | None = None
    operator_id: str
    operator_name: str | None = None
    user_id: str | None
    username: str | None = None
    code: str
    result: str
    message: str
    created_at: datetime


class AuditLogOut(ORMModel):
    id: str
    actor_id: str | None
    actor_name: str | None = None
    action: str
    target_type: str
    target_id: str
    detail: str
    created_at: datetime
