from functools import lru_cache
from typing import Literal

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

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
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    app_name: str = "青年福利券系统"
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
    mail_from_name: str = "青年福利券系统"
    mail_starttls: bool = False
    mail_ssl_tls: bool = True
    mail_console: bool = True
    email_code_expire_minutes: int = 10
    email_code_cooldown_seconds: int = 60
    email_code_max_per_hour: int = 8

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
    def mail_sender(self) -> str:
        """发件人地址：优先 MAIL_FROM，否则用登录账号。"""
        return (self.mail_from or self.mail_username or "").strip()


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
