# Docker 部署指南

本文档说明如何用 Docker Compose 一键部署青年福利券系统。

## 前置条件

- Docker Engine ≥ 24.0
- Docker Compose v2（`docker compose` 子命令，非旧版 `docker-compose`）
- 服务器开放 80 端口（如需 HTTPS，前面加反代或用 traefik）

## 快速开始

### 1. 准备环境变量

```bash
cp .env.docker.example .env
```

编辑 `.env`，**必须修改**：

| 变量 | 说明 | 生成方式 |
|------|------|----------|
| `SECRET_KEY` | JWT 签名密钥 | `openssl rand -hex 32` |
| `FIELD_ENCRYPTION_KEY` | 银行卡字段加密密钥 | `openssl rand -hex 32` |
| `CORS_ORIGINS` | 前端正式域名 | `https://coupon.example.com` |
| `MAIL_USERNAME` / `MAIL_PASSWORD` | 腾讯企业邮账号 | 企业邮箱后台 |

### 2. 构建并启动

```bash
docker compose up -d --build
```

首次启动会：
- 构建后端镜像（Python 3.12 + 依赖安装）
- 构建前端镜像（Node 20 构建 → nginx 服务）
- 启动 Redis 容器
- 后端启动时自动跑 `alembic upgrade head` 建表

### 3. 验证

```bash
# 健康检查
curl http://localhost/api/health

# 应返回类似：
# {"status":"ok","app":"youth","version":"1.4.0",...}

# 容器状态
docker compose ps

# 查看日志
docker compose logs -f api
docker compose logs -f web
```

访问 `http://<服务器IP>/` 即可打开前端登录页。

## 架构说明

```
                    ┌─────────────┐
   用户 ──80──►     │  web (nginx) │  ──SPA 静态文件
                    │   :8080      │
                    └──────┬───────┘
                           │ /api/ 反代
                    ┌──────▼───────┐
                    │   api        │  ──FastAPI :19001
                    │   (uvicorn)  │
                    └──────┬───────┘
                           │
              ┌────────────┼────────────┐
              │            │            │
        ┌─────▼─────┐ ┌───▼────┐ ┌────▼─────┐
        │ api-data  │ │ redis  │ │ redis-data│
        │ (volume)  │ │ :6379  │ │ (volume) │
        │ SQLite    │ └────────┘ └──────────┘
        │ 限流文件   │
        └───────────┘
```

- **web**：nginx 容器，对外暴露 80，服务前端静态文件 + 反代 `/api/` 到后端
- **api**：FastAPI 容器，监听 19001（仅 compose 网络内可见），2 个 worker
- **redis**：限流后端 + 未来缓存层，AOF 持久化
- **api-data**：SQLite 数据库 + 限流文件持久化卷

## 常用操作

### 重新构建（代码更新后）

```bash
docker compose up -d --build api web
```

### 回滚（切到上一个镜像）

```bash
# 假设上一个镜像 tag 为 welfare-api:prev
docker tag welfare-api:prev welfare-api:latest
docker compose up -d api
```

### 查看日志

```bash
# 实时跟踪
docker compose logs -f api
docker compose logs -f web

# 最近 100 行
docker compose logs --tail 100 api
```

### 进入容器

```bash
docker compose exec api sh
docker compose exec web sh
```

### 停止与清理

```bash
# 停止容器（保留数据）
docker compose down

# 停止并删除数据卷（⚠️ 会丢失数据库）
docker compose down -v
```

## 常用命令快捷方式

项目提供两套等价的快捷命令封装，避免记长串 `docker compose` 参数：

| 操作 | Makefile（Linux/macOS） | PowerShell（Windows） |
|------|------------------------|----------------------|
| 启动 dev | `make up` | `.\scripts\docker.ps1 up` |
| 启动 prod | `make up-prod` | `.\scripts\docker.ps1 up-prod` |
| 启动 HTTPS | `make up-https` | `.\scripts\docker.ps1 up-https` |
| 停止 | `make down` | `.\scripts\docker.ps1 down` |
| 查看日志 | `make logs-api` | `.\scripts\docker.ps1 logs api` |
| 进入容器 | `make shell-api` | `.\scripts\docker.ps1 shell api` |
| 备份数据库 | `make backup` | `.\scripts\docker.ps1 backup` |
| 恢复数据库 | `make restore FILE=./backup/xxx.db` | `.\scripts\docker.ps1 restore FILE=.\backup\xxx.db` |
| 镜像扫描 | `make scan` | `.\scripts\docker.ps1 scan` |
| 校验配置 | `make validate` | `.\scripts\docker.ps1 validate` |

运行 `make help` 或 `.\scripts\docker.ps1 help` 查看完整命令列表。

## 开发 vs 生产配置

Compose 默认会自动加载 `docker-compose.override.yml`，提供开发便利：

| 配置项 | 开发（override） | 生产（base） |
|--------|------------------|--------------|
| api 端口 | 暴露 19001 | 仅内部网络 |
| redis 端口 | 暴露 6379 | 仅内部网络 |
| 启动命令 | `uvicorn --reload`（热重载） | `alembic upgrade head && uvicorn --workers 2` |
| APP_ENV | development | production |
| OpenAPI | 开启 | 关闭 |
| 演示数据 | 自动 seed | 不 seed |
| 资源限制 | 无 | api 512MB/1.5核, web 128MB/0.5核, redis 96MB/0.5核 |

启动生产模式（跳过 override）：

```bash
docker compose -f docker-compose.yml up -d --build
# 或
make up-prod
```

## 资源限制与日志轮转

生产 compose 已为每个服务配置：

**资源限制**（防止单容器吃光宿主机资源）：
- api: 内存 512MB / CPU 1.5 核
- web: 内存 128MB / CPU 0.5 核
- redis: 内存 96MB / CPU 0.5 核

**日志轮转**（防止日志撑爆磁盘）：
- 驱动：json-file
- 单文件最大 10MB，保留 3 份
- 每容器日志上限约 30MB

如需调整，编辑 `docker-compose.yml` 中对应服务的 `mem_limit`、`cpus`、`logging.options`。

## 网络隔离

生产 compose 拆分两个网络：

```
┌─────────────────────────────────────────────┐
│  frontend-net（对外）                        │
│    └─ web (80→8080)                          │
│         │                                    │
│         │ 反代 /api/                         │
│         ▼                                    │
│  backend-net（内部）                          │
│    ├─ api (19001，无端口映射，外部不可达)     │
│    └─ redis (6379，无端口映射，外部不可达)    │
└─────────────────────────────────────────────┘
```

- **api 和 redis 不暴露任何端口**到宿主机，只能通过 web 容器反代访问
- web 同时接入两个网络：frontend-net 接收外部请求，backend-net 反代到 api
- 依赖顺序：redis healthy → api 启动 → api healthy → web 启动

## 数据库备份与恢复

### 备份

```bash
# 用快捷命令（推荐）
make backup
# 或 PowerShell
.\scripts\docker.ps1 backup

# 手动执行
docker compose exec -T api python -c "import shutil; shutil.copy('/app/data/app.db','/app/data/backup-$(date +%Y%m%d).db')"
docker compose cp api:/app/data/backup-20260731.db ./backup/backup-20260731.db
```

### 恢复

```bash
# 拷入容器
docker compose cp ./backup-20260731.db api:/app/data/restore.db

# 替换并重启
docker compose exec api sh -c "cp /app/data/restore.db /app/data/app.db"
docker compose restart api
```

## 使用外部 MySQL

如需用 MySQL 替代 SQLite：

1. 在 `docker-compose.yml` 中注释掉 api 服务的 `DATABASE_URL` 环境变量
2. 在 `.env` 中设置：
   ```
   DATABASE_URL=mysql+pymysql://welfare:密码@mysql-host:3306/welfare?charset=utf8mb4
   ```
3. 也可在 compose 中加 mysql 服务（参考下方"扩展"）

## HTTPS 配置

容器内 web 服务只监听 80。项目已内置 Caddy overlay 方案，自动签发并续期 Let's Encrypt 证书。

### 方案 A：Caddy 自动 HTTPS（推荐，项目已内置）

项目已提供 `docker-compose.https.yml` 和 `Caddyfile`，开箱即用：

1. 在 `.env` 中设置正式域名：
   ```
   WELFARE_DOMAIN=coupon.example.com
   ```
2. 确保域名 A 记录已指向本机公网 IP，且 80/443 端口对外可达
3. 启动：
   ```bash
   docker compose -f docker-compose.yml -f docker-compose.https.yml up -d --build
   # 或
   make up-https
   ```

Caddy 会自动：
- 向 Let's Encrypt 申请证书（首次访问触发，约 10-30 秒）
- 自动续期（到期前 30 天）
- 80 端口所有请求跳转到 443
- 注入 HSTS / X-Content-Type-Options 等安全响应头

`Caddyfile` 可按需自定义（如添加多个域名、访问日志等）。

### 方案 B：外部 Nginx + Certbot

参考 `deploy/nginx-welfare.conf`，反代到 `127.0.0.1:80`（容器映射的端口）。

## 扩展

### 加 MySQL 服务

在 `docker-compose.yml` 中添加：

```yaml
  mysql:
    image: mysql:8.0
    container_name: welfare-mysql
    restart: unless-stopped
    environment:
      MYSQL_ROOT_PASSWORD: ${MYSQL_ROOT_PASSWORD}
      MYSQL_DATABASE: welfare
      MYSQL_USER: welfare
      MYSQL_PASSWORD: ${MYSQL_PASSWORD}
    volumes:
      - mysql-data:/var/lib/mysql
    networks:
      - welfare-net
```

并在 api 服务中注释掉 `DATABASE_URL`，改在 `.env` 设置：
```
DATABASE_URL=mysql+pymysql://welfare:${MYSQL_PASSWORD}@mysql:3306/welfare?charset=utf8mb4
```

### 水平扩展后端

```bash
docker compose up -d --scale api=3
```

注意：SQLite 不支持多容器并发写，多实例必须用 MySQL/PostgreSQL。

## 故障排查

### 后端启动失败

```bash
# 看启动日志
docker compose logs api | tail -50

# 常见问题：
# - SECRET_KEY 未设置 → 修改 .env
# - alembic 迁移失败 → 进入容器手动跑：docker compose exec api python -m alembic upgrade head
# - 数据卷权限 → 确认容器以非 root (uid 1001) 运行，volume 权限正确
```

### 前端访问 502

```bash
# 检查后端健康
docker compose ps
# api 应为 healthy

# 检查 nginx 日志
docker compose logs web | tail -20
```

### Redis 连不上

```bash
# 检查 Redis
docker compose exec redis redis-cli ping
# 应返回 PONG
```

## 与裸机部署的关系

Docker 化与 `deploy/install-ubuntu.sh` 裸机部署**并存**：

- **Docker**：推荐用于新环境、CI/CD、需要快速回滚的场景
- **裸机**：适用于不装 Docker 的环境，或对性能有极致要求

两种方式共用同一份代码与 `.env` 配置，可平滑切换。

## 安全清单

- [ ] `SECRET_KEY` 和 `FIELD_ENCRYPTION_KEY` 已替换为随机串
- [ ] `APP_ENV=production`
- [ ] `OPENAPI_ENABLED=false`
- [ ] `SEED_DEMO_ACCOUNTS=false`
- [ ] `CORS_ORIGINS` 填正式域名，非 `*`
- [ ] `CORS_ALLOW_LAN=false`
- [ ] HTTPS 已配置（Caddy 或外部 Nginx）
- [ ] 数据库备份已配置（见 `docs/backup-restore.md`）
- [ ] 服务器防火墙仅开放 80/443
