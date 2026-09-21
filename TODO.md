# TODO

## 2026-09-21 待办

### 1. ~~把 exampledoc 批量导入测试固化为回归用例~~ ✅ 2026-09-21

已落地 `backend/tests/test_exampledoc_import.py`（2 个用例，全绿）：

- `TestExampledocFormatParity`：3 类 × 4 格式的 `(row, identifier, status, reason)`
  两两一致；行数 users 6 / issue 4 / points 4；用户未导入时 issue/points
  逐行 `precheck_failed`，原因 `用户不存在或无法唯一识别（支持用户名/邮箱/手机/学号）`。
- `TestExampledocFullSequence`：users 6/6（`email_queued=3`，凭证 `20260103` /
  `20260105` / `zhaoxy`）→ issue 4/4（四种标识各命中一次）→ points 3 成功 /
  1 失败（第 4 行 `时长余额不足`）；重复 execute 幂等（`point_ledgers` 4→4）；
  重复导 users 6 行全 `用户名已存在`；`/rows` 与 `/rows.csv`（UTF-8 BOM）可读。

**可选决定已定**：保留 points 第 4 行失败作为「余额不足拦截」演示，已在
`exampledoc/README.md` 表格下注明（不再改动示例数据）。

---

### 2. CSP 去掉 `style-src 'unsafe-inline'`（ZAP baseline 报 Medium）

- **现状**：`deploy/nginx-location-headers.conf`（线上 `/etc/nginx/snippets/`）与
  `backend/app/main.py` 的应用层 CSP 都是 `style-src 'self' 'unsafe-inline'`。
  ZAP 从「CSP Header Not Set」变成「CSP: style-src unsafe-inline」，仍是 Medium。
- **目标**：收紧到 nonce/hash。
- **现实约束（先看这条，别白费功夫）**：Element Plus 运行时同时注入 `<style>` 元素
  **和大量内联 `style="..."` 属性**。CSP nonce 只作用于 `<style>` 元素，管不了
  style 属性（那要 `style-src-attr`）。所以纯 nonce 大概率不可行。
- **可行路径**：`style-src-elem 'self' 'nonce-…'` + `style-src-attr 'unsafe-inline'`，
  或在 Vite 侧抽离/收敛内联样式。先评估收益——别为消一条 Medium 把 UI 搞崩。
- **步骤**：改 nginx snippet + 应用层 CSP（两处同值）→ Playwright 打开
  登录页 / 仪表盘 / 表格页，确认 **0 console CSP 报错** → 复跑 ZAP baseline 对比。
- **注意**：`script-src` 已经**没有** `unsafe-inline`，这块是真正要紧的，已达标。

### 3. 阿里云 ESA/WAF cookie 补 `Secure` / `SameSite`（ZAP baseline 报 Low）

- **现象**：响应里的 `acw_tc` / `cdn_sec_tc` 由阿里云 WAF 注入，缺 `Secure` 与 `SameSite`。
- **评估**：这俩是防爬/人机校验 cookie，不是会话凭证；应用自身的会话 cookie 已是
  `HttpOnly + Secure + SameSite=Lax`。风险低。
- **做法**：阿里云 ESA/WAF 控制台找「Cookie 设置 / 会话保持」补 `Secure`、`SameSite=Lax`。
- **验证**：`curl -D- https://youth.51huisheng.top/ | grep -i set-cookie` 应带 `Secure; SameSite`。

### 4. ~~（顺手，优先做）install-ubuntu.sh 没安装 nginx 头片段~~ ✅ 2026-09-21

已在 `deploy/install-ubuntu.sh` Nginx 段（`echo "==> Nginx"` 之后）加：
`install -D -m 644 "${APP_ROOT}/deploy/nginx-location-headers.conf" /etc/nginx/snippets/welfare-location-headers.conf`。
`bash -n` 通过；全新装机 `nginx -t` 不再因 include 缺失中断。

---

## 其他（不急）

- 旧域名残留：`deploy/pack-and-upload-public.sh`、`run-on-public.sh`、
  `remote-deploy.sh` 仍默认旧 AWS 机（`198.44.182.107` / `youth.huishengbook.us.ci`）；
  `backend/scripts/security_audit_prod.py` docstring 默认也是旧域名。
  `deploy/archive/` 里的不用管。
- `POST /api/client-errors` 免登录可写且 `audit_logs` 无保留期，仅靠全局
  300/min/IP 兜底（pentest LOW）——可加保留期或单独限流。
- `security_audit_prod.py` 报的 `app_env=None（期望 production）` 是误报
  （生产 `/api/health` 已脱敏），可让脚本接受脱敏态。
- ZAP 只跑了 baseline（被动）；如需要可对已登录会话跑一次主动扫描。
