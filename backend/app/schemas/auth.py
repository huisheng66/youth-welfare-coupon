from pydantic import BaseModel, Field

from app.models.entities import Role, VerifyStatus
from app.schemas.common import ORMModel


class LoginIn(BaseModel):
    username: str
    password: str


class RegisterIn(BaseModel):
    username: str = Field(min_length=3, max_length=64)
    password: str = Field(min_length=6, max_length=64)
    display_name: str = Field(default="", max_length=64)
    phone: str | None = Field(default=None, max_length=20)


class AccountOut(ORMModel):
    id: str
    username: str
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


class CreateIssueAdminIn(BaseModel):
    username: str = Field(min_length=3, max_length=64)
    password: str = Field(min_length=6, max_length=64)
    display_name: str = ""


class ChangePasswordIn(BaseModel):
    old_password: str = Field(min_length=1, max_length=64)
    new_password: str = Field(min_length=6, max_length=64)


class ResetPasswordIn(BaseModel):
    new_password: str = Field(min_length=6, max_length=64)


class SetActiveIn(BaseModel):
    is_active: bool
