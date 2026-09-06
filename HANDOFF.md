# 安全加固交接

更新时间：2026-09-06（第十二批：T19 Nuclei 错误语义）

## 已完成

`log.md` 已记录并通过对应回归测试的修改。截至 2026-09-06 第十二批，
`docs/开发计划.md` 中的 T00–T19（Nuclei 部分）、T20、T21（部分）已实施：

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
21. T20 `tests/test_mysql_concurrency.py`（11 用例，含 T11 双审核竞争）与
    `tests/test_mysql_migration.py`（6 用例）；CI 已配 mysql:8.4 service。
22. F06 夹具自动供给修复：`--init-file` 创建可 TCP 连入的 `welfare_t20` 测试账户，
    供给失败一律 skip 而非 error；不设 `MYSQL_TEST_URL` 时 16 个 MySQL 用例自动
    供给临时实例并全过（连续 3 轮）。
23. F07 CI 测试实例改空 root 密码，连接串不含凭据，密钥扫描全量门禁通过。
24. T21 浏览器 E2E（部分）：Playwright 套件 12 用例（四角色/首改密/过期会话/核验/
    发券/兑换/双会话核销/错误恢复），独立端口 + 随机隔离 SQLite 库，Windows 实证
    连续 3 轮全绿；CI 新增 frontend-e2e job（失败自动上传 trace）。真实手机摄像头
    与 HTTPS 信任待实机验收。
25. SQLite 连接补 busy_timeout=30s（并发轮询+写事务下避免 database is locked）。
26. T11 核验申请保存姓名/学号/组织快照与资料版本；待审期间改资料会使旧申请
    superseded，旧决定不能批准新资料；双人审核条件更新单胜者；批量审核返回逐条
    结果；名单导入写入 `bulk_import` 来源记录。
27. 前端退出登录先清本地态；管理空状态、侧栏图标、商家扫码页手机顺序与验证码
    6 位输入已收口。
28. T12 资格规则统一：`services/eligibility.py` 集中账号/核验/门店/模板资格判定，
    发券（单条/批量/名单）与时长调整、兑换复用；停用账号新增拦截；兑换目录过滤
    停用门店；券实例保存发放时模板快照（历史行回退模板当前值）；行为矩阵见
    `PRODUCT.md`「业务资格规则」。
29. T13 写操作幂等：`idempotency_keys` 表（actor+action+key 唯一）+
    `services/idempotency.py`；发券/时长/兑换 7 接口支持 `Idempotency-Key`
    重放、同 key 不同请求 409、并发单胜者；记录与业务写入同事务、仅存摘要
    与结果、保留 7 天；前端按操作意图复用 key。
30. T14 统一导入：`import_batches`/`import_rows` 表 + `services/imports.py`
    （预检不写业务数据、逐行独立事务、断点续执只重试失败行）；`/imports`
    preview/execute/detail/rows/rows.csv 五接口；歧义解析、文件内重复拒绝、
    解析资源上限（列数/单元格/zip 防爆/NaN）；users 批次共用密码哈希；
    前端 `ImportWizard` 替换三个导入入口。旧导入端点阶段性保留。
31. T15 账号激活与可靠邮件：`activation_tokens`（HMAC 摘要、单次消费）+
    `email_outbox`（同事务入队、退避重试、人工重发，迁移 `d8f2a06c4b11`）；
    导入双轨——含邮箱用户收一次性激活链接（占位哈希随机不可知，发送成功后
    清空正文），无邮箱/关闭通知用户领一次性个人凭证；`/auth/activate` 公开
    端点 + 前端 `/activate` 落地页；`/outbox` 管理（查询不回正文 + resend）；
    统一初始密码仅旧导入端点保留。详见 `docs/security-ops.md` 7f 节。
32. T16 出码与扫码异常恢复：核销接口支持 `Idempotency-Key`（响应丢失同 key
    重试重放原结果，不重复写流水；失败不留痕）；用户出码弹窗状态机（加载/
    有效/刷新中/断网/终态全覆盖，倒计时服务端校准、visibilitychange 重同步、
    请求代次防晚到响应、轮询单飞+隐藏暂停+退避）；商家页预览锁定（输入与
    预览一致才可核销）、确认前重新预览、超时「结果确认中」（流水查询+同 key
    重试，不把"已使用"当本次成功）、离开页面关摄像头。
33. T17 管理员高频操作完整性：/admin/accounts、/admin/audit 路由补超管
    约束（守卫取最深 roles，与菜单/后端三层一致）；formatHours 统一两位
    小数；/export/users 补 q 搜索与列表筛选一致；发券/批量发券/时长/作废
    确认补齐对象/数量/商家/影响 + 按钮 loading 防重（幂等键兜底）；批量
    弹窗注明仅当前页选中、部分成功列出失败用户与原因且保留选中便于续处。
34. T18 状态查询、分页与统计口径：单券轻量状态端点（弹窗轮询成本 O(1)）；
    /coupons/my 升级 Page{total,items} 分页（前后端同批），待办 limit；
    services/biztime.py 统一 Asia/Shanghai 划日（仪表盘今日 + 导出区间）；
    构建分析入口 npm run analyze（两种写法兼容）。

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

当前迁移链 head 为 `d8f2a06c4b11`（`c7e1d95b3a10` 之后新增 activation_tokens/email_outbox）。发布迁移执行方式已变更：**先**
`MIGRATE_DATABASE_URL=... bash deploy/migrate-release.sh`（迁移账号），**再**启动应用；
生产 worker 启动只做只读 schema 校验，版本落后或缺列会拒绝启动。

当前最后一次验证：

```powershell
cd D:\卡系统\backend
$env:MYSQL_TEST_URL = "mysql+pymysql://root@127.0.0.1:33307"   # 指向一次性/本地 MySQL；未设置时 MySQL 用例跳过
.\.venv\Scripts\python.exe -m pytest tests/ -q
```

SQLite 回归全量 184 passed，18 skipped（本机未跑 MySQL，CI 真实运行）。前端
`npm run build` 通过；密钥扫描门禁退出 0。

## 后续顺序

按 `docs/开发计划.md` 第 12 节检查表推进：

1. T22 健康、指标和告警、T23 发布验收包与文档交接。
2. 独立运维动作（不随代码走）：历史泄漏凭据的轮换证据收集、生产服务器实际状态核实、
   季度恢复演练（首次已演练，见 log.md 2026-09-05）。

## 工作区注意事项

- `.env` 和 `secrets/` 已加入 `.gitignore`；仍不要读取、输出、提交或删除其内容。
- `backend/alembic/versions/2c984c17c453_baseline.py` 的 git 状态为换行符噪音，内容
  diff 为空，不要提交无意义换行变更。
- 新增迁移不得重写既有已部署迁移；`2c984c17c453`→`e4f8a2c1b907` 链保持原样。
- MySQL 回归用例读 `MYSQL_TEST_URL`（不含库名的根 URL）；未提供时自动供给一次性
  mysqld（`--init-file` 创建 `welfare_t20` 测试账户），供给失败自动 skip。注意 mysqld
  对非 ASCII 工作路径敏感，临时实例目录必须纯 ASCII。
- T09 起生产数据库账号拆分为 welfare_app / welfare_migrate / welfare_backup（仅
  localhost）；部署新版本必须让 `install-ubuntu.sh` 或 `setup-mysql.sql` 重建账号，
  并删除历史 ALL 权限的 `welfare` 账号。
- T15 邮件 outbox：生产必须配置 `PUBLIC_BASE_URL`（激活链接地址）；激活邮件
  发送成功即清库内正文；`/api/outbox` 仅超管可查/重发。
