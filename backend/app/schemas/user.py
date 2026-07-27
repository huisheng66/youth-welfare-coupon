from datetime import datetime

from pydantic import BaseModel, Field, field_validator

from app.models.entities import VerifyStatus
from app.schemas.common import ORMModel


class ProfileUpdateIn(BaseModel):
    real_name: str = Field(default="", max_length=64)
    phone: str | None = Field(default=None, max_length=20)
    display_name: str | None = Field(default=None, max_length=64)
    student_no: str = Field(default="", max_length=64, description="学号")
    organization: str = Field(default="", max_length=128)
    remark: str = ""


class BankCardIn(BaseModel):
    """用户自愿绑定银行卡（仅核验通过后）。"""

    card_number: str = Field(min_length=16, max_length=32, description="银行卡号，可含空格")
    bank_name: str = Field(default="", max_length=64, description="开户行，选填")

    @field_validator("card_number")
    @classmethod
    def strip_card(cls, v: str) -> str:
        return (v or "").strip()

    @field_validator("bank_name")
    @classmethod
    def strip_bank(cls, v: str) -> str:
        return (v or "").strip()


class SubmitVerificationIn(BaseModel):
    material_note: str = Field(min_length=1, max_length=2000)


class ReviewVerificationIn(BaseModel):
    approve: bool
    review_note: str = ""


class VerificationOut(ORMModel):
    id: str
    profile_id: str
    material_note: str
    status: VerifyStatus
    reviewer_id: str | None
    review_note: str
    created_at: datetime
    reviewed_at: datetime | None
    # enriched fields for admin review
    user_id: str | None = None
    username: str | None = None
    real_name: str | None = None
    phone: str | None = None
    organization: str | None = None


class UserListItem(ORMModel):
    id: str
    username: str
    display_name: str
    phone: str | None
    real_name: str
    organization: str
    verify_status: VerifyStatus
    created_at: datetime
    student_no: str | None = None
    remark: str | None = None
    latest_material_note: str | None = None
    # 银行卡：仅脱敏，不含完整号
    bank_card_bound: bool = False
    bank_card_masked: str | None = None
    bank_card_bank_name: str | None = None
    bank_card_bound_at: datetime | None = None


class BankCardPlainOut(BaseModel):
    """仅超级管理员解密查看完整卡号（写审计）。"""

    user_id: str
    card_number: str
    bank_card_masked: str
    bank_name: str = ""


class BatchReviewIn(BaseModel):
    verification_ids: list[str] = Field(min_length=1, max_length=100)
    approve: bool
    review_note: str = ""
