# 发布验收包 v1.5.0

发布日期：2026-09-06 · 发布负责人：____ · 修复窗口：____

## 1. 版本与制品

| 项 | 值 | 校验方式 |
|---|---|---|
| 应用版本 | **1.5.0**（前后端同批） | `frontend/package.json` / `GET /api/health`（开发环境） |
| 迁移 head | **`d8f2a06c4b11`**（activation_tokens / email_outbox，T15） | `alembic heads`；`/api/ready` 的 `checks.schema_head` |
| 后端测试 | 195 passed，18 skipped | `cd backend && .venv/bin/python -m pytest tests/ -q` |
| 前端构建 | 通过 | `cd frontend && npm run build` |
| 前端 E2E | 12 用例全绿 | `cd frontend && npm run e2e` |
| 密钥扫描 | 退出 0 | `python3 scripts/scan_staged_secrets.py --tree` |

本次发布包含的破坏性/结构性变更（前后端已同批升级，无需灰度兼容）：

- `GET /coupons/my` 响应由数组升级为 `Page{total, items}`（T18）。
- `POST /imports/{id}/execute` 响应移除 `default_password`，新增
  `credentials` / `email_queued` / `smtp_unconfigured`（T15）。
- `POST /coupons/redeem` 支持 `Idempotency-Key` 头（可选，不带行为不变）。
- 新增公开端点 `POST /auth/activate`、探针 `GET /api/ready`、超管端点
  `GET|POST /api/outbox…` 与 `GET /api/metrics`。

## 2. 升级前置条件

1. **数据库账号**：确认 `welfare_app`（仅 DML）/ `welfare_migrate`（发布期 DDL）/
   `welfare_backup`（只读）三账号存在且权限最小化（T09 起；历史 ALL 权限
   `welfare` 账号必须删除）。
2. **迁移先行**：升级前先以迁移账号执行迁移（应用启动会做只读 schema 校验，
   版本落后直接拒绝启动）：
   ```bash
   MIGRATE_DATABASE_URL='mysql+pymysql://welfare_migrate:…@127.0.0.1:3306/welfare?charset=utf8mb4' \
     bash deploy/migrate-release.sh
   ```
3. **配置键**：在 `backend/.env` 补充（详见 `.env.example`）：
   - `PUBLIC_BASE_URL=https://你的域名`（**必须**——激活邮件链接指向它，未配置用户无法激活）；
   - `ACTIVATION_TOKEN_EXPIRE_HOURS` / `OUTBOX_POLL_SECONDS` / `OUTBOX_BATCH_SIZE` / `OUTBOX_MAX_ATTEMPTS`（有默认值，可不配）。
4. **SMTP**：导入名单含邮箱并勾选"发送激活邮件"前，确认 SMTP 已配置（`/api/metrics` 的 `outbox_backlog.queued` 持续增长即提示未投递）。
5. **前端构建**：`npm ci && npm run build`，Nginx root 指向新 `dist/`。

## 3. 部署步骤（升级既有环境）

```bash
# 1) 备份（失败即停）
BACKUP_DATABASE_URL='…welfare_backup…' bash deploy/backup-mysql.sh
# 确认 /opt/welfare/backups/last-backup-status.json ok=true

# 2) 发布迁移（迁移账号）
MIGRATE_DATABASE_URL='…welfare_migrate…' bash deploy/migrate-release.sh

# 3) 更新代码 + .env（PRESERVE_ENV=1 保留既有配置）+ 前端构建
sudo -E bash deploy/remote-deploy.sh   # 或按 install-ubuntu.sh 升级流程

# 4) 重启并验收
systemctl restart welfare-api
curl -s http://127.0.0.1:19001/api/health   # 200 {"status":"ok"}
curl -s http://127.0.0.1:19001/api/ready    # 200 {"status":"ready",…}
bash deploy/verify-prod.sh https://你的域名  # 可选：接口/页面探测（ADMIN_PASS 注入）
```

## 4. 失败退出与回退路径

| 失败场景 | 现象 | 处置 |
|---|---|---|
| 迁移失败中断 | `migrate-release.sh` 退出非 0；应用启动报"迁移版本落后"拒绝启动 | 修正后重跑 `alembic upgrade head`（幂等）；必要时 `alembic downgrade` 到发布前 revision 后回滚代码 |
| schema 校验失败 | worker 启动即退出，日志提示缺表/缺列 | 确认迁移已执行到 `d8f2a06c4b11`；不要用运行账号手补 DDL |
| 数据库失效 | `GET /api/ready` 503（liveness 仍 200） | 检查 MySQL；恢复后 readiness 自动恢复 |
| 新版业务异常需回滚 | — | 先 `bash deploy/backup-mysql.sh` 留存现状 → `alembic downgrade <上一 revision>` → 回滚代码到上一 tag → `systemctl restart welfare-api`。**回滚到 T15 之前版本会丢失 activation_tokens/email_outbox 表的兼容**（旧版本代码不读这两张表，数据保留无害） |
| 备份失败 | `last-backup-status.json` ok=false；cron 日志 `/var/log/welfare-backup.log` | 排查 `BACKUP_DATABASE_URL`/磁盘空间；修复后手动重跑 |

数据库整体恢复（灾难场景）按 `deploy/README.md`「备份与恢复」执行：
`restore-mysql.sh` 对账 PASS 后切换连接串，`.env`（含 `FIELD_ENCRYPTION_KEY`）
必须与库成对恢复。

## 5. 风险说明

- **激活邮件依赖 SMTP + PUBLIC_BASE_URL**：两者任一缺失，导入的邮箱用户无法
  自助激活（账号占位密码随机不可知，不存在弱口令风险；管理员可改用"关闭
  通知"导入拿到一次性个人凭证，或修复配置后 outbox 自动补发）。
- **`/coupons/my` 结构变更**：若有外部脚本直接消费该接口的数组结构需同步
  修改（本仓库内前后端与 e2e 已同批更新）。
- **git 历史凭据泄露**（历史遗留，见 `deploy/README.md` 凭据轮换章节）：
  上线后继续推进轮换证据收集，属于独立运维动作。
- **观察窗口**（发布后 7 天，见 `docs/开发计划.md` T23 条款 5）：
  - `GET /api/metrics`：`redeem_results` 失败分布（`already_used` 应主要来自
    商家重复扫码）、`errors_5xx_total` 增速、`latency_buckets` 尾部（≥3s 占比）；
  - `outbox_backlog.queued` 归零速率与 `failed` 计数；
  - 401 突增（会话版本/激活改密相关的异常失效）；
  - 兑换失败与首次激活成功率。

## 6. 角色验收清单（staging 实机执行）

- [ ] 四角色登录（admin / issuer / merchant1 / youth1）；issue_admin 直输
      `/admin/accounts`、`/admin/audit` 被守卫弹回
- [ ] 导入向导：上传含邮箱/无邮箱混合名单 → 预检 → 执行 → 邮箱用户收激活
      链接、无邮箱用户看到一次性凭证 → 用户激活后登录并强制改密过 → 再登录
- [ ] 激活链接重放/过期被拒（复点同一链接提示"已被使用/已过期"）
- [ ] 发券 → 用户出码（断网模拟：飞行模式 10s 恢复后自动重签；切后台 1 分钟
      回来倒计时自动校准）→ 商家扫码核销 → 用户端立即显示成功
- [ ] 商家核销断网模拟：确认核销后断网 → 「结果确认中」→ 恢复后"查询结果"
      得到确定性结论；同券重复核销被拒且不产生重复流水
- [ ] 批量发券部分成功：失败用户保留选中、逐条原因可见
- [ ] 导出（用户/券/流水）与列表筛选一致；时长展示统一两位小数
- [ ] 手机 390×844 与 360×800：出码、扫码、核销、兑换无重叠；页面切换后无
      残留摄像头/轮询
- [ ] `/api/ready` 在停库场景 503、恢复后 200（验收 T22）

## 7. 交付物索引

| 文档 | 内容 |
|---|---|
| `README.md` | 快速启动、演示账号、已实现能力、配置键 |
| `PRODUCT.md` | 业务资格行为矩阵、导入歧义约定 |
| `deploy/README.md` | 部署、账号拆分、备份恢复、安全清单、凭据轮换 |
| `docs/security-ops.md` | Cookie 方案、验证码、激活与 outbox 语义（7f 节）、扫描工具 |
| `docs/开发计划.md` | T00–T22 实施记录与检查表 |
| `log.md` | 逐批修改日志（文件/行为/验证命令/实际结果） |
| `HANDOFF.md` | 交接状态、工作区注意事项、后续顺序 |
