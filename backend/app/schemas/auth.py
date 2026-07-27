from pydantic import BaseModel, EmailStr, Field, field_validator

from app.models.entities import Role, VerifyStatus
from app.schemas.common import ORMModel


class LoginIn(BaseModel):
    """username 字段可传用户名或邮箱。"""

    username: str = Field(min_length=1, max_length=128, description="用户名或邮箱")
    password: str


class RegisterIn(BaseModel):
    email: EmailStr
    password: str = Field(min_length=6, max_length=64)
    display_name: str = Field(default="", max_length=64)
    phone: str | None = Field(default=None, max_length=20)
    # 可选；不填则用邮箱 @ 前缀生成唯一用户名
    username: str | None = Field(default=None, max_length=64)

    @field_validator("email")
    @classmethod
    def normalize_email(cls, v: EmailStr) -> str:
        return str(v).strip().lower()


class AccountOut(ORMModel):
    id: str
    username: str
    email: str | None = None
    role: Role
    display_name: str
    phone: str | None
    is_active: bool
    merchant_id: str | None
    verify_status: VerifyStatus | None = None


class CreateMerchantAccountIn(BaseModel):
    username: str = Field(min_length=3, max_length=64)
    password: str = Field(min_length=6, max_length=64)
    display_name: str = ""
    merchant_id: str
    email: EmailStr | None = None


class CreateIssueAdminIn(BaseModel):
    username: str = Field(min_length=3, max_length=64)
    password: str = Field(min_length=6, max_length=64)
    display_name: str = ""
    email: EmailStr | None = None


class ChangePasswordIn(BaseModel):
    old_password: str = Field(min_length=1, max_length=64)
    new_password: str = Field(min_length=6, max_length=64)


class ResetPasswordIn(BaseModel):
    new_password: str = Field(min_length=6, max_length=64)


class SetActiveIn(BaseModel):
    is_active: bool


class UpdateEmailIn(BaseModel):
    email: EmailStr

    @field_validator("email")
    @classmethod
    def normalize_email(cls, v: EmailStr) -> str:
        return str(v).strip().lower()
