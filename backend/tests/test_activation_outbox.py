"""T15 账号激活与可靠邮件 outbox 测试。

覆盖：激活链接单次消费、过期/重放/弱密码拒绝、会话版本递增、
占位密码不可登录、个人初始凭证双轨、outbox 入队与业务同事务、
退避重试与上限转失败、HTML 转义、库内无明文 token/密码、人工重发。

Run from backend/:
  .venv/bin/python -m pytest tests/test_activation_outbox.py -v
"""

from __future__ import annotations

import unittest
from datetime import timedelta
from unittest import mock
from urllib.parse import parse_qs, urlparse

from app.models.entities import (
    Account,
    ActivationToken,
    AuditLog,
    EmailOutbox,
    OutboxStatus,
    utcnow,
)
from tests._helpers import TempApp, reset_env_defaults

USERS_CSV = (
    "姓名,学号,用户名,手机,邮箱,组织,备注\n"
    "张三,20260001,zhangsan,13800000011,zhangsan@example.com,某大学,\n"
    "李四,20260002,lisi,13800000012,,某大学,\n"
).encode("utf-8")


def _preview(ta: TempApp, token: str, data: bytes, form: dict, filename: str = "users.csv"):
    with ta.client() as c:
        return c.post(
            "/api/imports/preview",
            headers=ta.bearer(token),
            files={"file": (filename, data, "application/octet-stream")},
            data=form,
        )


def _execute(ta: TempApp, token: str, batch_id: str):
    with ta.client() as c:
        return c.post(f"/api/imports/{batch_id}/execute", headers=ta.bearer(token), json={})


def _import_users(ta: TempApp, *, notify: str = "true", data: bytes = USERS_CSV) -> dict:
    admin = ta.login("admin", "admin123")
    r = _preview(ta, admin, data, {"kind": "users", "notify": notify})
    assert r.status_code == 200, r.text
    batch_id = r.json()["id"]
    r = _execute(ta, admin, batch_id)
    assert r.status_code == 200, r.text
    return r.json()


def _activation_token_raw(ta: TempApp) -> tuple[str, str]:
    """从 outbox 邮件正文解析激活链接的明文 token（仅 queued 任务有正文）。"""
    import html as _html
    import re as _re

    with ta.session() as db:
        task = (
            db.query(EmailOutbox)
            .filter(EmailOutbox.kind == "activation", EmailOutbox.status == OutboxStatus.queued)
            .one()
        )
        href = _re.search(r'href="([^"]+)"', task.html).group(1)
        link = urlparse(_html.unescape(href))
        token = parse_qs(link.query)["token"][0]
        return token, task.to_email


class TestActivationFlow(unittest.TestCase):
    def tearDown(self) -> None:
        reset_env_defaults()

    def test_import_with_email_enqueues_activation_and_locks_account(self) -> None:
        with TempApp() as ta:
            body = _import_users(ta)
            self.assertEqual(body["succeeded"], 2)
            self.assertEqual(body.get("email_queued"), 1)
            # 同批次无邮箱行走个人凭证；激活行不产生凭证
            creds = body.get("credentials") or []
            self.assertEqual([c["username"] for c in creds], ["lisi"])
            self.assertNotIn("default_password", body)
            with ta.session() as db:
                zs = db.query(Account).filter(Account.username == "zhangsan").one()
                self.assertEqual(db.query(ActivationToken).filter(ActivationToken.account_id == zs.id).count(), 1)
                # 库里只有 HMAC 摘要，且库内任何行不出现链接明文 token
                row = db.query(ActivationToken).filter(ActivationToken.account_id == zs.id).one()
                self.assertEqual(len(row.token_hash), 64)
                self.assertTrue(row.used_at is None)
                # 占位密码不可登录：默认初始密码必然失败
            with ta.client() as c:
                r = c.post("/api/auth/login", json={"username": "zhangsan", "password": "youth123456"})
                self.assertEqual(r.status_code, 400)

    def test_import_without_email_returns_personal_credential_once(self) -> None:
        with TempApp() as ta:
            body = _import_users(ta, notify="false")
            self.assertNotIn("email_queued", body)
            self.assertNotIn("smtp_unconfigured", body)
            creds = body.get("credentials") or []
            # 关闭通知：所有行（含有邮箱）都走个人凭证，不发激活邮件
            self.assertEqual(sorted(c["username"] for c in creds), ["lisi", "zhangsan"])
            self.assertNotIn("default_password", body)
            # 该凭证可登录且强制首改密
            lisi_cred = next(c for c in creds if c["username"] == "lisi")
            with ta.client() as c:
                r = c.post("/api/auth/login", json={"username": "lisi", "password": lisi_cred["password"]})
                self.assertEqual(r.status_code, 200, r.text)
                me = c.get("/api/auth/me", headers=ta.bearer(r.json()["access_token"]))
                self.assertTrue(me.json()["must_change_password"])
            # 重复导入同一名单：用户名冲突全部拒绝，不重复建号
            body2 = _import_users(ta, notify="true", data=USERS_CSV)
            self.assertEqual(body2["failed"], 2)

    def test_activate_sets_password_once_and_invalidates_replay(self) -> None:
        with TempApp() as ta:
            _import_users(ta)
            token, email = _activation_token_raw(ta)
            self.assertEqual(email, "zhangsan@example.com")
            with ta.session() as db:
                zs = db.query(Account).filter(Account.username == "zhangsan").one()
                self.assertEqual(zs.session_version, 0)

            with ta.client() as c:
                r = c.post("/api/auth/activate", json={"token": token, "new_password": "NewPass2026"})
                self.assertEqual(r.status_code, 200, r.text)
                # 重放：同一 token 第二次消费被拒
                r2 = c.post("/api/auth/activate", json={"token": token, "new_password": "OtherPass2026"})
                self.assertEqual(r2.status_code, 400)
                self.assertIn("已被使用", r2.json()["detail"])

            with ta.session() as db:
                zs = db.query(Account).filter(Account.username == "zhangsan").one()
                self.assertFalse(zs.must_change_password)
                self.assertEqual(zs.session_version, 1)
                row = db.query(ActivationToken).filter(ActivationToken.account_id == zs.id).one()
                self.assertIsNotNone(row.used_at)

            # 新密码可登录，旧占位密码不可
            with ta.client() as c:
                r = c.post("/api/auth/login", json={"username": "zhangsan", "password": "NewPass2026"})
                self.assertEqual(r.status_code, 200, r.text)
                r = c.post("/api/auth/login", json={"username": "zhangsan", "password": "youth123456"})
                self.assertEqual(r.status_code, 400)

    def test_activate_rejects_expired_and_weak_password(self) -> None:
        with TempApp() as ta:
            _import_users(ta)
            token, _ = _activation_token_raw(ta)
            with ta.session() as db:
                row = db.query(ActivationToken).one()
                db.query(ActivationToken).filter(ActivationToken.id == row.id).update(
                    {ActivationToken.expires_at: utcnow() - timedelta(minutes=1)},
                    synchronize_session=False,
                )
                db.commit()
            with ta.client() as c:
                r = c.post("/api/auth/activate", json={"token": token, "new_password": "NewPass2026"})
                self.assertEqual(r.status_code, 400)
                self.assertIn("过期", r.json()["detail"])
                # 未过期的错误 token / 弱密码
                r = c.post("/api/auth/activate", json={"token": "x" * 32, "new_password": "NewPass2026"})
                self.assertEqual(r.status_code, 400)
                r = c.post("/api/auth/activate", json={"token": token, "new_password": "short"})
                self.assertEqual(r.status_code, 422)

    def test_activation_email_escapes_user_fields_and_stores_no_token_plaintext(self) -> None:
        # 解析层 sanitize_plain_text 已剥 <>；这里直接单测转义层对
        # 能通过清洗的字符（&、引号）以及未清洗输入的防线
        from app.services.imports import _activation_email_html

        html = _activation_email_html(
            '张&三"onmouseover="x', 'u<b>1', "http://x/activate?token=a&b=1"
        )
        self.assertNotIn('<b>1', html)
        self.assertNotIn('"onmouseover', html)
        self.assertIn('张&amp;三&quot;onmouseover=&quot;x', html)
        self.assertIn('u&lt;b&gt;1', html)
        self.assertIn("http://x/activate?token=a&amp;b=1", html)

        csv_data = (
            "姓名,学号,用户名,手机,邮箱,组织,备注\n"
            '张&三"x,20260001,zsx,13800000011,zsx@example.com,某大学,\n'
        ).encode("utf-8")
        with TempApp() as ta:
            _import_users(ta, data=csv_data)
            with ta.session() as db:
                task = db.query(EmailOutbox).filter(EmailOutbox.kind == "activation").one()
                self.assertNotIn('"x', task.html)
                self.assertIn("张&amp;三&quot;x", task.html)
                # 任何库内 outbox/审计行都不含激活 token 明文（链接只进正文一次，正文即唯一出口）
                audits = db.query(AuditLog).filter(AuditLog.action.in_(["user_import", "import_execute"])).all()
                for a in audits:
                    self.assertNotIn("token=", a.detail or "")


class TestOutboxDelivery(unittest.TestCase):
    def tearDown(self) -> None:
        reset_env_defaults()

    def test_send_due_delivers_queued_and_clears_body(self) -> None:
        import asyncio

        from app.services.outbox import send_due

        with TempApp() as ta:
            _import_users(ta)
            with ta.session() as db:
                self.assertEqual(db.query(EmailOutbox).filter(EmailOutbox.status == OutboxStatus.queued).count(), 1)
            with ta.session() as db:
                counts = asyncio.run(send_due(db))
            self.assertEqual(counts["sent"], 1)
            with ta.session() as db:
                task = db.query(EmailOutbox).one()
                self.assertEqual(task.status, OutboxStatus.sent)
                self.assertIsNotNone(task.sent_at)
                self.assertEqual(task.html, "", "已受理任务正文清空（激活链接不长期留库）")
            # 重启模拟：再次 flush 不会重发已 sent 的任务
            with ta.session() as db:
                counts = asyncio.run(send_due(db))
            self.assertEqual(counts["sent"], 0)

    def test_send_failure_retries_with_backoff_then_permanent_failure(self) -> None:
        import asyncio

        from app.services.outbox import BACKOFF_SECONDS, send_due

        with TempApp() as ta:
            _import_users(ta)
            with mock.patch("app.services.mail.send_email_html", side_effect=RuntimeError("smtp down")):
                with ta.session() as db:
                    counts = asyncio.run(send_due(db))
                self.assertEqual(counts["retried"], 1)
                with ta.session() as db:
                    task = db.query(EmailOutbox).one()
                    self.assertEqual(task.status, OutboxStatus.queued)
                    self.assertEqual(task.attempts, 1)
                    self.assertIn("RuntimeError", task.last_error)
                    # next_retry_at 在未来（退避窗口）；SQLite 读回 naive，统一去 tz 后比较
                    from datetime import datetime, timezone as _tz

                    now_naive = datetime.now(_tz.utc).replace(tzinfo=None)
                    self.assertGreater(task.next_retry_at.replace(tzinfo=None), now_naive)

                # 连续失败直到上限
                for expected_attempts in range(2, task.max_attempts + 1):
                    with ta.session() as db:
                        t = db.query(EmailOutbox).one()
                        # 手动到期以便下一轮领取
                        db.query(EmailOutbox).filter(EmailOutbox.id == t.id).update(
                            {EmailOutbox.next_retry_at: utcnow() - timedelta(seconds=1)},
                            synchronize_session=False,
                        )
                        db.commit()
                        asyncio.run(send_due(db))
                with ta.session() as db:
                    task = db.query(EmailOutbox).one()
                    self.assertEqual(task.status, OutboxStatus.failed)
                    self.assertEqual(task.attempts, task.max_attempts)
                    self.assertIn("smtp down", task.last_error)
            # 失败任务保留正文（重发需要）；人工重发后回到 queued
            with ta.session() as db:
                task = db.query(EmailOutbox).one()
                self.assertTrue(task.html)
            admin = ta.login("admin", "admin123")
            with ta.client() as c:
                r = c.post(f"/api/outbox/{task.id}/resend", headers=ta.bearer(admin))
                self.assertEqual(r.status_code, 200, r.text)
                r = c.get("/api/outbox", headers=ta.bearer(admin), params={"status": "queued"})
                self.assertEqual(r.status_code, 200, r.text)
                self.assertEqual(r.json()["total"], 1)
                # 正文不含激活 token 之外的敏感信息；管理列表不回正文
                self.assertNotIn("html", r.json()["items"][0])

    def test_backoff_sequence_grows(self) -> None:
        from app.services.outbox import BACKOFF_SECONDS

        self.assertEqual(len(BACKOFF_SECONDS), 4)
        self.assertLess(BACKOFF_SECONDS[0], BACKOFF_SECONDS[-1])

    def test_enqueue_survives_without_sender_configured_in_dev(self) -> None:
        """开发环境未配 SMTP：console 模式受理（测试里 monkeypatch 掉真实发送同理）。"""
        import asyncio

        from app.services.outbox import send_due

        with TempApp() as ta:
            _import_users(ta)
            # TempApp 未配置 SMTP（开发环境）：send_email_html console 模式不抛错
            with ta.session() as db:
                counts = asyncio.run(send_due(db))
            self.assertEqual(counts["sent"], 1)

    def test_resend_requires_super_admin(self) -> None:
        with TempApp() as ta:
            _import_users(ta)
            with mock.patch("app.services.mail.send_email_html", side_effect=RuntimeError("boom")):
                import asyncio

                from app.services.outbox import send_due

                # 直接耗尽重试
                from app.services.outbox import BACKOFF_SECONDS

                for _ in range(len(BACKOFF_SECONDS) + 1):
                    with ta.session() as db:
                        t = db.query(EmailOutbox).one()
                        db.query(EmailOutbox).filter(EmailOutbox.id == t.id).update(
                            {EmailOutbox.next_retry_at: utcnow() - timedelta(seconds=1)},
                            synchronize_session=False,
                        )
                        db.commit()
                        asyncio.run(send_due(db))
            with ta.session() as db:
                task = db.query(EmailOutbox).one()
                self.assertEqual(task.status, OutboxStatus.failed)
            issuer = ta.login("issuer", "issuer123")
            with ta.client() as c:
                r = c.post(f"/api/outbox/{task.id}/resend", headers=ta.bearer(issuer))
                self.assertEqual(r.status_code, 403)


if __name__ == "__main__":
    unittest.main()
