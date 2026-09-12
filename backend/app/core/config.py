import os
from functools import lru_cache
from typing import Literal

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

# env_file 可用 APP_SETTINGS_ENV_FILE 覆盖：测试进程把它指向不存在的路径，
# 显式断开与本地 .env（真实 SMTP/密钥）的 dotenv 回退，保证测试无外部副作用。
_ENV_FILE = os.environ.get("APP_SETTINGS_ENV_FILE") or ".env"

# Known weak / placeholder secrets that must never ship in production
INSECURE_SECRET_KEYS = frozenset(
    {
        "dev-secret-change-me",
        "dev-secret-change-me-in-production",
        "please-change-me-to-a-long-random-string",
        "change-me",
        "secret",
        "secret_key",
    }
)


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=_ENV_FILE, env_file_encoding="utf-8", extra="ignore")

    app_name: str = "youth"
    # development | production — drives secure defaults when explicit flags are omitted
    app_env: Literal["development", "production"] = "development"

    secret_key: str = "dev-secret-change-me-in-production"
    # Separate Fernet key material for field encryption (bank cards). Falls back to secret_key.
    field_encryption_key: str = ""
    # Optional previous key for decrypt during rotation
    field_encryption_key_previous: str = ""
    algorithm: str = "HS256"
    access_token_expire_minutes: int = 60 * 24
    database_url: str = "sqlite:///./data/app.db"
    cors_origins: str = (
        "http://localhost:5173,http://127.0.0.1:5173,"
        "https://localhost:5173,https://127.0.0.1:5173"
    )
    # None = auto: LAN regex only in development
    cors_allow_lan: bool | None = None
    # None = auto: OpenAPI only in development
    openapi_enabled: bool | None = None
    # None = auto: seed demo weak accounts only in development
    seed_demo_accounts: bool | None = None
    # When true, skip production secret-key hard block (tests only)
    allow_insecure_secret: bool = False

    live_code_expire_seconds: int = 30

    # 批量导入（用户名单 / 按名单发券 / 按名单发时长）
    import_max_rows: int = 1000
    # 导入用户的统一初始密码（须 ≥8 位且含字母和数字），管理员在结果页分发并提醒用户修改
    import_initial_password: str = "youth123456"
    # 读取路径过期券扫描节流（秒），0 = 每次列表请求都扫描
    coupon_expire_scan_interval: int = 30
    # 写操作幂等记录保留天数（T13）：短期请求幂等与长期业务批次留档区分
    idempotency_retention_days: int = 7
    # 幂等记录清理节流（秒），进程内复用与过期券扫描相同的节流模式
    idempotency_sweep_interval: int = 300

    # 商家门头照（T25 门店详情页）：原图入库大小上限，需小于 MEDIUMBLOB 的 16MB
    merchant_photo_max_bytes: int = 5 * 1024 * 1024

    # 账号激活链接（T15）：一次性 token 有效期与激活页公开地址
    activation_token_expire_hours: int = 48
    # 邮件中激活链接的公开 base URL（生产必须配置为前端可访问地址）
    public_base_url: str = "http://localhost:5173"
    # 邮件 outbox worker：轮询间隔、单批处理数与重试上限
    outbox_poll_seconds: int = 30
    outbox_batch_size: int = 10
    outbox_max_attempts: int = 5

    # 认证 Cookie：将 JWT 从 localStorage 迁到 HttpOnly Cookie，消除 XSS 窃取 token 的链路
    auth_cookie_name: str = "token"
    # 留空=不设置 Domain（仅当前主机）；跨子域如 api.x.com ↔ www.x.com 可设 ".x.com"
    auth_cookie_domain: str = ""
    # None=auto：生产 Secure=True（仅 HTTPS），开发 Secure=False（允许 http://localhost）
    auth_cookie_secure: bool | None = None
    # lax 覆盖绝大多数 CSRF 场景；strict 会断开外链跳转后的会话
    auth_cookie_samesite: Literal["lax", "strict", "none"] = "lax"
    # 是否仍允许 Authorization: Bearer 头读取 token（过渡期兼容小程序/旧前端，1-2 版本后关闭）
    auth_allow_bearer: bool = True

    # Rate limiting: auto | memory | file | redis
    rate_limit_backend: str = "auto"
    redis_url: str = ""
    rate_limit_file_path: str = "./data/rate_limit.db"
    login_max_fails: int = 8
    login_window_seconds: int = 300
    # Light global IP limit (requests per window); 0 disables
    global_ip_max_requests: int = 300
    global_ip_window_seconds: int = 60

    # SMTP（mail_server 与 mail_password 都填才启用真实发信；否则控制台模式）
    mail_server: str = ""
    mail_port: int = 465
    mail_username: str = ""
    mail_password: str = ""
    mail_from: str = ""
    mail_from_name: str = "youth"
    mail_starttls: bool = False
    mail_ssl_tls: bool = True
    mail_console: bool = True
    email_code_expire_minutes: int = 10
    email_code_cooldown_seconds: int = 60
    email_code_max_per_hour: int = 8

    # IMAP（收信；与 SMTP 共用 MAIL_USERNAME / MAIL_PASSWORD；业务发码不依赖 IMAP）
    imap_server: str = ""
    imap_port: int = 993
    imap_ssl: bool = True

    @field_validator("app_env", mode="before")
    @classmethod
    def normalize_env(cls, v: object) -> str:
        if v is None or v == "":
            return "development"
        s = str(v).strip().lower()
        if s in {"prod", "production"}:
            return "production"
        if s in {"dev", "development", "local", "test"}:
            return "development"
        return s

    @property
    def is_production(self) -> bool:
        return self.app_env == "production"

    @property
    def effective_openapi_enabled(self) -> bool:
        if self.openapi_enabled is not None:
            return self.openapi_enabled
        return not self.is_production

    @property
    def effective_cors_allow_lan(self) -> bool:
        if self.cors_allow_lan is not None:
            return self.cors_allow_lan
        return not self.is_production

    @property
    def effective_seed_demo_accounts(self) -> bool:
        if self.seed_demo_accounts is not None:
            return self.seed_demo_accounts
        return not self.is_production

    @property
    def cors_origin_list(self) -> list[str]:
        return [o.strip() for o in self.cors_origins.split(",") if o.strip()]

    @property
    def field_crypto_key_material(self) -> str:
        """Key material for Fernet derivation; prefer dedicated field key."""
        dedicated = (self.field_encryption_key or "").strip()
        if dedicated:
            return dedicated
        return self.secret_key

    @property
    def using_secret_for_field_crypto(self) -> bool:
        return not (self.field_encryption_key or "").strip()

    @property
    def secret_is_insecure(self) -> bool:
        key = (self.secret_key or "").strip()
        if not key or len(key) < 16:
            return True
        if key in INSECURE_SECRET_KEYS:
            return True
        if key.startswith("please-change") or key.startswith("dev-secret"):
            return True
        return False

    @property
    def smtp_configured(self) -> bool:
        return bool(
            (self.mail_server or "").strip()
            and (self.mail_password or "").strip()
            and (self.mail_username or self.mail_from or "").strip()
        )

    @property
    def imap_configured(self) -> bool:
        return bool(
            (self.imap_server or "").strip()
            and (self.mail_password or "").strip()
            and (self.mail_username or "").strip()
        )

    @property
    def mail_sender(self) -> str:
        """发件人地址：优先 MAIL_FROM，否则用登录账号。"""
        return (self.mail_from or self.mail_username or "").strip()

    @property
    def effective_auth_cookie_secure(self) -> bool:
        """Cookie Secure 属性：显式配置优先，否则生产 True、开发 False。"""
        if self.auth_cookie_secure is not None:
            return self.auth_cookie_secure
        return self.is_production


@lru_cache
def get_settings() -> Settings:
    return Settings()


def clear_settings_cache() -> None:
    get_settings.cache_clear()


def assert_secure_startup(settings: Settings | None = None) -> None:
    """
    Production hard-block on default/weak SECRET_KEY.
    Raises RuntimeError when APP_ENV=production and secret is insecure
    (unless ALLOW_INSECURE_SECRET=true for controlled tests).
    """
    s = settings or get_settings()
    if not s.is_production:
        return
    if s.allow_insecure_secret:
        return
    if s.secret_is_insecure:
        raise RuntimeError(
            "生产环境禁止使用默认/弱 SECRET_KEY。"
            "请在 .env 中设置足够长的随机 SECRET_KEY（建议 openssl rand -hex 32）。"
        )
