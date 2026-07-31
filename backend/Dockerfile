# 后端镜像：多阶段构建 + 非 root 用户
# 用法：docker compose build api && docker compose up -d

# ---------- 构建阶段 ----------
FROM python:3.12-slim AS builder

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PIP_INDEX_URL=https://mirrors.aliyun.com/pypi/simple/

WORKDIR /build

# 切换 apt 到清华镜像源（trixie 新格式 sources.list.d/debian.sources），加速国内构建
RUN sed -i 's|deb.debian.org|mirrors.tuna.tsinghua.edu.cn|g' /etc/apt/sources.list.d/debian.sources \
    && apt-get update \
    && apt-get install -y --no-install-recommends gcc libffi-dev \
    && rm -rf /var/lib/apt/lists/*

# 先装依赖（利用 layer 缓存；pip 走阿里镜像）
COPY requirements.txt .
RUN python -m venv /opt/venv \
    && /opt/venv/bin/pip install -U pip \
    && /opt/venv/bin/pip install -r requirements.txt

# ---------- 运行阶段 ----------
FROM python:3.12-slim AS runtime

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PATH="/opt/venv/bin:$PATH"

# 运行时无需额外装 libffi：python:3.12-slim 基础镜像已自带（python ctypes 依赖）
# 仅创建非 root 用户
RUN groupadd --system --gid 1001 app \
    && useradd --system --uid 1001 --gid app --home-dir /app --shell /sbin/nologin app

# 拷贝虚拟环境
COPY --from=builder /opt/venv /opt/venv

WORKDIR /app

# 拷贝应用代码
COPY --chown=app:app . /app

# 数据目录（SQLite / 限流文件）
RUN mkdir -p /app/data && chown -R app:app /app

USER app

EXPOSE 19001

HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 \
    CMD python -c "import urllib.request,sys; sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:19001/api/health', timeout=3).status==200 else 1)"

# 启动：先跑 alembic 迁移（生产模式），再起 uvicorn
CMD ["sh", "-c", "APP_ENV=production python -m alembic upgrade head && uvicorn app.main:app --host 0.0.0.0 --port 19001 --workers 2"]
