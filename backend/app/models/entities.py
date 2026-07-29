import enum
import uuid
from datetime import datetime, timezone

from decimal import Decimal

from sqlalchemy import Boolean, DateTime, Enum, ForeignKey, Integer, Numeric, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def new_id() -> str:
    return str(uuid.uuid4())


def _str_enum(enum_cls: type[enum.Enum]):
    """VARCHAR 存枚举值，兼容 SQLite / MySQL，避免原生 ENUM 迁移麻烦。"""
    return Enum(
        enum_cls,
        values_callable=lambda obj: [e.value for e in obj],
        native_enum=False,
        length=32,
    )


class Role(str, enum.Enum):
    super_admin = "super_admin"
    issue_admin = "issue_admin"
    merchant = "merchant"
    user = "user"


class VerifyStatus(str, enum.Enum):
    draft = "draft"
    pending = "pending"
    approved = "approved"
    rejected = "rejected"


class CouponStatus(str, enum.Enum):
    unused = "unused"
    used = "used"
    void = "void"
    expired = "expired"


class Account(Base):
    __tablename__ = "accounts"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    username: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    email: Mapped[str | None] = mapped_column(String(128), unique=True, nullable=True, index=True)
    password_hash: Mapped[str] = mapped_column(String(255))
    role: Mapped[Role] = mapped_column(_str_enum(Role), index=True)
    display_name: Mapped[str] = mapped_column(String(64), default="")
    phone: Mapped[str | None] = mapped_column(String(20), unique=True, nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    merchant_id: Mapped[str | None] = mapped_column(String(36), ForeignKey("merchants.id"), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    merchant = relationship("Merchant", back_populates="accounts", foreign_keys=[merchant_id])
    profile = relationship("UserProfile", back_populates="account", uselist=False)
    coupons = relationship("CouponInstance", back_populates="user", foreign_keys="CouponInstance.user_id")


class Merchant(Base):
    __tablename__ = "merchants"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    name: Mapped[str] = mapped_column(String(128), unique=True)
    contact_name: Mapped[str] = mapped_column(String(64), default="")
    contact_phone: Mapped[str] = mapped_column(String(20), default="")
    address: Mapped[str] = mapped_column(String(255), default="")
    description: Mapped[str] = mapped_column(Text, default="")
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    accounts = relationship("Account", back_populates="merchant", foreign_keys="Account.merchant_id")
    templates = relationship("CouponTemplate", back_populates="merchant")


class UserProfile(Base):
    __tablename__ = "user_profiles"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    account_id: Mapped[str] = mapped_column(String(36), ForeignKey("accounts.id"), unique=True)
    real_name: Mapped[str] = mapped_column(String(64), default="")
    student_no: Mapped[str] = mapped_column(String(64), default="")  # 学号
    organization: Mapped[str] = mapped_column(String(128), default="")
    remark: Mapped[str] = mapped_column(Text, default="")
    # 银行卡：仅存 Fernet 密文 + 末四位/脱敏展示字段，明文不落库
    bank_card_encrypted: Mapped[str | None] = mapped_column(Text, nullable=True)
    bank_card_last4: Mapped[str] = mapped_column(String(4), default="")
    bank_card_bank_name: Mapped[str] = mapped_column(String(64), default="")  # 开户行（选填）
    bank_card_bound_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    verify_status: Mapped[VerifyStatus] = mapped_column(_str_enum(VerifyStatus), default=VerifyStatus.draft, index=True)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)

    account = relationship("Account", back_populates="profile")
    verifications = relationship("UserVerification", back_populates="profile", order_by="UserVerification.created_at.desc()")


class UserVerification(Base):
    __tablename__ = "user_verifications"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    profile_id: Mapped[str] = mapped_column(String(36), ForeignKey("user_profiles.id"), index=True)
    material_note: Mapped[str] = mapped_column(Text, default="")
    status: Mapped[VerifyStatus] = mapped_column(_str_enum(VerifyStatus), default=VerifyStatus.pending)
    reviewer_id: Mapped[str | None] = mapped_column(String(36), ForeignKey("accounts.id"), nullable=True)
    review_note: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    reviewed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    profile = relationship("UserProfile", back_populates="verifications")


class CouponTemplate(Base):
    __tablename__ = "coupon_templates"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    name: Mapped[str] = mapped_column(String(128))
    description: Mapped[str] = mapped_column(Text, default="")
    merchant_id: Mapped[str] = mapped_column(String(36), ForeignKey("merchants.id"), index=True)
    valid_days: Mapped[int] = mapped_column(Integer, default=30)
    # 兑换所需志愿服务时长（小时，两位小数）；0=不可兑换
    cost_points: Mapped[Decimal] = mapped_column(Numeric(12, 2), default=Decimal("0.00"))
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    merchant = relationship("Merchant", back_populates="templates")
    instances = relationship("CouponInstance", back_populates="template")


class CouponInstance(Base):
    __tablename__ = "coupon_instances"
    __table_args__ = (UniqueConstraint("code", name="uq_coupon_code"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    code: Mapped[str] = mapped_column(String(32), index=True)
    user_id: Mapped[str] = mapped_column(String(36), ForeignKey("accounts.id"), index=True)
    template_id: Mapped[str] = mapped_column(String(36), ForeignKey("coupon_templates.id"), index=True)
    merchant_id: Mapped[str] = mapped_column(String(36), ForeignKey("merchants.id"), index=True)
    status: Mapped[CouponStatus] = mapped_column(_str_enum(CouponStatus), default=CouponStatus.unused, index=True)
    issued_by: Mapped[str] = mapped_column(String(36), ForeignKey("accounts.id"))
    issued_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    redeemed_by: Mapped[str | None] = mapped_column(String(36), ForeignKey("accounts.id"), nullable=True)
    redeemed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    void_reason: Mapped[str] = mapped_column(String(255), default="")

    user = relationship("Account", back_populates="coupons", foreign_keys=[user_id])
    template = relationship("CouponTemplate", back_populates="instances")
    merchant = relationship("Merchant")


class RedemptionLog(Base):
    __tablename__ = "redemption_logs"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    coupon_id: Mapped[str | None] = mapped_column(String(36), ForeignKey("coupon_instances.id"), nullable=True, index=True)
    merchant_id: Mapped[str] = mapped_column(String(36), ForeignKey("merchants.id"), index=True)
    operator_id: Mapped[str] = mapped_column(String(36), ForeignKey("accounts.id"))
    user_id: Mapped[str | None] = mapped_column(String(36), ForeignKey("accounts.id"), nullable=True)
    code: Mapped[str] = mapped_column(String(32))
    result: Mapped[str] = mapped_column(String(32), default="success")
    message: Mapped[str] = mapped_column(String(255), default="")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class AuditLog(Base):
    __tablename__ = "audit_logs"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    actor_id: Mapped[str | None] = mapped_column(String(36), ForeignKey("accounts.id"), nullable=True)
    action: Mapped[str] = mapped_column(String(64), index=True)
    target_type: Mapped[str] = mapped_column(String(64), default="")
    target_id: Mapped[str] = mapped_column(String(36), default="")
    detail: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class PointAccount(Base):
    """Volunteer service hours / points balance."""

    __tablename__ = "point_accounts"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    user_id: Mapped[str] = mapped_column(String(36), ForeignKey("accounts.id"), unique=True)
    balance: Mapped[Decimal] = mapped_column(Numeric(12, 2), default=Decimal("0.00"))
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)


class PointLedger(Base):
    """Volunteer service hours / points ledger."""

    __tablename__ = "point_ledgers"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    user_id: Mapped[str] = mapped_column(String(36), ForeignKey("accounts.id"), index=True)
    change: Mapped[Decimal] = mapped_column(Numeric(12, 2))
    balance_after: Mapped[Decimal] = mapped_column(Numeric(12, 2), default=Decimal("0.00"))
    reason: Mapped[str] = mapped_column(String(255), default="")
    operator_id: Mapped[str | None] = mapped_column(String(36), ForeignKey("accounts.id"), nullable=True)
    ref_type: Mapped[str] = mapped_column(String(32), default="")
    ref_id: Mapped[str] = mapped_column(String(36), default="")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class EmailCodePurpose(str, enum.Enum):
    register = "register"
    reset_password = "reset_password"
    bind_email = "bind_email"


class EmailCode(Base):
    """One-time email verification codes (register / reset / bind)."""

    __tablename__ = "email_codes"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    email: Mapped[str] = mapped_column(String(128), index=True)
    code: Mapped[str] = mapped_column(String(16))
    purpose: Mapped[EmailCodePurpose] = mapped_column(_str_enum(EmailCodePurpose), index=True)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    attempts: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

