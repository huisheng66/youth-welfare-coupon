from datetime import datetime

from pydantic import BaseModel, Field

from app.schemas.common import ORMModel
from app.schemas.coupon import CouponOut, TemplateOut


class PointAccountOut(BaseModel):
    user_id: str
    balance: int
    updated_at: datetime | None = None


class PointLedgerOut(ORMModel):
    id: str
    user_id: str
    change: int
    balance_after: int
    reason: str
    operator_id: str | None
    ref_type: str
    ref_id: str
    created_at: datetime


class GrantPointsIn(BaseModel):
    user_id: str
    # 正数入账，负数扣减（调整）
    amount: int = Field(ne=0, ge=-100000, le=100000)
    reason: str = Field(default="志愿服务时长入账", max_length=255)


class BatchGrantPointsIn(BaseModel):
    user_ids: list[str] = Field(min_length=1, max_length=100)
    amount: int = Field(ne=0, ge=-100000, le=100000)
    reason: str = Field(default="志愿服务时长入账", max_length=255)


class ExchangeIn(BaseModel):
    template_id: str


class ExchangeOut(BaseModel):
    message: str
    balance: int
    coupon: CouponOut


class CatalogItem(TemplateOut):
    pass
