from pydantic import BaseModel, EmailStr, Field, field_validator

from app.models.entities import EmailCodePurpose, Role, VerifyStatus
from app.schemas.common import ORMModel
from app.services.sanitize import sanitize_plain_text, validate_password_strength


class LoginIn(BaseModel):
    """username 字段可传用户名或邮箱。"""

    username: str = Field(min_length=1, max_length=128, description="用户名或邮箱")
    password: str


class RegisterIn(BaseModel):
    email: EmailStr
    password: str = Field(min_length=8, max_length=64)
    code: str = Field(min_length=4, max_length=16, description="邮箱验证码")
    display_name: str = Field(default="", max_length=64)
    phone: str | None = Field(default=None, max_length=20)
    # 可选；不填则用邮箱 @ 前缀生成唯一用户名
    username: str | None = Field(default=None, max_length=64)

    @field_validator("email")
    @classmethod
    def normalize_email(cls, v: EmailStr) -> str:
        return str(v).strip().lower()

    @field_validator("code")
    @classmethod
    def strip_code(cls, v: str) -> str:
        return v.strip()

    @field_validator("password")
    @classmethod
    def check_password(cls, v: str) -> str:
        return validate_password_strength(v, min_length=8)

    @field_validator("display_name")
    @classmethod
    def clean_display_name(cls, v: str) -> str:
        return sanitize_plain_text(v, max_length=64)

    @field_validator("username")
    @classmethod
    def clean_username(cls, v: str | None) -> str | None:
        if v is None:
            return None
        s = sanitize_plain_text(v, max_length=64)
        return s or None


class SendEmailCodeIn(BaseModel):
    email: EmailStr
    purpose: EmailCodePurpose = EmailCodePurpose.register

    @field_validator("email")
    @classmethod
    def normalize_email(cls, v: EmailStr) -> str:
        return str(v).strip().lower()


class SendEmailCodeOut(BaseModel):
    message: str
    expire_minutes: int
    # 仅未配置 SMTP 且 mail_console=true 时返回，便于本地联调
    debug_code: str | None = None


class ForgotPasswordIn(BaseModel):
    email: EmailStr

    @field_validator("email")
    @classmethod
    def normalize_email(cls, v: EmailStr) -> str:
        return str(v).strip().lower()


class ResetPasswordByEmailIn(BaseModel):
    email: EmailStr
    code: str = Field(min_length=4, max_length=16)
    new_password: str = Field(min_length=8, max_length=64)

    @field_validator("email")
    @classmethod
    def normalize_email(cls, v: EmailStr) -> str:
        return str(v).strip().lower()

    @field_validator("code")
    @classmethod
    def strip_code(cls, v: str) -> str:
        return v.strip()

    @field_validator("new_password")
    @classmethod
    def check_password(cls, v: str) -> str:
        return validate_password_strength(v, min_length=8)


class TestSmtpIn(BaseModel):
    """超级管理员：向指定邮箱发一封连通测试信。"""

    to: EmailStr

    @field_validator("to")
    @classmethod
    def normalize_to(cls, v: EmailStr) -> str:
        return str(v).strip().lower()


class SmtpStatusOut(BaseModel):
    smtp_configured: bool
    mail_server: str = ""
    mail_port: int = 0
    mail_username: str = ""
    mail_from: str = ""
    mail_ssl_tls: bool = False
    mail_starttls: bool = False
    mail_console: bool = True
    # IMAP 收信配置（与 SMTP 共用账号密码）
    imap_configured: bool = False
    imap_server: str = ""
    imap_port: int = 0
    imap_ssl: bool = True


class AccountOut(ORMModel):
    id: str
    username: str
    email: str | None = None
    role: Role
    display_name: str
    phone: str | None
    is_active: bool
    # 登录后须先改密（导入账号 / 管理员重置 / 新建管理账号）
    must_change_password: bool = False
    merchant_id: str | None
    verify_status: VerifyStatus | None = None


def _clean_account_username(v: str) -> str:
    s = sanitize_plain_text((v or "").strip(), max_length=64, strip_angles=True)
    if len(s) < 3:
        raise ValueError("用户名至少 3 个字符")
    if len(s) > 64:
        raise ValueError("用户名过长")
    return s


def _empty_email_to_none(v: object) -> object:
    """表单常传 email:''，转为 None，避免 EmailStr 422。"""
    if v is None:
        return None
    if isinstance(v, str) and not v.strip():
        return None
    return v


class CreateMerchantAccountIn(BaseModel):
    username: str = Field(min_length=1, max_length=64)
    password: str = Field(min_length=1, max_length=64)
    display_name: str = ""
    merchant_id: str = Field(min_length=1, description="商家 ID")
    email: EmailStr | None = None

    @field_validator("email", mode="before")
    @classmethod
    def empty_email(cls, v: object) -> object:
        return _empty_email_to_none(v)

    @field_validator("username")
    @classmethod
    def clean_username(cls, v: str) -> str:
        return _clean_account_username(v)

    @field_validator("password")
    @classmethod
    def check_password(cls, v: str) -> str:
        return validate_password_strength(v, min_length=8)

    @field_validator("display_name")
    @classmethod
    def clean_display_name(cls, v: str) -> str:
        return sanitize_plain_text(v, max_length=64)

    @field_validator("merchant_id")
    @classmethod
    def clean_merchant_id(cls, v: str) -> str:
        s = (v or "").strip()
        if not s:
            raise ValueError("请选择商家")
        return s


class CreateIssueAdminIn(BaseModel):
    username: str = Field(min_length=1, max_length=64)
    password: str = Field(min_length=1, max_length=64)
    display_name: str = ""
    email: EmailStr | None = None

    @field_validator("email", mode="before")
    @classmethod
    def empty_email(cls, v: object) -> object:
        return _empty_email_to_none(v)

    @field_validator("username")
    @classmethod
    def clean_username(cls, v: str) -> str:
        return _clean_account_username(v)

    @field_validator("password")
    @classmethod
    def check_password(cls, v: str) -> str:
        return validate_password_strength(v, min_length=8)

    @field_validator("display_name")
    @classmethod
    def clean_display_name(cls, v: str) -> str:
        return sanitize_plain_text(v, max_length=64)


class ChangePasswordIn(BaseModel):
    old_password: str = Field(min_length=1, max_length=64)
    new_password: str = Field(min_length=8, max_length=64)

    @field_validator("new_password")
    @classmethod
    def check_password(cls, v: str) -> str:
        return validate_password_strength(v, min_length=8)


class ResetPasswordIn(BaseModel):
    new_password: str = Field(min_length=8, max_length=64)

    @field_validator("new_password")
    @classmethod
    def check_password(cls, v: str) -> str:
        return validate_password_strength(v, min_length=8)


class SetActiveIn(BaseModel):
    is_active: bool


class UpdateEmailIn(BaseModel):
    email: EmailStr
    code: str = Field(min_length=4, max_length=16, description="邮箱验证码")

    @field_validator("email")
    @classmethod
    def normalize_email(cls, v: EmailStr) -> str:
        return str(v).strip().lower()

    @field_validator("code")
    @classmethod
    def strip_code(cls, v: str) -> str:
        return v.strip()
