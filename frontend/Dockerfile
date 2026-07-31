# 前端镜像：多阶段构建（node build → nginx serve）
# 用法：docker compose build web && docker compose up -d

# ---------- 构建阶段 ----------
FROM node:20-alpine AS builder

WORKDIR /build

# npm 走淘宝镜像源，加速国内构建
RUN npm config set registry https://registry.npmmirror.com

# 先拷依赖文件（利用 layer 缓存）
COPY package.json package-lock.json ./

RUN npm ci

# 拷源码并构建
COPY . .

# 容器内构建走 HTTP（basicSsl 仅 dev 用）
RUN npm run build -- --mode production

# ---------- 运行阶段 ----------
FROM nginx:alpine AS runtime

# 复制自定义 nginx 配置（SPA + /api 反代）
COPY nginx.conf /etc/nginx/conf.d/default.conf

# 复制构建产物
COPY --from=builder /build/dist /usr/share/nginx/html

# 非 root 监听 8080（nginx.conf 中已配置）
EXPOSE 8080

HEALTHCHECK --interval=30s --timeout=3s --start-period=5s --retries=3 \
    CMD wget -q --spider http://127.0.0.1:8080/ || exit 1
