# 青年福利券系统 — Docker 常用命令快捷方式
# 用法：make <target>，例如 make up / make logs / make shell-api
# Windows 无 make 时，可直接复制 Makefile 中对应的 docker compose 命令执行

.PHONY: help up up-prod up-dev down build rebuild logs logs-api logs-web ps \
        shell-api shell-web shell-redis health seed backup restore clean \
        up-https validate scan

# 默认目标
help: ## 显示所有可用命令
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) | \
		awk 'BEGIN {FS = ":.*?## "}; {printf "  \033[36m%-15s\033[0m %s\n", $$1, $$2}'

# ---------- 启停 ----------
up: build ## 启动开发环境（含 dev override，热重载 + 演示数据）
	docker compose up -d

up-prod: build ## 启动生产模式（不叠加 dev override）
	docker compose -f docker-compose.yml up -d

up-https: build ## 启动生产 + HTTPS（Caddy 自动 TLS，需先设 WELFARE_DOMAIN）
	docker compose -f docker-compose.yml -f docker-compose.https.yml up -d

down: ## 停止所有容器（保留数据）
	docker compose down

down-clean: ## 停止并删除数据卷（⚠️ 丢失数据库）
	docker compose down -v

# ---------- 构建 ----------
build: ## 构建镜像（如有改动）
	docker compose build

rebuild: ## 强制重新构建（无缓存）
	docker compose build --no-cache

# ---------- 观测 ----------
ps: ## 查看容器状态
	docker compose ps

logs: ## 跟踪所有容器日志
	docker compose logs -f --tail=100

logs-api: ## 跟踪 api 日志
	docker compose logs -f --tail=100 api

logs-web: ## 跟踪 web 日志
	docker compose logs -f --tail=100 web

health: ## 查看健康状态
	@echo "=== API ==="
	@curl -s http://localhost:19001/api/health 2>/dev/null || curl -s http://localhost/api/health
	@echo ""
	@echo "=== Web ==="
	@curl -s -o /dev/null -w "HTTP %{http_code}\n" http://localhost/ 2>/dev/null || echo "unreachable"

# ---------- 调试 ----------
shell-api: ## 进入 api 容器
	docker compose exec api sh

shell-web: ## 进入 web 容器
	docker compose exec web sh

shell-redis: ## 进入 redis 容器
	docker compose exec redis sh

db-shell: ## 连接 SQLite（api 容器内）
	docker compose exec api python -c "import sqlite3; c=sqlite3.connect('/app/data/app.db'); import code; code.interact(local={'c':c,'cur':c.cursor()})"

redis-cli: ## 连接 redis-cli
	docker compose exec redis redis-cli

# ---------- 数据 ----------
seed: ## 临时 seed 演示账号（生产慎用）
	docker compose exec api python -c "import os; os.environ['SEED_DEMO_ACCOUNTS']='true'; from app.seed import seed_if_empty; from app.core.database import SessionLocal; s=SessionLocal(); seed_if_empty(s); s.close(); print('SEED_DONE')"

backup: ## 备份数据库到 ./backup/
	@mkdir -p backup
	@TS=$$(date +%Y%m%d-%H%M%S); \
	docker compose exec -T api python -c "import shutil; shutil.copy('/app/data/app.db','/app/data/backup-$${TS}.db'); print('backup-$${TS}.db created')"; \
	docker compose cp api:/app/data/backup-$${TS}.db ./backup/backup-$${TS}.db; \
	echo "==> ./backup/backup-$${TS}.db"

restore: ## 恢复数据库：make restore FILE=./backup/xxx.db
	@test -f "$(FILE)" || { echo "Usage: make restore FILE=./backup/xxx.db"; exit 1; }
	docker compose cp $(FILE) api:/app/data/restore.db
	docker compose exec api sh -c "cp /app/data/restore.db /app/data/app.db"
	docker compose restart api
	@echo "==> restored from $(FILE)"

# ---------- 校验 ----------
validate: ## 校验 compose 配置语法
	docker compose config --quiet && echo "compose OK"
	@test -f .env || echo "⚠️  .env 不存在，复制：cp .env.docker.example .env"

scan: ## 镜像安全扫描（需先安装 trivy）
	@command -v trivy >/dev/null 2>&1 || { echo "请先安装 trivy：https://aquasecurity.github.io/trivy/"; exit 1; }
	trivy image welfare-api:latest --severity HIGH,CRITICAL --ignore-unfixed
	trivy image welfare-web:latest --severity HIGH,CRITICAL --ignore-unfixed

# ---------- 清理 ----------
clean: ## 删除停止的容器、悬空镜像、构建缓存
	docker container prune -f
	docker image prune -f
	docker builder prune -f

clean-all: down-clean ## 彻底清理（含数据卷，⚠️ 危险）
	docker volume prune -f
