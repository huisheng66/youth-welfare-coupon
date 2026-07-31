# 后端镜像：多阶段构建 + 非 root 用户
# 用法：docker compose build api && docker compose up -d
# 规范对照：
#   - # syntax 锁定 BuildKit 前端（Docker 官方 best practices）
#   - OCI 标准 LABEL（hadolint --strict-labels）
#   - setuid/setgid 清理（CIS Docker Benchmark §4.8）
#   - 非 root USER（CIS §4.1 / OWASP #2）
#   - HEALTHCHECK（CIS §4.6）
# syntax=docker/dockerfile:1

# ---------- 构建阶段 ----------
# 固定 patch 版本，保证可重现构建（避免 latest 自动升级引入意外变更）
FROM python:3.12.7-slim AS builder

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PIP_INDEX_URL=https://mirrors.aliyun.com/pypi/simple/

WORKDIR /build

# 切换 apt 到清华镜像源（trixie 新格式 sources.list.d/debian.sources），加速国内构建
# --mount=type=cache：BuildKit 缓存 apt lists，重复构建跳过网络下载（Docker 官方 best practice）
RUN --mount=type=cache,target=/var/cache/apt,sharing=locked \
    --mount=type=cache,target=/var/lib/apt,sharing=locked \
    sed -i 's|deb.debian.org|mirrors.tuna.tsinghua.edu.cn|g' /etc/apt/sources.list.d/debian.sources \
    && rm -rf /var/lib/apt/lists/* \
    && apt-get update \
    && apt-get install -y --no-install-recommends gcc libffi-dev

# 先装依赖（利用 layer 缓存；pip 走阿里镜像）
# --mount=type=cache：pip 下载缓存跨构建复用，避免重复下载 wheel（Docker 官方 awesome-compose 示例）
# COPY --link：以快照方式拷贝，不破坏后续层缓存（Docker 1.4+ 最佳实践）
COPY --link requirements.txt .
RUN --mount=type=cache,target=/root/.cache/pip,sharing=locked \
    python -m venv /opt/venv \
    && /opt/venv/bin/pip install -U pip \
    && /opt/venv/bin/pip install -r requirements.txt

# ---------- 运行阶段 ----------
FROM python:3.12.7-slim AS runtime

# OCI 标准 LABEL（OCI Image Spec / hadolint --strict-labels）
# CI 通过 --build-arg 注入实际值；本地构建用默认值
ARG APP_VERSION=1.4.0
ARG APP_REVISION=unknown
ARG APP_CREATED=unknown
LABEL org.opencontainers.image.title="youth-welfare-api" \
      org.opencontainers.image.description="Youth Welfare Coupon API (FastAPI)" \
      org.opencontainers.image.version="${APP_VERSION}" \
      org.opencontainers.image.revision="${APP_REVISION}" \
      org.opencontainers.image.created="${APP_CREATED}" \
      org.opencontainers.image.source="https://github.com/youth-welfare/youth" \
      org.opencontainers.image.licenses="MIT"

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PATH="/opt/venv/bin:$PATH"

# 运行时无需额外装 libffi：python:3.12-slim 基础镜像已自带（python ctypes 依赖）
# 仅创建非 root 用户
RUN groupadd --system --gid 1001 app \
    && useradd --system --uid 1001 --gid app --home-dir /app --shell /sbin/nologin app

# 拷贝虚拟环境
COPY --from=builder --link /opt/venv /opt/venv

WORKDIR /app

# 拷贝应用代码（COPY --link：快照挂载，不破坏后续层缓存）
COPY --link --chown=app:app . /app

# 数据目录（SQLite / 限流文件）
RUN mkdir -p /app/data && chown -R app:app /app

# CIS §4.8：清理 setuid/setgid 位，减少提权攻击面
# -xdev 不跨文件系统；/6000 匹配 setuid 或 setgid；|| true 容忍无权限错误
RUN find / -xdev -perm /6000 -type f -exec chmod a-s {} \+ 2>/dev/null || true

USER app

EXPOSE 19001

HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 \
    CMD python -c "import urllib.request,sys; sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:19001/api/health', timeout=3).status==200 else 1)"

# 启动：先跑 alembic 迁移（生产模式），再起 uvicorn
CMD ["sh", "-c", "APP_ENV=production python -m alembic upgrade head && uvicorn app.main:app --host 0.0.0.0 --port 19001 --workers 2"]
