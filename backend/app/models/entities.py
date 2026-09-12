import enum
import uuid
from datetime import datetime, timezone

from decimal import Decimal

from sqlalchemy import Boolean, DateTime, Enum, ForeignKey, Index, Integer, LargeBinary, Numeric, String, Text, UniqueConstraint
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
    # 仅用于核验申请记录：资料更新后旧申请失效，资料状态本身不会是 superseded
    superseded = "superseded"


class VerificationSource(str, enum.Enum):
    user_submit = "user_submit"
    profile_change = "profile_change"
    bulk_import = "bulk_import"
    seed = "seed"
    legacy_unknown = "legacy_unknown"


class CouponStatus(str, enum.Enum):
    unused = "unused"
    used = "used"
    void = "void"
    expired = "expired"


class Account(Base):
    __tablename__ = "accounts"
    __table_args__ = (Index("ix_accounts_role_created_at", "role", "created_at"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    username: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    email: Mapped[str | None] = mapped_column(String(128), unique=True, nullable=True, index=True)
    password_hash: Mapped[str] = mapped_column(String(255))
    role: Mapped[Role] = mapped_column(_str_enum(Role), index=True)
    display_name: Mapped[str] = mapped_column(String(64), default="")
    phone: Mapped[str | None] = mapped_column(String(20), unique=True, nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    # 统一初始密码/管理员重置后须强制改密（导入用户、重置密码、新建管理账号）
    must_change_password: Mapped[bool] = mapped_column(Boolean, default=False)
    # 密码变更时递增；JWT 携带签发版本以立即废止该账号的旧会话。
    session_version: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
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
    # T25 门店详情页：门头照原图入库（MySQL 落 MEDIUMBLOB，SQLite 不限），
    # 经纬度为高德坐标拾取器复制的 GCJ-02 文本；均为空串/NULL 表示未填写
    photo_blob: Mapped[bytes | None] = mapped_column(LargeBinary(16777215), nullable=True)
    photo_content_type: Mapped[str] = mapped_column(String(50), default="")
    photo_updated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    longitude: Mapped[str] = mapped_column(String(32), default="")
    latitude: Mapped[str] = mapped_column(String(32), default="")

    accounts = relationship("Account", back_populates="merchant", foreign_keys="Account.merchant_id")
    templates = relationship("CouponTemplate", back_populates="merchant")

    @property
    def has_photo(self) -> bool:
        return bool(self.photo_blob)


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
    # 身份字段（姓名/学号/组织）每次变更递增；核验申请快照对照此版本
    profile_version: Mapped[int] = mapped_column(Integer, default=1, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)

    account = relationship("Account", back_populates="profile")
    verifications = relationship("UserVerification", back_populates="profile", order_by="UserVerification.created_at.desc()")


class UserVerification(Base):
    __tablename__ = "user_verifications"
    __table_args__ = (
        Index("ix_user_verifications_profile_created_at", "profile_id", "created_at"),
        Index("ix_user_verifications_status_created_at", "status", "created_at"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    profile_id: Mapped[str] = mapped_column(String(36), ForeignKey("user_profiles.id"), index=True)
    material_note: Mapped[str] = mapped_column(Text, default="")
    status: Mapped[VerifyStatus] = mapped_column(_str_enum(VerifyStatus), default=VerifyStatus.pending)
    reviewer_id: Mapped[str | None] = mapped_column(String(36), ForeignKey("accounts.id"), nullable=True)
    review_note: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    reviewed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    # 提交时的身份快照；snapshot_version=0 表示历史未知，不能用当前资料冒充
    snapshot_real_name: Mapped[str] = mapped_column(String(64), default="")
    snapshot_student_no: Mapped[str] = mapped_column(String(64), default="")
    snapshot_organization: Mapped[str] = mapped_column(String(128), default="")
    snapshot_version: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    source: Mapped[VerificationSource] = mapped_column(
        _str_enum(VerificationSource), default=VerificationSource.legacy_unknown
    )

    profile = relationship("UserProfile", back_populates="verifications")
    reviewer = relationship("Account", foreign_keys=[reviewer_id])

    @classmethod
    def from_profile(cls, profile: "UserProfile", **kwargs) -> "UserVerification":
        """用当前资料生成带快照的申请记录。调用前 profile 必须已有主键。"""
        return cls(
            profile_id=profile.id,
            snapshot_real_name=profile.real_name or "",
            snapshot_student_no=profile.student_no or "",
            snapshot_organization=profile.organization or "",
            snapshot_version=profile.profile_version or 1,
            **kwargs,
        )


class CouponTemplate(Base):
    __tablename__ = "coupon_templates"
    __table_args__ = (Index("ix_coupon_templates_merchant_created_at", "merchant_id", "created_at"),)

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
    __table_args__ = (
        UniqueConstraint("code", name="uq_coupon_code"),
        Index("ix_coupon_instances_user_issued_at", "user_id", "issued_at"),
        Index("ix_coupon_instances_merchant_issued_at", "merchant_id", "issued_at"),
        Index("ix_coupon_instances_status_issued_at", "status", "issued_at"),
        Index("ix_coupon_instances_status_expires_at", "status", "expires_at"),
    )

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
    # 发放时的权益快照（T12）：模板名称/描述随后续编辑变化，券面以发放时为准；
    # 历史行为 NULL（无快照），展示回退到模板当前值，不回填伪造历史
    template_name: Mapped[str | None] = mapped_column(String(128), nullable=True)
    template_description: Mapped[str | None] = mapped_column(Text, nullable=True)

    user = relationship("Account", back_populates="coupons", foreign_keys=[user_id])
    template = relationship("CouponTemplate", back_populates="instances")
    merchant = relationship("Merchant")


class RedemptionLog(Base):
    __tablename__ = "redemption_logs"
    __table_args__ = (
        Index("ix_redemption_logs_merchant_created_at", "merchant_id", "created_at"),
        Index("ix_redemption_logs_result_created_at", "result", "created_at"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    coupon_id: Mapped[str | None] = mapped_column(String(36), ForeignKey("coupon_instances.id"), nullable=True, index=True)
    merchant_id: Mapped[str] = mapped_column(String(36), ForeignKey("merchants.id"), index=True)
    operator_id: Mapped[str] = mapped_column(String(36), ForeignKey("accounts.id"))
    user_id: Mapped[str | None] = mapped_column(String(36), ForeignKey("accounts.id"), nullable=True)
    code: Mapped[str] = mapped_column(String(32))
    result: Mapped[str] = mapped_column(String(32), default="success")
    # 稳定失败原因码（already_used / voided / expired / wrong_merchant / ...），
    # 成功记录为 redeemed；历史失败行 reason 为空视为 legacy_unknown
    reason: Mapped[str] = mapped_column(String(32), default="")
    message: Mapped[str] = mapped_column(String(255), default="")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class AuditLog(Base):
    __tablename__ = "audit_logs"
    __table_args__ = (Index("ix_audit_logs_created_at", "created_at"),)

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
    __table_args__ = (Index("ix_point_ledgers_user_created_at", "user_id", "created_at"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    user_id: Mapped[str] = mapped_column(String(36), ForeignKey("accounts.id"), index=True)
    change: Mapped[Decimal] = mapped_column(Numeric(12, 2))
    balance_after: Mapped[Decimal] = mapped_column(Numeric(12, 2), default=Decimal("0.00"))
    reason: Mapped[str] = mapped_column(String(255), default="")
    operator_id: Mapped[str | None] = mapped_column(String(36), ForeignKey("accounts.id"), nullable=True)
    ref_type: Mapped[str] = mapped_column(String(32), default="")
    ref_id: Mapped[str] = mapped_column(String(36), default="")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class IdempotencyRecord(Base):
    """写操作幂等记录（T13）。

    键按 操作者 + 操作类型 + 客户端键 限定范围；只保存请求摘要（SHA-256）与
    结果关联（响应 JSON），不保存敏感原始请求体。仅记录已成功完成的操作；
    默认保留 7 天，由 services.idempotency.sweep_expired 定期清理。
    """

    __tablename__ = "idempotency_keys"
    __table_args__ = (
        UniqueConstraint("actor_id", "action", "key", name="uq_idempotency_scope"),
        Index("ix_idempotency_keys_created_at", "created_at"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    key: Mapped[str] = mapped_column(String(128))
    actor_id: Mapped[str] = mapped_column(String(36), ForeignKey("accounts.id"), index=True)
    action: Mapped[str] = mapped_column(String(48))
    request_hash: Mapped[str] = mapped_column(String(64))
    status: Mapped[str] = mapped_column(String(16), default="completed")
    result_json: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class ImportBatchStatus(str, enum.Enum):
    previewed = "previewed"  # 预检完成，待确认执行
    executing = "executing"  # 执行中（可断点续执）
    completed = "completed"  # 全部行处理完毕


class ImportRowStatus(str, enum.Enum):
    pending = "pending"  # 预检通过，待执行
    precheck_failed = "precheck_failed"  # 预检失败（终态，不进入执行）
    running = "running"  # 已被某个执行者领取
    ok = "ok"
    failed = "failed"  # 执行期失败，可通过再次执行重试


class ImportBatch(Base):
    """统一导入批次（T14）：预检 → 确认执行 → 逐行结果。

    保存类型、操作者、文件摘要、参数、状态与计数；原始文件本身不保留
    （仅 SHA-256 摘要用于执行确认），名单内容以逐行结构化结果形式留档。
    """

    __tablename__ = "import_batches"
    __table_args__ = (
        Index("ix_import_batches_actor_created_at", "actor_id", "created_at"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    kind: Mapped[str] = mapped_column(String(16), index=True)  # users / issue / points
    actor_id: Mapped[str] = mapped_column(String(36), ForeignKey("accounts.id"), index=True)
    filename: Mapped[str] = mapped_column(String(255), default="")
    file_sha256: Mapped[str] = mapped_column(String(64), default="")
    params_json: Mapped[str] = mapped_column(Text, default="{}")
    status: Mapped[ImportBatchStatus] = mapped_column(
        _str_enum(ImportBatchStatus), default=ImportBatchStatus.previewed, index=True
    )
    total: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    succeeded: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    failed: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    message: Mapped[str] = mapped_column(String(255), default="")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    executed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    rows = relationship("ImportRow", back_populates="batch", cascade="all, delete-orphan")


class ImportRow(Base):
    """导入批次逐行结果：预检/执行状态、失败原因与业务对象关联。"""

    __tablename__ = "import_rows"
    __table_args__ = (
        Index("ix_import_rows_batch_row_no", "batch_id", "row_no"),
        Index("ix_import_rows_batch_status", "batch_id", "status"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    batch_id: Mapped[str] = mapped_column(String(36), ForeignKey("import_batches.id"), index=True)
    row_no: Mapped[int] = mapped_column(Integer, nullable=False)
    identifier: Mapped[str] = mapped_column(String(128), default="")
    # 解析后的逻辑字段（users: 姓名/学号/...；issue: identifier；points: identifier/hours/reason）
    payload_json: Mapped[str] = mapped_column(Text, default="{}")
    status: Mapped[ImportRowStatus] = mapped_column(
        _str_enum(ImportRowStatus), default=ImportRowStatus.pending
    )
    reason: Mapped[str] = mapped_column(String(255), default="")
    ref_id: Mapped[str] = mapped_column(String(36), default="")
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)

    batch = relationship("ImportBatch", back_populates="rows")


class OutboxStatus(str, enum.Enum):
    queued = "queued"  # 已排队
    sending = "sending"  # worker 已领取，发送中
    sent = "sent"  # SMTP 已受理（不等于用户已收件）
    failed = "failed"  # 永久失败（达到重试上限），可人工重发


class EmailOutbox(Base):
    """最小邮件 outbox（T15）：与业务事务一起记录待发送任务，worker 异步投递。

    payload 只在 html 字段（邮件内容本身）；状态、错误与日志绝不包含
    初始密码或激活 token 明文。
    """

    __tablename__ = "email_outbox"
    __table_args__ = (
        Index("ix_email_outbox_status_next_retry", "status", "next_retry_at"),
        Index("ix_email_outbox_created_at", "created_at"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    kind: Mapped[str] = mapped_column(String(32), default="")  # activation / import_notify
    to_email: Mapped[str] = mapped_column(String(128), index=True)
    subject: Mapped[str] = mapped_column(String(255), default="")
    html: Mapped[str] = mapped_column(Text, default="")
    ref_type: Mapped[str] = mapped_column(String(32), default="")
    ref_id: Mapped[str] = mapped_column(String(36), default="")
    status: Mapped[OutboxStatus] = mapped_column(_str_enum(OutboxStatus), default=OutboxStatus.queued, index=True)
    attempts: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    max_attempts: Mapped[int] = mapped_column(Integer, default=5, nullable=False)
    next_retry_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    last_error: Mapped[str] = mapped_column(String(255), default="")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    sent_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class ActivationToken(Base):
    """一次性账号激活 token（T15）：只存 HMAC 摘要，单次消费，限期有效。"""

    __tablename__ = "activation_tokens"
    __table_args__ = (Index("ix_activation_tokens_account_created_at", "account_id", "created_at"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    account_id: Mapped[str] = mapped_column(String(36), ForeignKey("accounts.id"), index=True)
    token_hash: Mapped[str] = mapped_column(String(64), unique=True)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class EmailCodePurpose(str, enum.Enum):
    register = "register"
    reset_password = "reset_password"
    bind_email = "bind_email"


class EmailCode(Base):
    """One-time email verification codes (register / reset / bind)."""

    __tablename__ = "email_codes"
    __table_args__ = (Index("ix_email_codes_email_purpose_created_at", "email", "purpose", "created_at"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    email: Mapped[str] = mapped_column(String(128), index=True)
    # 存 HMAC-SHA256 摘要（64 字符），不再是验证码明文；历史明文行迁移后兼容读取
    code: Mapped[str] = mapped_column(String(128))
    purpose: Mapped[EmailCodePurpose] = mapped_column(_str_enum(EmailCodePurpose), index=True)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    attempts: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
