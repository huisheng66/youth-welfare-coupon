from __future__ import annotations

import logging
import re
import uuid
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, Request, Response
from fastapi.middleware.cors import CORSMiddleware
from starlette.middleware.base import BaseHTTPMiddleware

from app.api import auth, coupons, export, imports, merchants, outbox, points, stats, users
from app.core.client_ip import get_client_ip
from app.core.config import assert_secure_startup, get_settings
import app.core.database as db
from app.core.logging import request_id_var, setup_logging
from app.core.migrate import apply_migrations
from app.seed import seed_if_empty
from app.services.rate_limit import get_ip_limiter, reset_limiters

logger = logging.getLogger(__name__)

REQUEST_ID_RE = re.compile(r"^[A-Za-z0-9._-]{1,64}$")

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
    response.headers.setdefault("Permissions-Policy", "camera=(self), microphone=(), geolocation=()")
    response.headers.setdefault("X-Permitted-Cross-Domain-Policies", "none")
    if get_settings().is_production:
        response.headers.setdefault(
            "Strict-Transport-Security", "max-age=31536000; includeSubDomains"
        )
    return response


class SecurityHeadersMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next) -> Response:
        response = await call_next(request)
        if request.url.path.startswith("/api/auth") or "/bank-card" in request.url.path:
            response.headers.setdefault("Cache-Control", "no-store")
            response.headers.setdefault("Pragma", "no-cache")
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
        allowed, retry = limiter.acquire(ip)
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
        return await call_next(request)


class CsrfProtectMiddleware(BaseHTTPMiddleware):
    """基于 X-Requested-With 的 CSRF 防护（配合 SameSite=Lax Cookie）。

    浏览器原生表单不会带 X-Requested-With，前端 axios 全局加上后即可区分 AJAX 与跨站提交。
    仅对写方法（POST/PUT/PATCH/DELETE）校验；GET/HEAD/OPTIONS 跳过。
    """

    WRITE_METHODS = {"POST", "PUT", "PATCH", "DELETE"}

    async def dispatch(self, request: Request, call_next) -> Response:
        if request.method in self.WRITE_METHODS and "x-requested-with" not in {k.lower() for k in request.headers.keys()}:
            return apply_security_headers(
                Response(
                    content='{"detail":"缺少 CSRF 校验头（X-Requested-With）"}',
                    status_code=403,
                    media_type="application/json",
                )
            )
        return await call_next(request)


class RequestIdMiddleware:
    """纯 ASGI 中间件：为每个请求注入 request_id 到 contextvars + 响应头。

    用纯 ASGI 而非 BaseHTTPMiddleware，避免后者在 call_next 跨任务执行时
    contextvars 不传播的坑。所有 logger 输出自动带 request_id，可串联单次请求全链路。
    """

    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        headers = dict(scope.get("headers") or [])
        incoming_rid = headers.get(b"x-request-id", b"").decode("ascii", "ignore")
        rid = incoming_rid if REQUEST_ID_RE.fullmatch(incoming_rid) else uuid.uuid4().hex[:12]
        token = request_id_var.set(rid)

        async def send_wrapper(message):
            if message["type"] == "http.response.start":
                response_headers = [
                    (key, value)
                    for key, value in message.setdefault("headers", [])
                    if key.lower() != b"x-request-id"
                ]
                response_headers.append((b"x-request-id", rid.encode("ascii")))
                message["headers"] = response_headers
            await send(message)

        try:
            await self.app(scope, receive, send_wrapper)
        finally:
            request_id_var.reset(token)


def create_app() -> FastAPI:
    settings = get_settings()
    assert_secure_startup(settings)
    # 结构化日志：生产 JSON Lines + request_id，开发人类可读
    setup_logging()

    # Ensure SQLite directory exists
    if settings.database_url.startswith("sqlite:///./"):
        db_path = settings.database_url.replace("sqlite:///./", "")
        Path(db_path).parent.mkdir(parents=True, exist_ok=True)

    # engine 由 app.core.database 模块级 init_engine() 构造（import 时按 settings）；
    # 测试可通过 init_engine(test_settings) 显式重建切换，create_app 不重复构造
    # 以免覆盖测试已注入的 engine。

    @asynccontextmanager
    async def lifespan(_: FastAPI):
        # Re-assert in case settings were mutated after import
        s = get_settings()
        assert_secure_startup(s)
        reset_limiters()
        # T08：生产 worker 启动只做只读 schema 校验（版本一致 + 关键列存在），
        # 不执行 DDL——迁移由发布流程用迁移账号单独执行
        # （alembic upgrade head / deploy/migrate-release.sh），避免多 worker
        # 并发建表、运行账号需要 DDL 权限，以及迁移阻塞服务启动。
        if s.is_production:
            from app.core.migrate import verify_schema_current

            verify_schema_current(db.engine)
        else:
            # 开发环境保留 create_all + ensure_schema，方便本地迭代
            apply_migrations(db.engine, production=False)
        session = db.SessionLocal()
        try:
            seed_if_empty(session)
            from app.services.coupons import expire_stale_coupons

            expire_stale_coupons(session)
        finally:
            session.close()
        if s.using_secret_for_field_crypto:
            logger.warning(
                "FIELD_ENCRYPTION_KEY unset — bank-card encryption uses SECRET_KEY (deprecated)"
            )
        # T15：邮件 outbox worker——进程内后台任务，重启后 queued 任务仍在库中继续投递
        import asyncio

        from app.services.outbox import worker_loop

        stop_event = asyncio.Event()
        worker = asyncio.create_task(worker_loop(stop_event))
        yield
        # shutdown：通知 worker 退出并等待当前批次结束
        stop_event.set()
        try:
            await asyncio.wait_for(worker, timeout=10)
        except asyncio.TimeoutError:
            worker.cancel()
        except asyncio.CancelledError:
            pass

    openapi_on = settings.effective_openapi_enabled
    app = FastAPI(
        title=settings.app_name,
        version="1.4.0",
        docs_url="/docs" if openapi_on else None,
        redoc_url="/redoc" if openapi_on else None,
        openapi_url="/openapi.json" if openapi_on else None,
        lifespan=lifespan,
    )

    origins = settings.cors_origin_list
    cors_kwargs: dict = {
        "allow_origins": origins if origins else [],
        "allow_credentials": True,
        "allow_methods": ["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"],
        "allow_headers": ["Accept", "Authorization", "Content-Type", "X-Requested-With", "X-Request-ID"],
        "expose_headers": ["Content-Disposition", "Retry-After", "X-Export-Truncated", "X-Request-ID"],
    }
    if settings.effective_cors_allow_lan:
        cors_kwargs["allow_origin_regex"] = LAN_ORIGIN_REGEX
    app.add_middleware(CORSMiddleware, **cors_kwargs)
    app.add_middleware(SecurityHeadersMiddleware)
    app.add_middleware(CsrfProtectMiddleware)
    if settings.global_ip_max_requests > 0:
        app.add_middleware(GlobalIpRateLimitMiddleware)
    # RequestIdMiddleware 最后添加 = 最外层，确保所有内层中间件与路由日志都带 request_id
    app.add_middleware(RequestIdMiddleware)

    app.include_router(auth.router, prefix="/api")
    app.include_router(users.router, prefix="/api")
    app.include_router(merchants.router, prefix="/api")
    app.include_router(coupons.router, prefix="/api")
    app.include_router(stats.router, prefix="/api")
    app.include_router(points.router, prefix="/api")
    app.include_router(export.router, prefix="/api")
    app.include_router(imports.router, prefix="/api")
    app.include_router(outbox.router, prefix="/api")

    @app.get("/api/health")
    def health() -> dict:
        s = get_settings()
        # 生产只暴露存活状态：数据库类型 / SMTP 配置 / 运行环境等都是无谓的指纹
        if s.is_production:
            return {"status": "ok"}
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
