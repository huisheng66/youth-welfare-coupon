# 前端镜像：多阶段构建（node build → nginx serve）
# 用法：docker compose build web && docker compose up -d
# 规范对照：
#   - # syntax 锁定 BuildKit 前端（Docker 官方 best practices）
#   - 运行阶段用 nginx-unprivileged（非 root，CIS §4.1 / OWASP #2）
#   - OCI 标准 LABEL（hadolint --strict-labels）
#   - HEALTHCHECK（CIS §4.6）
# syntax=docker/dockerfile:1

# ---------- 构建阶段 ----------
# 固定版本，保证可重现构建
FROM node:20.18-alpine3.20 AS builder

WORKDIR /build

# npm 走淘宝镜像源，加速国内构建
RUN npm config set registry https://registry.npmmirror.com

# 先拷依赖文件（利用 layer 缓存）
# COPY --link：快照方式拷贝，不破坏后续层缓存（Docker 1.4+ 最佳实践）
COPY --link package.json package-lock.json ./

# --mount=type=cache：npm 下载缓存跨构建复用，避免重复下载 tarball（Docker 官方 best practice）
RUN --mount=type=cache,target=/root/.npm \
    npm ci

# 拷源码并构建
COPY --link . .

# 容器内构建走 HTTP（basicSsl 仅 dev 用）
RUN npm run build -- --mode production

# ---------- 运行阶段 ----------
# nginx-unprivileged：以 uid 101 (nginx) 运行，默认监听 8080，无需 cap_add
# 对照 nginx:alpine 需 root 启动 master + cap_add [CHOWN,SETUID,SETGID]
FROM nginxinc/nginx-unprivileged:1.27-alpine AS runtime

ARG APP_VERSION=1.4.0
ARG APP_REVISION=unknown
ARG APP_CREATED=unknown
LABEL org.opencontainers.image.title="youth-welfare-web" \
      org.opencontainers.image.description="Youth Welfare Coupon Web (Vue + nginx)" \
      org.opencontainers.image.version="${APP_VERSION}" \
      org.opencontainers.image.revision="${APP_REVISION}" \
      org.opencontainers.image.created="${APP_CREATED}" \
      org.opencontainers.image.source="https://github.com/youth-welfare/youth" \
      org.opencontainers.image.licenses="MIT"

# 复制自定义 nginx 配置（SPA + /api 反代，监听 8080 与 nginx-unprivileged 默认一致）
COPY --link nginx.conf /etc/nginx/conf.d/default.conf

# 复制构建产物（COPY --link：快照挂载，不破坏缓存）
COPY --from=builder --link /build/dist /usr/share/nginx/html

EXPOSE 8080

HEALTHCHECK --interval=30s --timeout=3s --start-period=5s --retries=3 \
    CMD wget -q --spider http://127.0.0.1:8080/ || exit 1
