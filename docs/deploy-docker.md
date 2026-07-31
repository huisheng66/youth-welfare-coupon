# Docker 部署指南

本文档说明如何用 Docker Compose 一键部署青年福利券系统。

## 前置条件

- Docker Engine ≥ 24.0
- Docker Compose v2（`docker compose` 子命令，非旧版 `docker-compose`）
- 服务器开放 80 端口（如需 HTTPS，前面加反代或用 traefik）

## 快速开始

### 1. 准备环境变量与 secrets

```bash
# 非敏感配置（CORS、邮件账号、功能开关等）
cp .env.docker.example .env

# 敏感密钥（推荐用 Docker secrets，OWASP Rule #12）
cp secrets/secret_key.txt.example secrets/secret_key.txt
cp secrets/field_encryption_key.txt.example secrets/field_encryption_key.txt
cp secrets/mail_password.txt.example secrets/mail_password.txt

# 文件权限收紧到 600（仅属主可读，CIS §4.10 / OWASP #12）
chmod 600 secrets/*.txt
```

编辑 secrets 文件（**文件内容只能是密钥值本身**，不带引号、不带换行、不带 `#` 注释）：

| 文件 | 说明 | 生成方式 |
|------|------|----------|
| `secrets/secret_key.txt` | JWT 签名密钥 | `openssl rand -hex 32` |
| `secrets/field_encryption_key.txt` | 银行卡字段加密密钥 | `openssl rand -hex 32` |
| `secrets/mail_password.txt` | 腾讯企业邮密码 | 企业邮箱后台 |

编辑 `.env`，修改非敏感配置：

| 变量 | 说明 | 示例 |
|------|------|------|
| `CORS_ORIGINS` | 前端正式域名 | `https://coupon.example.com` |
| `MAIL_USERNAME` | 腾讯企业邮账号 | `noreply@your-company.com` |
| `WELFARE_DOMAIN` | HTTPS 域名（Caddy 用） | `coupon.example.com` |

> **密钥优先级**：`SECRET_KEY`、`FIELD_ENCRYPTION_KEY`、`MAIL_PASSWORD` 优先从 Docker secrets 读取（`/run/secrets/<name>`），`.env` 中的同名值作为后备。secrets 文件不存在时自动回退到 `.env`。

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

## Secrets 管理

生产环境敏感密钥通过 Docker secrets 注入（OWASP Docker Rule #12），不直接写进 `.env` 或环境变量。

### 工作原理

```
secrets/secret_key.txt  ──compose secrets──►  /run/secrets/secret_key  ──►  pydantic-settings
```

1. `docker-compose.yml` 顶层 `secrets:` 块定义三个密钥文件
2. compose 把文件挂载到容器内 `/run/secrets/<name>`（tmpfs，不入镜像层）
3. 后端通过 `SECRETS_DIR=/run/secrets` 启用 pydantic-settings 原生 secrets 读取
4. 优先级：Docker secrets > 环境变量 > `.env` 文件 > 默认值（`settings_customise_sources` 自定义）

### 密钥文件格式

文件内容**只能是密钥值本身**：

```bash
# 正确
echo -n "$(openssl rand -hex 32)" > secrets/secret_key.txt

# 错误（pydantic 会把注释/变量名读进值）
echo "# JWT 密钥" > secrets/secret_key.txt
echo "SECRET_KEY=abc123" > secrets/secret_key.txt
```

### 文件权限

Linux 部署时务必收紧权限到 600（仅属主可读），符合 CIS §4.10 / OWASP #12：

```bash
chmod 600 secrets/*.txt
ls -l secrets/   # 验证：-rw------- 1 deploy deploy ...
```

> Windows NTFS 无 Unix 权限位概念，Docker Desktop 会按文件 ACL 处理；Linux 服务器部署必须执行。

### Windows 部署生成密钥

Windows 无原生 `openssl`，可选以下方式之一：

```powershell
# 方式 1：用 Docker 内的 openssl
docker run --rm python:3.12.7-slim sh -c "openssl rand -hex 32" > secrets\secret_key.txt
# 注意：以上命令末尾会带 CRLF，需用 Set-Content -NoNewline 重新写
Set-Content -NoNewline -Path secrets\secret_key.txt -Value (docker run --rm python:3.12.7-slim sh -c "openssl rand -hex 32")

# 方式 2：用 Python 内置 secrets 模块
python -c "import secrets; print(secrets.token_hex(32), end='')" | Set-Content -NoNewline secrets\secret_key.txt
```

### 与 .env 的关系

`.env` 仍保留 `SECRET_KEY`、`FIELD_ENCRYPTION_KEY`、`MAIL_PASSWORD` 作为：
- 非 secrets 部署模式的后备（如裸机部署、本地开发）
- secrets 文件不存在时的回退

生产部署推荐：secrets 文件存真实密钥 + `.env` 中保留占位符（被 secrets 覆盖）。

### 轮换密钥

1. 生成新密钥：`openssl rand -hex 32`
2. 更新 secrets 文件：`echo -n "新密钥" > secrets/secret_key.txt`
3. 重启 api：`docker compose restart api`
4. 已签发的 JWT 仍有效至过期（如需立即失效，缩短 `ACCESS_TOKEN_EXPIRE_MINUTES`）

> `FIELD_ENCRYPTION_KEY` 轮换时，旧密文需用 `FIELD_ENCRYPTION_KEY_PREVIOUS` 解密。MultiFernet 会自动用旧密钥解密、新密钥加密。

## 安全清单

### 镜像构建（CIS §4）

- [x] `# syntax=docker/dockerfile:1` 锁定 BuildKit 前端
- [x] 多阶段构建（builder → runtime）
- [x] 基础镜像固定 patch 版本（`python:3.12.7-slim`、`nginxinc/nginx-unprivileged:1.27-alpine`）
- [x] 非 root 用户（后端 `USER app` uid 1001；前端 nginx-unprivileged uid 101）
- [x] OCI 标准 LABEL（`org.opencontainers.image.*`）
- [x] setuid/setgid 位清理（CIS §4.8）
- [x] HEALTHCHECK 已配置
- [x] `.dockerignore` 排除敏感文件
- [x] BuildKit cache mount（pip/npm/apt 缓存跨构建复用，Docker 官方 best practice）
- [x] `COPY --link` 快照拷贝（避免源码变更破坏后续层缓存）

### 容器运行时（CIS §5 / OWASP）

- [x] `security_opt: no-new-privileges:true`
- [x] `cap_drop: ALL` + 最小 `cap_add`（仅 redis 的 SETUID/SETGID）
- [x] `read_only: true` + tmpfs（api/web）
- [x] `pids_limit: 100` + `mem_limit` + `memswap_limit`（禁 swap）
- [x] `cpus` 限制
- [x] `init: true`（tini 作 PID 1）
- [x] `ulimits: nofile/nproc`
- [x] `restart: on-failure:5`（防循环重启）
- [x] 网络分段（frontend-net / backend-net）

### 密钥管理（OWASP Rule #12）

- [ ] secrets 文件已创建并填入真实密钥（非占位符）
- [ ] `SECRET_KEY` 长度 ≥ 32（`secret_is_insecure: False`）
- [ ] `FIELD_ENCRYPTION_KEY` 已设置（独立于 SECRET_KEY）
- [ ] secrets 文件权限 600（`chmod 600 secrets/*.txt`）

### 生产配置

- [ ] `APP_ENV=production`
- [ ] `OPENAPI_ENABLED=false`
- [ ] `SEED_DEMO_ACCOUNTS=false`
- [ ] `CORS_ORIGINS` 填正式域名，非 `*`
- [ ] `CORS_ALLOW_LAN=false`
- [ ] HTTPS 已配置（Caddy 或外部 Nginx）
- [ ] 数据库备份已配置（见 `docs/backup-restore.md`）
- [ ] 服务器防火墙仅开放 80/443

### 供应链安全（OWASP Rule #13）

- [x] CI hadolint 静态检查
- [x] CI trivy HIGH/CRITICAL 扫描
- [x] CI SBOM（SPDX JSON）生成
- [x] CI cosign keyless 签名（push to main 时自动签名 GHCR 镜像）
- [x] 部署端 `cosign verify` 校验脚本（`scripts/verify-image-signature.sh`）
- [ ] 部署执行 `verify-image-signature.sh` 完成首次校验

### 部署前校验签名

用 `scripts/verify-image-signature.sh` 校验 GHCR 镜像未被篡改（自动解析 tag → digest，按 digest 校验）：

```bash
# 安装 cosign: https://github.com/sigstore/cosign#installation
REPO=your-org/your-repo  # 替换为实际仓库（GitHub Actions 中 ${{ github.repository }}）

# 校验 api 镜像（latest tag 或 sha256 digest）
bash scripts/verify-image-signature.sh $REPO api latest

# 校验 web 镜像
bash scripts/verify-image-signature.sh $REPO web latest

# 校验固定 digest（推荐：部署前先用 digest 锁定，避免 tag 被替换）
bash scripts/verify-image-signature.sh $REPO api sha256:abc123def456...
```

脚本流程：
1. 若 ref 是 tag，自动用 `docker buildx imagetools` / `skopeo` / `crane` 解析为 digest
2. 调用 `cosign verify` 用 GitHub OIDC identity + Fulcio CA 校验签名
3. 校验通过返回 0，失败返回非零（可作为 CI 部署门禁）
