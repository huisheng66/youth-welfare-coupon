# 代码修改日志

## 2026-09-02

### 1. 修复生产环境邮箱验证码泄露

- 修改 `backend/app/services/mail.py:182-183`：只有非生产环境且启用控制台模式时才返回 `debug_code`；生产环境即使误配置 `MAIL_CONSOLE=true` 也不会把验证码放进 HTTP 响应。
- 修改 `deploy/install-ubuntu.sh:121-122`：生产安装模板将 `MAIL_CONSOLE` 默认设为 `false`，并补充配置说明注释。
- 修改 `backend/tests/test_email_code.py:89-111`：新增生产环境验证码不回传回归测试，并在 `:12` 增加 `unittest.mock` 导入。
- 验证：`backend/.venv/Scripts/python.exe -m pytest tests/test_email_code.py -q`，9 passed。

### 2. 将首次改密限制下沉到后端

- 修改 `backend/app/core/deps.py:14-21`：增加允许首次改密账号访问的认证接口白名单，并写明该限制不能只依赖前端路由。
- 修改 `backend/app/core/deps.py:53`：`get_current_account` 在账号仍标记 `must_change_password` 时拒绝其它业务接口，返回 403。
- 修改 `backend/tests/test_authz.py:304-337`：新增回归测试，验证初始密码账号不能访问商家业务接口，完成改密后恢复访问。
- 验证：`backend/.venv/Scripts/python.exe -m pytest tests/test_authz.py -q`，14 passed；存在既有依赖弃用和 HMAC 密钥长度 warning。

### 3. 防止已核验身份资料绕过复核

- 修改 `backend/app/schemas/user.py:11-48`：资料更新字段改为可选，支持安全的部分字段更新，避免未提交字段被默认空值覆盖。
- 修改 `backend/app/api/users.py:186-216`：检测姓名、学号、组织变更；已核验用户变更后自动转为 `pending`、创建新的待审核记录并写入审计日志。
- 修改 `backend/tests/test_authz.py:339-363`：新增回归测试，确认已核验资料变更不能继续保持 `approved`。
- 验证：`backend/.venv/Scripts/python.exe -m pytest tests/test_authz.py tests/test_security_hardening.py -q`，43 passed；存在既有依赖弃用和 HMAC 密钥长度 warning。

### 4. 密码变更后立即废止旧会话

- 修改 `backend/app/models/entities.py:66-67`：为账号增加 `session_version`；密码变更时递增，令牌携带签发版本。
- 修改 `backend/app/core/deps.py:53-56,79-80`：认证依赖在强制改密校验前比对令牌 `sv` 与账户版本；旧 Cookie、Bearer token 及不含版本的历史令牌均返回 401。
- 修改 `backend/app/api/auth.py:294-296,329-332,466-469,543-546`：登录令牌写入 `sv`；邮箱重置、本人改密、管理员重置均递增版本，并在代码旁补充失效范围注释。
- 修改 `backend/app/core/migrate.py:284`：开发/历史 SQLite 库兼容补充 `session_version` 列。
- 新增 `backend/alembic/versions/c3e5a281d942_add_accounts_session_version.py:25-33`：生产迁移以默认 `0` 新增该列，并支持回滚删除。
- 修改 `backend/tests/test_authz.py:336-402`：覆盖首次改密、本人改密、管理员重置、邮箱重置四种路径；均验证旧令牌被拒绝，重新登录后的令牌可用。
- 验证：`backend/.venv/Scripts/python.exe -m pytest tests/test_authz.py tests/test_email_code.py -q`，27 passed；`backend/.venv/Scripts/python.exe -m alembic upgrade head --sql` 确认迁移链可生成 `accounts.session_version` DDL。保留既有 Starlette TestClient 弃用和 JWT HMAC 密钥长度 warning。

## 2026-09-05

按 `docs/开发计划.md` 实施首个工作包 T00+T07，随后完成 T04、T02、T05、T01、T03、T06（P0 安全与数据正确性）。

### T00：恢复可信的测试与开发基线

- 修改 `backend/app/core/config.py`：`Settings` 的 `env_file` 改为可用 `APP_SETTINGS_ENV_FILE` 覆盖（默认 `.env` 行为不变）。
- 修改 `backend/tests/_helpers.py`：测试进程在导入 `app.core.config` 前把 `APP_SETTINGS_ENV_FILE` 指向不存在的占位路径，断开 dotenv 对 `backend/.env`（真实 SMTP/密钥）的回退读取。
- 修改 `backend/tests/test_security_hardening.py::TestAlembicUpgradePath`：head 断言改为从 `alembic.script.ScriptDirectory.get_heads()` 推导，并实际校验 `accounts.session_version`、`must_change_password` 列存在；engine dispose 与临时目录清理移入 `finally`，消除 Windows 句柄导致的 WinError 32。
- 在 venv 补装 `requirements.txt` 已声明的 `openpyxl==3.1.5`、`python-docx==1.1.2`（Office 解析用例此前因缺依赖失败）。
- 验证：基线 4 个失败（`test_import_rejects_corrupt_office_files`、`test_import_xlsx_docx_and_gbk_csv`、`test_import_skips_email_notify_without_smtp`、`test_legacy_database_gets_post_baseline_indexes`）全部关闭。

### T07：敏感文件进入版本库的防护

- 修改 `.gitignore`：新增根 `.env`、`.env.*`（保留 `.env.example` 可追踪）、`secrets/`、`*.pem/*.key/*.p12/*.pfx`、`*backup*.sql*`、`*.dump`、`deploy/*.local.*`、`deploy/archive/`。已用 `git check-ignore` 验证：`.env`、`secrets/`、`deploy/smtp.local.sh`、`db-backup.sql` 被忽略，`backend/.env.example` 保持可追踪；未读取、未删除任何敏感文件内容。
- 新增 `scripts/scan_staged_secrets.py`：扫描暂存/指定基准差异中的疑似凭据（私钥块、AWS key、密码字面量、带凭据的数据库 URL、硬编码 SECRET_KEY 等），输出仅含「文件:行号: 规则」不回显内容；`secret-scan:allow` 行内标记用于误报豁免；`--tree` 全量模式额外排除含演示凭据夹具的 `backend/scripts/` 存量。
- 修改 `.github/workflows/security.yml` 与 `docs/ci/security.yml`（保持同步）：新增 `secret-scan` job，PR 扫描 `origin/<base>...HEAD`、push 扫描 `github.event.before` 差异，新分支退化全量扫描。
- 新增 `backend/tests/test_security_hardening.py::TestSensitiveFileGuard`：覆盖 ignore 规则、示例可追踪、扫描命中且输出脱敏、环境变量注入不报。
- 验证：`backend/.venv/Scripts/python.exe -m pytest tests/test_security_hardening.py -q`，31 passed；`python scripts/scan_staged_secrets.py --tree` 退出码 0。

### T04：邮箱验证码计数持久化与原子消费

- 修改 `backend/app/services/mail.py`：新增 `hash_email_code()`（HMAC-SHA256，服务端 SECRET_KEY 参与）；`issue_email_code` 入库存摘要、日志不再输出验证码明文、生产未配 SMTP 直接 503 fail-closed（不再“成功只写日志”）；`consume_email_code` 错误计数改原子表达式自增并独立事务 `commit` 后才返回 400（此前 flush 随请求回滚清零，可无限试码），正确码用 `WHERE used_at IS NULL` 条件更新原子消费，历史明文码兼容读取。
- 修改 `backend/app/models/entities.py`：`email_codes.code` 扩为 `String(128)` 存摘要。
- 新增迁移 `backend/alembic/versions/b7e42a9013dd_email_code_hash_storage.py`（MySQL 扩列；SQLite 长度仅为亲和性跳过）；`core/migrate.py::ensure_schema` 补 `_widen_email_code_column` 兼容开发路径历史 MySQL 库。
- 修改 `backend/tests/test_email_code.py`：生产无 SMTP 断言 fail-closed；新增摘要入库、HTTP 连错 5 次后锁定且 attempts 持久化、双会话并发消费单胜者用例。
- 验证：`backend/.venv/Scripts/python.exe -m pytest tests/test_email_code.py tests/test_authz.py -q` 全部通过。

### T02：门店范围隔离

- 修改 `backend/app/api/merchants.py`：`list_merchants` 对 merchant 角色强制 `Merchant.id == account.merchant_id`（未绑定返回空页，query 参数不可覆盖）；`get_merchant` 对他店对象统一 404，不暴露他店联系资料。
- 核对券列表、核销流水、导出、商家仪表盘已有范围过滤：merchant 分支均以 `account.merchant_id` 限定；新增测试确认 `merchant_id` 查询参数不能扩大范围。
- 新增 `backend/tests/test_merchant_scope.py`：覆盖本店列表锁定、他店详情 404、未绑定账号空结果、券与流水筛选不可越权，5 passed。

### T05：认证状态与密码生命周期闭环（后端）

- 修改 `backend/app/api/auth.py`：本人改密、管理员重置、邮箱重置三处 `session_version` 递增改数据库原子表达式（并发改密不丢递增）；`set_account_active` 停用时同步递增版本废止旧会话，重新启用后必须重新登录；登录响应体 access_token 仅在 `AUTH_ALLOW_BEARER` 开启时返回，Cookie 专用模式不再泄露可读 token。
- 新增 `backend/tests/test_authz.py` 用例：停用→旧会话 401→重新启用→旧会话仍 401→重新登录可用；Cookie 专用模式响应体无 token 且 Cookie 会话可用。

### T05：认证状态前端闭环

- 新增 `frontend/src/authState.js`：reactive 状态 + `clearAuthState()` 同步清理本地缓存；storage 事件多标签页同步退出（不传输 token）。
- 修改 `frontend/src/auth.js`：登录/退出统一走 authState；新增 `ensureAuthReady()`——启动时用 `/auth/me` 验证 Cookie 有效性，失效即清理，进程内只执行一次。
- 修改 `frontend/src/api.js`：401 拦截器改调 `clearAuthState()` 并 `router.replace` 到登录页，消除“reactive 状态残留导致守卫重定向回受保护页”的循环。
- 修改 `frontend/src/router/index.js`：守卫 `await ensureAuthReady()`，过期 Cookie 与残留缓存不再放行业务路由。
- 修改 `frontend/src/views/Settings.vue`：改密成功后 `clearAuthState()` + `replace('/login')`（移除在已废止会话上调用 `refreshAccount()` 的流程）；首次改密期间隐藏绑定邮箱表单，避免触发后端 403。
- 验证：`cd frontend && npm run build` 通过（7.6s）。

### T01：动态券码成为唯一常规核销凭证

- 修改 `backend/app/services/live_code.py`：动态码载荷删除永久 `code`，必要 claim（`exp/cid/uid/typ`）用 `options.require` 强制存在。
- 修改 `backend/app/api/coupons.py`：`_resolve_coupon_by_code` 仅接受动态码；预览改 `POST /coupons/preview`（body 传输凭证，不进访问日志 query）并拒绝永久码；`/redeem` 拒绝永久码（失败留痕 `invalid_live_code`）；`LiveCodeOut` 移除 `permanent_code`，出码响应不再返回永久编号。
- 前端：用户券码弹窗移除“备用永久码”展示（保留复制动态码路径）；商家核销页预览改 POST、删除永久券码展示行。
- 测试：`test_redeem_with_permanent_code_success` 改为拒绝用例；`test_void_used_coupon_fails`、`test_redeem_already_redeemed_fails`、`test_redeem_expired_coupon_fails`、`test_redeem_wrong_merchant_fails`、动态码相关用例全部改走真实动态码。
- 兼容说明：发布需前后端同步升级；旧动态码（含永久 code 字段）最长存活 `LIVE_CODE_EXPIRE_SECONDS`（默认 30 秒），此后自然失效；核销接口不会回落永久码。

### T03：时长余额与账本一致

- 修改 `backend/app/services/points.py`：`apply_points` 在条件原子 UPDATE 后于同一事务内 `db.refresh(acc)` 重读余额，`balance_after` 取本次变更后的真实串行值（原实现用旧读数计算，交错时账本与余额不符）；`get_or_create_account` 用 savepoint 包裹首次开户，处理唯一约束竞争。
- 修改 `backend/app/api/points.py`：兑换先建券实例 `flush` 取 id，账本 `ref_id` 关联实际券而非模板，扣减失败整事务回滚；新增只读 `GET /points/reconcile`（管理员）对比账户余额与账本变更之和，输出异常账户清单，不改写数据。
- 新增 `backend/tests/test_points.py` 用例：10→+5→-2 场景末条账本 `balance_after == 13.00` 且逐条等于变更累计；兑换账本指向券实例；对账发现人为差异且不回写；并发首次开户仅一条账户、两笔入账均入账本。

### T06：券状态竞争与失败核销记录

- 修改 `backend/app/models/entities.py`：`redemption_logs` 增加 `reason` 列（稳定原因码）；新增迁移 `backend/alembic/versions/cf60b31a7e22_redemption_logs_reason.py`；`ensure_schema` 兼容补列。
- 修改 `backend/app/api/coupons.py`：核销条件更新把 `status == unused` 与 `expires_at > now` 一并放入 WHERE（临界过期由数据库判定）；作废改条件更新，与核销竞争仅一方成功；失败核销统一经 `_log_failed_redeem` 独立事务写 `redemption_logs`，原因码含 `already_used/voided/expired/wrong_merchant/invalid_live_code/state_conflict`，跨店失败不落他店用户标识；门店停用统一阻止预览与核销；`RedemptionLogOut` 返回 `reason`（历史失败行为 `legacy_unknown`）。
- 新增 `backend/tests/test_redemption_race.py`：同店双操作员并发核销仅一成功且仅一条成功流水；作废与核销竞争单胜者且终态一致；门店停用拦截预览/核销且券状态不变。

## 2026-09-05（第二批：T08–T10、T20 与审查报告 F01–F05 修复）

实施 `docs/开发计划.md` 的 T08（迁移与 worker 启动分离）、T09（数据库账号权限拆分）、
T10（备份恢复与回退）、T20（MySQL 并发回归），并修复 `docs/审查报告-2026-09-05.md` 的
全部 5 个问题。验证环境：本地临时 MySQL 8.4.8 实例（一次性 datadir、随机回环端口
33307、root 空密码、REPEATABLE-READ），未连接任何业务库；`MYSQL_TEST_URL` 未设置时
MySQL 用例自动跳过，CI 已配置 mysql:8.4 service 常驻运行。

### F01 [P1] 临界过期不再覆盖已核销终态

- 修改 `backend/app/api/coupons.py`：删除 `_maybe_expire()`（旧 ORM 对象盲写 expired），
  新增 `_transition_expired()`——`WHERE status = unused AND expires_at <= now` 的数据库级
  条件更新；预览、出码、核销、作废四个入口统一替换。
- 补测 `tests/test_mysql_concurrency.py::test_redeem_after_stale_read_keeps_used`：
  旧会话读券 → 另一会话真实核销成功 → 旧会话时钟推进后调用作废 → 断言终态保持
  `used`、成功流水唯一、作废被拒。

### F02 [P1] 验证码消费与错误计数统一原子资格边界

- 修改 `backend/app/services/mail.py::consume_email_code`：正确码消费与错误计数自增
  都改为条件更新，资格条件（未消费 + 次数未达上限，消费另加未过期）由数据库判定；
  未命中时通过锁定读（当前读）分类拒绝原因（`_locked_code_detail`），不再在 Python
  中依据读取快照放行。
- 补测：`test_locked_code_cannot_be_consumed`（读取 attempts=4 后他人推到 5，正确码
  必须被拒且次数已达上限）、`test_concurrent_consume_single_winner_mysql`（真实双连接
  并发消费单胜者）。

### F03 [P1] MySQL 首次开户冲突后使用当前读恢复

- 修改 `backend/app/services/points.py::get_or_create_account`：唯一约束竞争后改用
  `with_for_update()` 锁定读重查（MySQL RR 下普通 SELECT 走旧快照看不到已提交胜者；
  SQLite 忽略 FOR UPDATE 行为不变），不再把竞争失败当成 500。
- 补测 `test_first_account_race_single_row`：两独立连接 + Barrier 并发首次开户，
  仅一条账户、两笔账本、余额 3.75、无异常。

### F04 [P2] 密钥扫描覆盖项目实际凭据格式

- 修改 `scripts/scan_staged_secrets.py`：数据库 URL 规则覆盖带驱动 scheme
  （`mysql+pymysql://`、`postgresql+psycopg2://` 等）；密码变量规则补充 `pass`
  （`SSH_PASS`/`DB_PASS`）；区分字面量与环境变量引用（`${VAR}`/`$VAR`）与文档占位符
  （password/密码/你的密码 等不算命中），输出保持脱敏。
- 补测：`test_secret_scan_covers_project_credential_formats`（两类合成凭据均命中且不
  回显）、`test_secret_scan_exit_codes_as_gate`（临时 git 仓库子进程验证退出码：
  干净 0 / 命中 1，验证门禁本身而非仅正则函数）。

### F05 [P2] 门店停用核销拒绝留痕

- 修改 `backend/app/api/coupons.py::redeem`：门店存在但停用时，先经 `_log_failed_redeem`
  持久化 `merchant_inactive` 失败流水再拒绝；账号未绑定/门店缺失等无法满足外键的情况
  单独走结构化日志（`coupon.redeem.rejected`），不插入无效外键。
- 补测 `test_redemption_race.py::test_inactive_store_blocks_preview_and_redeem`：拒绝
  状态、失败原因、归属门店/操作者、不落他店用户标识、券保持 unused。

### T08：发布迁移与 worker 启动分离

- 修改 `backend/app/core/migrate.py`：新增 `verify_schema_current()`（只读校验
  alembic_version==head + 关键列存在）；`run_alembic_upgrade()` 在 stamp 前执行
  `_precheck_legacy_for_baseline()`（缺业务表的历史库拒绝标记 baseline）；新增
  `get_migration_head()`。
- 修改 `backend/app/main.py`：生产 lifespan 只调用 `verify_schema_current()`（版本落后
  或缺列直接启动失败，不执行 DDL）；开发环境保留 create_all + ensure_schema。
- 新增 `deploy/migrate-release.sh`：发布期迁移入口，`MIGRATE_DATABASE_URL` 或离散
  `MIGRATE_DB_*` 变量注入迁移账号凭据；已到 head 幂等跳过；迁移后自动校验 schema。
- 新增 `tests/test_mysql_migration.py`（6 用例）：空库升级幂等、baseline 时代历史库
  stamp+升级、缺表历史库拒绝（且未创建任何表）、缺 `session_version` 列时 worker 校验
  拒绝且不偷补列、正常库校验通过、无 alembic_version 库拒绝。
- 修改 CI（`.github/workflows/security.yml` 与 `docs/ci/security.yml` 同步）：backend-tests
  增加 mysql:8.4 service 并导出 `MYSQL_TEST_URL`，T08/T20 套件在 CI 真实运行。

### T09：数据库账号权限拆分

- 重写 `deploy/setup-mysql.sql`：`welfare_app`（DML）/`welfare_migrate`（DDL）/
  `welfare_backup`（SELECT+LOCK TABLES+SHOW VIEW+EVENT+TRIGGER+全局 SHOW_ROUTINE），
  全部仅 `localhost`；删除 `'%'` 账号；遗留 ALL 权限账号的清理语句以注释提供。
- 修改 `deploy/install-ubuntu.sh`：三账号分别生成密码；运行 .env 使用 welfare_app；
  迁移步骤改为 `deploy/migrate-release.sh`（迁移账号）；cron 注入 `BACKUP_DATABASE_URL`
  （备份账号，chmod 600）；检测到遗留 `welfare` 账号时输出人工清理提示。
- 演练（临时 MySQL 实例）：welfare_app 执行 CREATE TABLE → `ERROR 1142` 拒绝；
  welfare_migrate 执行 `migrate-release.sh` 全链升级至 `cf60b31a7e22` 并通过 schema
  校验，重复执行幂等跳过；welfare_backup 可 mysqldump、无写权限。

### T10：备份加固与恢复演练

- 重写 `deploy/backup-mysql.sh`：结构化解析（支持无显式端口、URL 编码密码、空密码字段
 不错位）；密码经 `MYSQL_PWD` 环境变量传递；`--no-tablespaces` 消除受限账号 PROCESS
 依赖；先写临时文件，gzip 完整性 + `CREATE TABLE` 计数校验通过后原子改名发布；
  失败不发布、不清理，退出码非 0。
- 新增 `deploy/restore-mysql.sh`：恢复指定备份到隔离库并校验（11 张业务表、账户/券/
  流水行数、券状态分布、余额=账本求和），任何不一致退出码非 0。
- 演练（同一临时实例）：welfare 轮询数据备份（12 表，含演练券行）→ 恢复至新建
  `welfare_restore` 库 → 校验 PASS（余额与账本一致）；失败路径实测：库名错误、备份
  账号无授权库、空转储（无 CREATE TABLE）三种情况均拒绝发布且不清理。
- 更新 `deploy/README.md`：三账号说明、迁移入口、备份失败保护、恢复脚本用法。

### 二次审查 F06/F07 修复

#### F06 [P1] MySQL 测试夹具自动供给路径修复

- 问题：`--initialize-insecure` 只创建 `root@localhost`，在 `--skip-name-resolve` 下
  从 127.0.0.1 的 TCP 连接不匹配该账户，自动供给的实例连接被拒且以 16 个 error 呈现
  （此前验证一直通过 `MYSQL_TEST_URL` 指向外部实例，未实际跑通自动供给路径）。
- 修改 `backend/tests/_mysql_fixture.py`：服务启动时经 `--init-file` 显式创建可用于
  TCP 的测试账户 `welfare_t20`（`@127.0.0.1` 与 `@localhost` 双 host），连接串改用该
  账户；端口就绪后增加连接验证，认证/连接失败转为带服务端日志尾部的明确 RuntimeError。
- 修改 `tests/test_mysql_concurrency.py` 与 `tests/test_mysql_migration.py` 的 `my`
  夹具：供给失败（任何异常）一律转 `pytest.skip`，不再以 error 呈现——与“MySQL 不可用
  时自动跳过”的文档契约一致。
- 修正 `test_first_account_race_single_row` 的断言时序假设：MySQL `created_at` 为秒
  精度 DATETIME，同一秒内的两笔账本排序不稳定，改为顺序无关断言
  （{change, balance_after} 匹配两种串行化之一，最大 balance_after == 最终余额）；
  该缺陷为测试自身假设，每笔 balance_after 的正确性不受影响。
- 验证：不设 `MYSQL_TEST_URL`，`pytest tests/test_mysql_concurrency.py
  tests/test_mysql_migration.py` 连续 3 轮 16/16 通过（自动供给 + 端到端 TCP）。

#### F07 [P2] CI 测试连接串不再被密钥扫描命中

- 修改 `.github/workflows/security.yml` 与 `docs/ci/security.yml`（同步）：CI mysql:8.4
  service 改用 `MYSQL_ALLOW_EMPTY_PASSWORD`，`MYSQL_TEST_URL` 不再包含凭据
  （`mysql+pymysql://root@127.0.0.1:33307`），健康检查去掉密码参数。
- 验证：`python scripts/scan_staged_secrets.py --tree` 退出码 0。
- 追加修复：Windows 上 mysqld 以父子进程对运行（启动器 + 实际服务），
  `Popen.terminate()` 只杀父进程导致临时实例在 pytest 退出后残留。
  `TempMySQLServer.shutdown()` 改为 `taskkill /T /F /PID` 按进程树终止
  （Linux 仍走 terminate）；两测试模块统一经 `_mysql_fixture.get_base_url()`
  共享单实例并注册 atexit 关闭。验证：pytest 结束后仅剩系统 MySQL84 服务进程，
  16/16 用例通过。

## 2026-09-05（第三批：T21 跨平台浏览器 E2E）

### T21：可重复运行的浏览器 E2E 套件

**基础设施**
- 重写 `frontend/playwright.config.js`：独立端口 19011/5199（不占用开发服务
  19001/5173）；每次运行在系统临时目录新建随机 SQLite 库（`mkdirSync` + 随机目录名，
  绝不读写开发数据）；python 按平台解析 `backend/.venv`（Windows Scripts / Linux bin，
  缺失时回退 PATH）；失败自动留 trace + 截图；`workers: 1` 串行保证种子数据链路可重复。
- `frontend/vite.config.js`：dev 端口、HMR clientPort、/api 代理目标全部可经
  `E2E_FRONT_PORT` / `E2E_BACKEND_PORT` 覆盖。
- 新增 `frontend/e2e/run-frontend.mjs`：以 chdir(真实项目根) + 继承式 cwd 启动 vite。
  原因：项目根为非 ASCII 路径时，部分 shell 会话向子进程传非 ASCII 命令行/cwd 会
  失败（spawn ENOENT），而 subst 盘符又会让 vite 模块解析与 realpath 视图错位、
  transform 全部回落为原始文件；启动器两端都规避。webServer 的 env 显式展开
  `process.env`（Windows 下覆盖式 env 丢 SystemRoot 同样报 ENOENT）。
- CI（`.github/workflows/security.yml` 与 `docs/ci/security.yml` 同步）：新增
  `frontend-e2e` job——backend venv、npm ci、playwright chromium、`npm run e2e`、
  失败上传 trace。

**用例（12 个，5 条链路）**
- core：四角色登录、错误密码提示与重试、退出登录后守卫拦截。
- redeem-flow（双会话核心链路）：管理员发券 → 用户出示动态码（真实二维码/倒计时弹窗）
  → 商家粘贴码预览 → 二次确认核销 → 用户弹窗轮询切换为「核销成功」→ 流水出现
  success 记录；作废券出示按钮禁用、列表状态已作废。
- verification：待审核区勾选 → 批量通过（ElMessageBox 确认）→ 接口断言 approved。
- exchange-flow：兑换确认弹窗 → 「稍后再说」触发刷新 → 余额 10→8、券列表 +1。
- auth-lifecycle：新建商家账号强制首改密（设置页只暴露改密表单）→ 改密后回登录页 →
  新密码登录不再受限；clearCookies 模拟会话失效 → 守卫拦回登录页。

**调试中发现并修复的环境/产品问题**
- `backend/app/core/database.py`：SQLite 连接补充 `busy_timeout=30s`（默认 0），
  多请求并发轮询+写事务时避免 `database is locked` 直接报错；对 MySQL 无影响。
- E2E 暴露的真实交互细节均已按应用实际语义断言：发券需绑定核销商家对应门店、
  批量通过与核销均有确认弹窗、兑换成功后还有「是否立即出示券码」追问、
  退出登录为异步未 await（导航语义相应调整）。
- webServer env 覆盖导致 SystemRoot 丢失、`JSON.stringify` 转义反斜杠等启动问题
  逐个排除；heredoc 写文件吃反斜杠的教训改用 Write 工具。

**验证**
- `npm run e2e`：12/12 通过，连续 3 轮（29.6s / 29.9s / 26.9s），每轮全新随机库。
- 后端全量回归（database.py 改动后）：153 passed。
- 剩余范围：真实 Android/iOS 摄像头权限与 HTTPS 信任仍按计划单独实机验收（T21 第 5 项）。

## 2026-09-05（第四批：前端体验收口 + T11 审核快照）

### 前端体验收口（未提交 polish）

- 修改 `frontend/src/auth.js`：`logout()` 先同步 `clearAuthState()` 再调后端，避免路由守卫因 token 仍在把 `/login` 弹回业务首页。
- 修改 `frontend/e2e/core.spec.js`：退出后立即断言跳转登录页。
- 管理/商家/用户壳层：侧栏图标、折叠待审红点、精确激活「首页/核销」、深色 shell 改 CSS 变量；登录/绑定邮箱验证码改为 6 位数字输入。
- 管理列表空状态改用 `EmptyState` 并补导入；商家核销页手机端把扫码提前，文案去掉永久码核销入口。
- 补 `AdminLayout` 图标 import 与各管理页 `EmptyState` import（此前模板已引用但未导入，构建会留下运行时缺口）。

### T11：审核资料快照及并发审核

- 新增 `user_profiles.profile_version`；`user_verifications` 增加身份快照、`snapshot_version`、`source`；`VerifyStatus.superseded` 仅用于申请记录。
- 新增迁移 `backend/alembic/versions/e4f8a2c1b907_verification_snapshots.py`（head）；`ensure_schema` / `REQUIRED_SCHEMA_COLUMNS` 同步。
- 新增 `backend/app/services/verifications.py`：身份变更递增版本并失效旧待审；审核用 `WHERE status=pending` 条件更新；快照版本与当前资料不一致则拒绝。
- 修改 `backend/app/api/users.py`：待审列表身份字段取申请快照（历史未知不回填当前资料）；单条审核 409 版本冲突；批量审核返回逐条 `success/already_processed/version_conflict/not_found`。
- 名单导入为已通过账号写入 `source=bulk_import` 的已审申请（含文件名与操作者）。
- 种子 youth1/youth2 写入快照，避免演示账号无来源的 approved/pending。
- 前端：资料页在自动待审时提示无需再提交；审核弹窗展示申请快照，快照与当前资料不一致时警告；批量结果区分版本冲突。

**验证**
- `pytest tests/test_verification.py tests/test_authz.py tests/test_import.py`：相关用例通过（含 7 个 T11 新用例）。
- 其余 `pytest tests/`：69 passed，17 skipped（本机未跑 MySQL；新增 `test_concurrent_review_single_winner` 随 T20 套件 skip）。
- `alembic heads` 为 `e4f8a2c1b907`；`upgrade head --sql` 含快照列 DDL。
- `npm run build` 通过（3.60s）。
- Playwright `e2e/core.spec.js` + `e2e/verification.spec.js`：7 passed（含退出立即跳转、批量通过）。

## 2026-09-06（第五批：T12 业务资格规则统一）

### T12：资格判断集中到领域服务

- 新增 `backend/app/services/eligibility.py`：账号启用/用户核验/门店启用/模板启用
  四类资格集中判定。`require_benefit_user`（角色+账号启用+核验通过，停用账号
  新增拦截）、`require_issuable_template`、`require_exchangeable_template`；
  资格异常 `EligibilityError` 是 `ValueError` 子类，批量/导入入口行级捕获不变。
  各入口核验拒绝文案为对外稳定契约（导入结果与测试断言依赖原文），按动作保留
  原措辞，仅统一判定来源。
- 修改 `backend/app/api/coupons.py`：单条/批量/名单导入三个发券入口统一走
  `require_issuable_template` + `require_benefit_user(action="发券")`，删除各入口
  散写的模板/商家/核验检查；发券写入模板快照。
- 修改 `backend/app/api/points.py`：`_grant_one`（单人/批量/名单导入共用）与
  兑换统一走资格检查；兑换目录 join Merchant 过滤停用门店（不再让用户点击后
  才发现商家不可用）；兑换券写入模板快照。
- 券实例快照：`coupon_instances` 新增 `template_name`/`template_description`
  （可空）；迁移 `a9d3e71b2c05`（head，Revises `e4f8a2c1b907`）；`ensure_schema`
  与 `REQUIRED_SCHEMA_COLUMNS` 同步；`coupon_to_out`/出码响应优先快照、历史行
  （NULL）回退模板当前值，不回填伪造历史；`seed.py` 演示券同步写快照。
- 行为矩阵写入 `PRODUCT.md`「业务资格规则」：停用账号/复核中/门店停用/模板
  停用/未标价模板 × 发券/入账/兑换/已有券 的完整矩阵与补充约定。
- 顺带修复：`test_secret_scan_exit_codes_as_gate` 子进程从裸 `python` 改为
  `sys.executable`（Linux PATH 只有 python3，此前在该环境 FileNotFoundError，
  与本次改动无关的跨平台缺陷）。

**验证**
- 新增 `tests/test_eligibility.py` 9 用例：停用账号三入口统一拒绝、复核中暂停
  新增权益但已有券可出码、目录过滤停用门店、停用门店兑换/发券拒绝且余额不变、
  模板停用只停新增（已发券出码→预览→核销全通）、快照在模板改名后保留、历史
  无快照回退、未核验用户四入口判定一致、EligibilityError 类型契约。
- `pytest tests/ -q`：153 passed，17 skipped（本机未跑 MySQL）。
- `alembic heads` 为 `a9d3e71b2c05`；`upgrade head --sql` 含快照列 DDL。
- `scripts/scan_staged_secrets.py --tree` 退出 0；`npm run build` 通过（3.60s）。

## 2026-09-06（第六批：T13 写操作幂等）

### T13：Idempotency-Key 与结果重放

- 新增 `idempotency_keys` 表（迁移 `b6c2f84a1d09`，head）：`actor_id + action +
  key` 唯一约束；仅存请求摘要（规范化 JSON 的 SHA-256）与结果 JSON，不保存
  敏感原始请求体；默认保留 7 天（`IDEMPOTENCY_RETENTION_DAYS`），
  `sweep_expired` 按 `IDEMPOTENCY_SWEEP_INTERVAL` 节流清理。
- 新增 `backend/app/services/idempotency.py`：`extract_key`（超长 400）、
  `replay`（同 key 同摘要重放原结果、不同摘要 409）、`store`（与业务写入
  同事务登记）、`commit_idempotent`（唯一约束竞争 → 败者重放胜者结果；
  胜者未提交可见时 409“处理中”）、`sweep_with_settings`。
- 七个写接口接入：发券单条/批量/名单导入（`api/coupons.py`）、时长单人/
  批量/名单导入与兑换（`api/points.py`）。导入接口请求摘要以文件内容
  SHA-256 代替原始名单。幂等记录与券/账本同一事务提交；业务 4xx 失败
  不留记录，修正后可用同 key 重发；不带 key 行为完全不变。
- 前端（`utils/idempotency.js`）：兑换（user/Points）、时长调整与导入
  （admin/Points）、单人/批量发券与名单发券（admin/Users）按“操作意图”
  生成 key 并随 `Idempotency-Key` 头发送；超时/失败保留 key 供重试复用，
  成功或重新打开弹窗生成新 key。
- 修复重构引入的缺陷：发券 `_preload_coupons` 移到 commit 前后实例主键
  （Python 端 default）尚未分配，需在收集 id 前 `db.flush()`（全量回归
  暴露，3 个既有用例失败已全部关闭）。

**验证**
- 新增 `tests/test_idempotency.py` 11 用例：发券/兑换/入账重放不重复、
  同 key 不同请求 409、操作者与动作双重隔离、失败不留痕、导入同文件
  重放不重复入账（文件变更 409）、超长 key 400、7 天保留清理、记录不含
  请求自由文本、无 key 行为不变。
- `tests/test_mysql_concurrency.py` 新增 `test_idempotent_commit_race_single_record`
  （双连接同 key 并发提交：一提交一重放、唯一记录）；本机无 mysqld 随套件
  skip，CI mysql:8.4 service 真实运行。
- `pytest tests/ -q`：164 passed，18 skipped；`alembic heads` 为
  `b6c2f84a1d09`；`npm run build` 通过（3.61s）；密钥扫描退出 0。

## 2026-09-06（第七批：T14 统一导入预检、批次与逐行结果）

### T14：预检 → 确认执行 → 批次结果

- 新增 `import_batches` / `import_rows` 表（迁移 `c7e1d95b3a10`，head）：
  批次保存类型/操作者/文件 SHA-256/参数/状态/计数；逐行保存预检与执行
  状态、失败原因、业务对象关联（ref_id）。原始文件不保留，仅存摘要；
  预检失败为终态（precheck_failed），执行失败（failed）可重试。
- 新增 `backend/app/services/imports.py`：预检不写业务数据；执行逐行
  独立事务（条件 UPDATE 领取 → 业务写入与行状态同一 commit），断点
  续执只处理未完成行；本轮失败的行下一轮才可重试（否则无限循环——
  首跑即暴露并修复）；已完成批次无失败行时幂等返回。
- 标识解析升级 `resolve_user_detailed`：用户名 → 邮箱 → 手机 → 学号
  优先级；跨字段命中不同用户或学号多命中报告歧义（旧行为静默取首个
  或返回 None）；姓名不作为唯一标识。旧 `resolve_user` 委托新实现。
- 文件内重复策略：users 按用户名/手机/邮箱、issue/points 按解析后用户，
  重复行预检即拒绝并保留首次出现（修复旧 issue-import 静默重复发券）。
- 执行时重新验证：资格/唯一冲突在每行执行时重新检查（预检不代替执行
  检查）；users 批次共用一次 bcrypt 初始密码哈希——实测单次 0.157s，
  1000 行朴素逐行 ≈157s 超请求窗口，共用哈希降到一次，同步执行可行。
- 解析加固（import_file.py）：列数上限 64、单元格 512 字符、Office
  zip 解压体积 50MB 与压缩比 100 倍快速拒绝；时长字段显式拒绝
  NaN/Infinity/零/超界。
- 新增 `api/imports.py`：`POST /imports/preview`（multipart）、
  `POST /imports/{id}/execute`（仅创建者可执行；可带文件摘要确认，
  不一致 409；users 批次返回初始密码并排队开通邮件）、
  `GET /imports/{id}`、`GET /imports/{id}/rows`（分页+状态过滤）、
  `GET /imports/{id}/rows.csv`（全部逐行明细，错误证据不截断）。
  旧三类导入端点阶段性保留。
- 前端：新增 `ImportWizard.vue`（步骤条：上传预检 → 确认执行 → 批次
  结果，含初始密码提示、重试失败行、逐行 CSV 下载）与
  `ImportErrorsTable.vue`；Users/Points 管理页三个导入入口全部切换
  到向导，删除旧导入逻辑与已无引用的 ImportResultDialog。

**验证**
- 新增 `tests/test_imports.py` 11 用例：预检不写业务数据、users 执行
  +重复执行幂等+批次共用哈希、执行时唯一冲突复检、摘要确认 409、非
  创建者 403、issue 重复/未核验/歧义预检、执行时资格复检、points
  NaN/Infinity/零/格式/重复预检、执行期失败修复后续执不重复入账、
  rows 分页与 CSV 全量、超长单元格/列数 400。
- `pytest tests/ -q`：174 passed，18 skipped（本机未跑 MySQL）。
- `alembic heads` 为 `c7e1d95b3a10`；`npm run build` 通过（3.61s）；
  密钥扫描退出 0。

## 2026-09-06（第八批：T15 账号激活与可靠邮件 outbox）

### T15：一次性激活链接 + 邮件 outbox

- 新增 `activation_tokens` / `email_outbox` 表（迁移 `d8f2a06c4b11`，head）。
- `services/activation.py`：一次性激活 token（`secrets.token_urlsafe(32)`，
  库内只存 `SECRET_KEY` 参与的 HMAC-SHA256 摘要，复用验证码同一 keyed-hash
  方案）；`consume_activation` 条件更新保证单次消费（重复点击/重放 400 且
  区分"已使用/已过期"）；激活原子写入新密码 + `must_change_password=False` +
  `session_version+1`（激活前签发的会话全部失效，与 T05 同一语义）。
- `services/outbox.py`：`enqueue` 与业务写入同事务入队（进程重启不丢待发送）；
  `send_due` 条件 UPDATE 领取（queued 到期 / 超时 sending 回收），失败按
  1/5/15/60 分钟退避，`OUTBOX_MAX_ATTEMPTS`（默认 5）后转 failed；`worker_loop`
  由 lifespan 启停（无独立队列平台）。发送成功即清空 html 字段——激活链接
  含一次性 token，不长期留库；失败任务保留正文供人工重发。
- 导入双轨（`services/imports.py` `_exec_users_row`）：
  - 有邮箱 + 开启通知：每批随机占位哈希（一次 bcrypt，明文即弃，任何已知
    密码不可登录）+ 一次性激活 token + outbox 激活邮件（正文 HTML 转义）；
  - 无邮箱 / 关闭通知：随机个人初始凭证（12 位字母数字），仅在执行响应出现
    一次，不落库不进日志；批次 CSV 不含密码列。
  删除统一初始密码路径与 `to_notify` 旧契约（旧导入端点阶段性保留原行为）。
- 接口：`POST /api/auth/activate`（公开，Pydantic 密码强度校验）、
  `GET /api/outbox`（超管，状态/计数/错误，不回正文）、
  `POST /api/outbox/{id}/resend`（仅 failed 可重置回 queued 立即投递）。
  execute 响应新增 `email_queued` / `credentials` / `smtp_unconfigured`，
  移除 `default_password`。
- 前端：`/activate` 公开落地页（token 缺失/无效/已用/过期直接进失败终态，
  成功后引导登录）；路由注册 public；`ImportWizard` 结果步骤改为"个人凭证
  一次性展示 + 激活邮件排队提示 + SMTP 未配置警告"。

**验证**

- 新增 `tests/test_activation_outbox.py` 10 用例：导入入队与占位锁定、个人
  凭证一次性返回并可登录（重复导入全拒）、激活单次消费+会话版本+新旧密码
  行为、过期/无效/弱密码拒绝、转义与库内无 token/密码明文、send_due 成功
  （正文清空、不重发）、失败退避到 failed（错误信息、next_retry 未来）、
  人工重发与超管权限、开发环境 console 模式受理。
- `tests/test_imports.py` 对齐新契约：`default_password` 不再返回，双轨断言。
- `pytest tests/ -q`：184 passed，18 skipped（本机未跑 MySQL）；
  `alembic heads` 为 `d8f2a06c4b11`；`npm run build` 通过；密钥扫描退出 0。

## 2026-09-06（第九批：T16 出码与扫码的异常恢复）

### T16：用户出码弹窗状态机 + 商家扫码/核销可靠性

- **后端**：`POST /coupons/redeem` 支持 `Idempotency-Key`（T13 机制复用）——
  成功结果（RedeemOut JSON）与核销写入同事务暂存，`commit_idempotent` 保证
  并发同 key 单胜者；响应丢失（超时）后同 key 重试重放原结果，不重复写流水；
  失败（4xx）不留记录，重试重新确定性判定。业务执行前 `db.refresh` 构建
  可重放结果。
- **用户出码弹窗**（`user/Coupons.vue` 重写状态机）：
  - 状态覆盖：加载（skeleton）→ 有效 → 刷新中（倒计时归零显示）→ 断网
    （保留未过期动态码半透明 + 手动重试）→ 已核销（成功页）→ 已作废/已过期
    （终态原因）；会话失效沿用 api.js 401 拦截器全局跳登录。
  - 倒计时按服务端 `expires_in` 重锚定 deadline（每 500ms 由 deadline 推算，
    不再每秒递减），后台节流/休眠恢复后自动对齐；`visibilitychange` 回前台
    重新同步状态并重签动态码。
  - 请求代次：开窗/切券/回前台/手动重试递增 `gen`，晚到响应按代次丢弃；
    live-code 请求带 AbortController，关窗/切券即取消。
  - 轮询单飞（in-flight 标志）+ 页面隐藏暂停 + 网络错误退避
    （1/2/4/8/10s 上限）+ 成功重置。
- **商家核销页**（`merchant/Redeem.vue`）：
  - 预览锁定 `lockedCode`：扫码/输入与预览对应同一券码才可核销；输入变化
    即清理旧预览与旧结果（修复"预览 A 后改输 B，确认弹窗显示 A 实际核销 B"
    的预览错位缺陷）。
  - 确认核销前强制重新预览（动态码可能已过期/被作废）。
  - 核销携带每意图幂等 key（超时重试复用）；超时/断网进入「结果确认中」，
    通过本店流水查询 + 同 key 重试确认，均不能确定性判定时报"核销未成功，
    请人工核对"，不把"已使用"当作本次成功。
  - 离开页面自动关闭摄像头。

**验证**

- `tests/test_idempotency.py` 新增 3 用例：核销响应丢失重放（不重复写流水）、
  失败不留痕且同 key 重试确定性失败、不带 key 行为不变。
- `pytest tests/ -q`：184 passed，18 skipped；前端 `npm run build` 通过；
  E2E 12 用例全绿（含出码→预览→核销→用户成功状态链路）；密钥扫描退出 0。
