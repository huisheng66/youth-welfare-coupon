from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    app_name: str = "青年福利券系统"
    secret_key: str = "dev-secret-change-me-in-production"
    algorithm: str = "HS256"
    access_token_expire_minutes: int = 60 * 24
    database_url: str = "sqlite:///./data/app.db"
    cors_origins: str = (
        "http://localhost:5173,http://127.0.0.1:5173,"
        "https://localhost:5173,https://127.0.0.1:5173"
    )
    live_code_expire_seconds: int = 30

    # SMTP（mail_server 与 mail_password 都填才启用真实发信；否则控制台模式）
    # 腾讯企业邮示例: smtp.exmail.qq.com / 465 / SSL
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
