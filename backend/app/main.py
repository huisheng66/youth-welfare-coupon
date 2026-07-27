from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api import auth, coupons, export, merchants, points, stats, users
from app.core.config import get_settings
from app.core.database import Base, SessionLocal, engine
from app.core.migrate import ensure_schema
from app.seed import seed_if_empty

settings = get_settings()

# Ensure SQLite directory exists
if settings.database_url.startswith("sqlite:///./"):
    db_path = settings.database_url.replace("sqlite:///./", "")
    Path(db_path).parent.mkdir(parents=True, exist_ok=True)

app = FastAPI(title=settings.app_name, version="1.0.0")

origins = [o.strip() for o in settings.cors_origins.split(",") if o.strip()]
# 开发期允许本机 / 局域网 HTTPS 访问（手机扫码调试）
app.add_middleware(
    CORSMiddleware,
    allow_origins=origins or ["*"],
    allow_origin_regex=r"https?://(localhost|127\.0\.0\.1|192\.168\.\d{1,3}\.\d{1,3}|10\.\d{1,3}\.\d{1,3}\.\d{1,3}|172\.(1[6-9]|2\d|3[0-1])\.\d{1,3}\.\d{1,3})(:\d+)?",
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(auth.router, prefix="/api")
app.include_router(users.router, prefix="/api")
app.include_router(merchants.router, prefix="/api")
app.include_router(coupons.router, prefix="/api")
app.include_router(stats.router, prefix="/api")
app.include_router(points.router, prefix="/api")
app.include_router(export.router, prefix="/api")


@app.on_event("startup")
def on_startup() -> None:
    Base.metadata.create_all(bind=engine)
    ensure_schema(engine)
    db = SessionLocal()
    try:
        seed_if_empty(db)
        from app.services.coupons import expire_stale_coupons

        expire_stale_coupons(db)
    finally:
        db.close()


@app.get("/api/health")
def health() -> dict:
    return {
        "status": "ok",
        "app": settings.app_name,
        "version": "1.2.0",
        "live_code_expire_seconds": settings.live_code_expire_seconds,
        "smtp_configured": settings.smtp_configured,
        "mail_console": settings.mail_console and not settings.smtp_configured,
    }
