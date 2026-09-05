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
