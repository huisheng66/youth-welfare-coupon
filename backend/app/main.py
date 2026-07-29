from __future__ import annotations

import logging
from pathlib import Path

from fastapi import FastAPI, Request, Response
from fastapi.middleware.cors import CORSMiddleware
from starlette.middleware.base import BaseHTTPMiddleware

from app.api import auth, coupons, export, merchants, points, stats, users
from app.core.client_ip import get_client_ip
from app.core.config import assert_secure_startup, get_settings
from app.core.database import Base, SessionLocal, engine
from app.core.migrate import ensure_schema
from app.seed import seed_if_empty
from app.services.rate_limit import get_ip_limiter, reset_limiters

logger = logging.getLogger(__name__)

# LAN / local origin regex for optional CORS (dev / explicit CORS_ALLOW_LAN)
LAN_ORIGIN_REGEX = (
    r"https?://(localhost|127\.0\.0\.1|"
    r"192\.168\.\d{1,3}\.\d{1,3}|"
    r"10\.\d{1,3}\.\d{1,3}\.\d{1,3}|"
    r"172\.(1[6-9]|2\d|3[0-1])\.\d{1,3}\.\d{1,3})(:\d+)?"
)


def apply_security_headers(response: Response) -> Response:
    """Attach baseline security headers (also used on early 429 paths)."""
    response.headers.setdefault("X-Content-Type-Options", "nosniff")
    response.headers.setdefault("X-Frame-Options", "DENY")
    response.headers.setdefault("Referrer-Policy", "strict-origin-when-cross-origin")
    response.headers.setdefault("X-XSS-Protection", "0")
    return response


class SecurityHeadersMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next) -> Response:
        response = await call_next(request)
        return apply_security_headers(response)


class GlobalIpRateLimitMiddleware(BaseHTTPMiddleware):
    """Light per-IP request ceiling to blunt naive scanning (optional)."""

    async def dispatch(self, request: Request, call_next) -> Response:
        # Skip health for probes / scanners
        if request.url.path in {"/api/health", "/health"}:
            return await call_next(request)
        limiter = get_ip_limiter()
        if limiter is None:
            return await call_next(request)
        ip = get_client_ip(request)
        allowed, retry = limiter.check(ip)
        if not allowed:
            # Early return must still carry security headers (outer middleware may not run)
            return apply_security_headers(
                Response(
                    content='{"detail":"请求过于频繁，请稍后再试"}',
                    status_code=429,
                    media_type="application/json",
                    headers={"Retry-After": str(retry)},
                )
            )
        limiter.hit(ip)
        return await call_next(request)


def create_app() -> FastAPI:
    settings = get_settings()
    assert_secure_startup(settings)

    # Ensure SQLite directory exists
    if settings.database_url.startswith("sqlite:///./"):
        db_path = settings.database_url.replace("sqlite:///./", "")
        Path(db_path).parent.mkdir(parents=True, exist_ok=True)

    openapi_on = settings.effective_openapi_enabled
    app = FastAPI(
        title=settings.app_name,
        version="1.4.0",
        docs_url="/docs" if openapi_on else None,
        redoc_url="/redoc" if openapi_on else None,
        openapi_url="/openapi.json" if openapi_on else None,
    )

    origins = settings.cors_origin_list
    cors_kwargs: dict = {
        "allow_origins": origins if origins else [],
        "allow_credentials": True,
        "allow_methods": ["*"],
        "allow_headers": ["*"],
    }
    if settings.effective_cors_allow_lan:
        cors_kwargs["allow_origin_regex"] = LAN_ORIGIN_REGEX
    app.add_middleware(CORSMiddleware, **cors_kwargs)
    app.add_middleware(SecurityHeadersMiddleware)
    if settings.global_ip_max_requests > 0:
        app.add_middleware(GlobalIpRateLimitMiddleware)

    app.include_router(auth.router, prefix="/api")
    app.include_router(users.router, prefix="/api")
    app.include_router(merchants.router, prefix="/api")
    app.include_router(coupons.router, prefix="/api")
    app.include_router(stats.router, prefix="/api")
    app.include_router(points.router, prefix="/api")
    app.include_router(export.router, prefix="/api")

    @app.on_event("startup")
    def on_startup() -> None:
        # Re-assert in case settings were mutated after import
        assert_secure_startup(get_settings())
        reset_limiters()
        Base.metadata.create_all(bind=engine)
        ensure_schema(engine)
        db = SessionLocal()
        try:
            seed_if_empty(db)
            from app.services.coupons import expire_stale_coupons

            expire_stale_coupons(db)
        finally:
            db.close()
        s = get_settings()
        if s.using_secret_for_field_crypto:
            logger.warning(
                "FIELD_ENCRYPTION_KEY unset — bank-card encryption uses SECRET_KEY (deprecated)"
            )

    @app.get("/api/health")
    def health() -> dict:
        s = get_settings()
        url = s.database_url
        if url.startswith("sqlite"):
            db_engine = "sqlite"
        elif "mysql" in url:
            db_engine = "mysql"
        elif "postgres" in url:
            db_engine = "postgresql"
        else:
            db_engine = "other"
        return {
            "status": "ok",
            "app": s.app_name,
            "version": "1.4.0",
            "live_code_expire_seconds": s.live_code_expire_seconds,
            "smtp_configured": s.smtp_configured,
            "mail_console": s.mail_console and not s.smtp_configured,
            "database": db_engine,
            "app_env": s.app_env,
            "openapi_enabled": s.effective_openapi_enabled,
        }

    return app


# Uvicorn entry: app.main:app
app = create_app()
