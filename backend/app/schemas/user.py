from datetime import datetime

from pydantic import BaseModel, Field, field_validator

from app.models.entities import VerifyStatus
from app.schemas.common import ORMModel
from app.services.sanitize import sanitize_note, sanitize_plain_text


class ProfileUpdateIn(BaseModel):
    real_name: str | None = Field(default=None, max_length=64)
    phone: str | None = Field(default=None, max_length=20)
    display_name: str | None = Field(default=None, max_length=64)
    student_no: str | None = Field(default=None, max_length=64, description="学号")
    organization: str | None = Field(default=None, max_length=128)
    remark: str | None = None

    @field_validator("real_name")
    @classmethod
    def clean_real_name(cls, v: str | None) -> str | None:
        return sanitize_plain_text(v, max_length=64) if v is not None else None

    @field_validator("display_name")
    @classmethod
    def clean_display_name(cls, v: str | None) -> str | None:
        if v is None:
            return None
        return sanitize_plain_text(v, max_length=64)

    @field_validator("student_no")
    @classmethod
    def clean_student_no(cls, v: str | None) -> str | None:
        # 学号：去控制符与尖括号
        return sanitize_plain_text(v, max_length=64) if v is not None else None

    @field_validator("organization")
    @classmethod
    def clean_organization(cls, v: str | None) -> str | None:
        return sanitize_plain_text(v, max_length=128) if v is not None else None

    @field_validator("remark")
    @classmethod
    def clean_remark(cls, v: str | None) -> str | None:
        return sanitize_note(v, max_length=2000) if v is not None else None


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
        return sanitize_plain_text(v or "", max_length=64)


class SubmitVerificationIn(BaseModel):
    material_note: str = Field(min_length=1, max_length=2000)

    @field_validator("material_note")
    @classmethod
    def clean_material(cls, v: str) -> str:
        cleaned = sanitize_note(v, max_length=2000)
        if not cleaned.strip():
            raise ValueError("材料说明不能为空")
        return cleaned


class ReviewVerificationIn(BaseModel):
    approve: bool
    review_note: str = ""

    @field_validator("review_note")
    @classmethod
    def clean_note(cls, v: str) -> str:
        return sanitize_note(v, max_length=2000)


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
    display_name: str | None = None
    real_name: str | None = None
    phone: str | None = None
    student_no: str | None = None
    organization: str | None = None
    remark: str | None = None
    verify_status: VerifyStatus | None = None
    account_created_at: datetime | None = None
    # 仅返回脱敏银行卡信息；完整卡号仍走单独的超管审计接口
    bank_card_bound: bool = False
    bank_card_masked: str | None = None
    bank_card_bank_name: str | None = None
    bank_card_bound_at: datetime | None = None
    reviewer_name: str | None = None


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

    @field_validator("review_note")
    @classmethod
    def clean_note(cls, v: str) -> str:
        return sanitize_note(v, max_length=2000)
