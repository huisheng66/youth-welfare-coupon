# 安全加固交接

更新时间：2026-09-05（第二批：T08–T10、T20 与审查报告 F01–F05）

## 已完成

`log.md` 已记录并通过对应回归测试的修改。截至 2026-09-05 第二批，除最初的四项外，
`docs/开发计划.md` 中的 T00–T10、T19（部分）、T20 已实施：

1. 生产环境不返回邮箱验证码。
2. 后端强制首次改密。
3. 已核验身份资料变更后重新审核。
4. 密码变更后立即废止旧会话。
5. T00 测试基线恢复（dotenv 隔离、迁移 head 动态断言、依赖补齐）。
6. T07 敏感文件 gitignore + 暂存/CI 密钥扫描。
7. T04 验证码 HMAC 存储、错误计数持久化、原子消费、生产 fail-closed。
8. T02 门店范围隔离（列表/详情/券/流水）。
9. T05 会话版本原子递增、停用废止会话、Cookie 专用模式、前端 clearAuthState/ensureAuthReady。
10. T01 动态码成为唯一核销凭证（预览改 POST，永久码不可核销）。
11. T03 时长账本 balance_after 与串行余额一致、兑换账本关联券实例、只读对账接口。
12. T06 核销/作废条件更新竞争、失败原因码、跨店失败脱敏、停用门店拦截留痕。
13. F01 过期转换条件更新（不覆盖并发已核销终态）。
14. F02 验证码消费/计数原子资格边界 + 锁定读分类。
15. F03 MySQL 首次开户冲突后锁定读恢复。
16. F04 密钥扫描覆盖 mysql+pymysql/SSH_PASS，退出码门禁测试。
17. F05 停用门店核销拒绝写入 merchant_inactive 失败流水。
18. T08 生产 worker 只读校验 schema；DDL 由 `deploy/migrate-release.sh`（迁移账号）发布期执行。
19. T09 `setup-mysql.sql` 三账号拆分（app/migrate/backup，仅 localhost 最小权限）。
20. T10 备份临时文件+校验+原子发布；`deploy/restore-mysql.sh` 恢复并自动对账。
21. T20 `tests/test_mysql_concurrency.py`（10 用例）与 `tests/test_mysql_migration.py`
    （6 用例）在本地临时 MySQL 8.4 全部通过；CI 已配 mysql:8.4 service。
22. F06 夹具自动供给修复：`--init-file` 创建可 TCP 连入的 `welfare_t20` 测试账户，
    供给失败一律 skip 而非 error；不设 `MYSQL_TEST_URL` 时 16 个 MySQL 用例自动
    供给临时实例并全过（连续 3 轮）。
23. F07 CI 测试实例改空 root 密码，连接串不含凭据，密钥扫描全量门禁通过。
24. T21 浏览器 E2E（部分）：Playwright 套件 12 用例（四角色/首改密/过期会话/核验/
    发券/兑换/双会话核销/错误恢复），独立端口 + 随机隔离 SQLite 库，Windows 实证
    连续 3 轮全绿；CI 新增 frontend-e2e job（失败自动上传 trace）。真实手机摄像头
    与 HTTPS 信任待实机验收。
25. SQLite 连接补 busy_timeout=30s（并发轮询+写事务下避免 database is locked）。

### E2E 运行方式

```powershell
cd D:\卡系统\frontend
npm run e2e        # 首次需 npx playwright install chromium
```

- 自动启动后端（backend/.venv，随机临时 SQLite 库，端口 19011）与前端 vite（5199），
  不占用开发服务、不读写开发数据。
- 端口可用 `E2E_BACKEND_PORT` / `E2E_FRONT_PORT` 覆盖。
- 失败时 trace 与截图在 `frontend/test-results/`（已被 gitignore）。
- `e2e/run-frontend.mjs` 的 chdir 启动器是为非 ASCII 项目根 + 特定 shell 会话的
  spawn 限制所设，常规环境同样适用，无需特殊配置。

当前迁移链 head 为 `cf60b31a7e22`。发布迁移执行方式已变更：**先**
`MIGRATE_DATABASE_URL=... bash deploy/migrate-release.sh`（迁移账号），**再**启动应用；
生产 worker 启动只做只读 schema 校验，版本落后或缺列会拒绝启动。

当前最后一次验证：

```powershell
cd D:\卡系统\backend
$env:MYSQL_TEST_URL = "mysql+pymysql://root@127.0.0.1:33307"   # 指向一次性/本地 MySQL；未设置时 MySQL 用例跳过
.\.venv\Scripts\python.exe -m pytest tests/ -q
```

结果为 153 passed（2026-09-05 全量回归含 MySQL 套件）。前端 `npm run build` 通过
（本批无前端改动）。

## 后续顺序

按 `docs/开发计划.md` 第 12 节检查表推进：

1. S3 运营增强：T11 审核快照与并发审核、T12 资格规则统一、T13 写操作幂等、
   T14 导入预检与批次、T15 激活与可靠邮件。
2. T16–T18 体验与性能、T19 剩余项（前端 build/E2E 接入、Nuclei 修复）、
   T21 跨平台 E2E、T22 健康与指标、T23 发布验收包。
3. 独立运维动作（不随代码走）：历史泄漏凭据的轮换证据收集、生产服务器实际状态核实、
   季度恢复演练（首次已演练，见 log.md 2026-09-05）。

## 工作区注意事项

- `.env` 和 `secrets/` 已加入 `.gitignore`；仍不要读取、输出、提交或删除其内容。
- `backend/alembic/versions/2c984c17c453_baseline.py` 的 git 状态为换行符噪音，内容
  diff 为空，不要提交无意义换行变更。
- 新增迁移不得重写既有已部署迁移；`2c984c17c453`→`cf60b31a7e22` 链保持原样。
- MySQL 回归用例读 `MYSQL_TEST_URL`（不含库名的根 URL）；未提供时自动供给一次性
  mysqld（`--init-file` 创建 `welfare_t20` 测试账户），供给失败自动 skip。注意 mysqld
  对非 ASCII 工作路径敏感，临时实例目录必须纯 ASCII。
- T09 起生产数据库账号拆分为 welfare_app / welfare_migrate / welfare_backup（仅
  localhost）；部署新版本必须让 `install-ubuntu.sh` 或 `setup-mysql.sql` 重建账号，
  并删除历史 ALL 权限的 `welfare` 账号。
