from datetime import datetime
from typing import Generic, TypeVar

from pydantic import BaseModel, ConfigDict

T = TypeVar("T")


class ORMModel(BaseModel):
    model_config = ConfigDict(from_attributes=True)


class MessageOut(BaseModel):
    message: str


class TokenOut(BaseModel):
    # 生产可为空字符串：会话仅靠 HttpOnly Cookie，避免 body 泄露 JWT
    access_token: str = ""
    token_type: str = "bearer"


class Page(BaseModel, Generic[T]):
    total: int
    items: list[T]


class DashboardActivityItem(BaseModel):
    time: datetime | None = None
    kind: str
    title: str
    detail: str = ""


class DashboardOut(BaseModel):
    users: int
    pending_verifications: int
    merchants: int
    coupons_issued: int
    coupons_used: int
    templates: int
    unused_coupons: int = 0
    approved_users: int = 0
    today_redemptions: int = 0
    today_issued: int = 0
    expired_coupons: int = 0
    recent_activity: list[DashboardActivityItem] = []


class MerchantDashboardOut(BaseModel):
    merchant_id: str
    merchant_name: str
    today_success: int
    total_success: int
    unused_for_store: int
    used_for_store: int
