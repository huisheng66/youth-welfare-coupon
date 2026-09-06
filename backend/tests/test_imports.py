"""T14 统一导入预检、批次与逐行结果测试。

覆盖：预检不写业务数据、执行幂等与断点续执、文件内重复拒绝、歧义报告、
执行时重新验证、摘要确认、分页与 CSV、解析资源上限、批次共用密码哈希。

Run from backend/:
  .venv/bin/python -m pytest tests/test_imports.py -v
"""

from __future__ import annotations

import unittest
from decimal import Decimal

from app.models.entities import (
    Account,
    CouponInstance,
    CouponTemplate,
    ImportBatch,
    ImportRow,
    ImportRowStatus,
    PointAccount,
    UserProfile,
    VerifyStatus,
)
from tests._helpers import TempApp, reset_env_defaults


def _csv(text: str) -> bytes:
    return text.strip().encode("utf-8")


def _account_id(ta: TempApp, username: str) -> str:
    with ta.session() as db:
        return db.query(Account).filter(Account.username == username).one().id


def _template_id(ta: TempApp, name: str = "餐饮立减券") -> str:
    with ta.session() as db:
        return db.query(CouponTemplate).filter(CouponTemplate.name == name).one().id


def _coupon_count(ta: TempApp, username: str) -> int:
    with ta.session() as db:
        acc = db.query(Account).filter(Account.username == username).one()
        return db.query(CouponInstance).filter(CouponInstance.user_id == acc.id).count()


def _balance(ta: TempApp, username: str) -> Decimal:
    with ta.session() as db:
        acc = db.query(Account).filter(Account.username == username).one()
        pa = db.query(PointAccount).filter(PointAccount.user_id == acc.id).one()
        return Decimal(pa.balance)


def _preview(ta: TempApp, token: str, data: bytes, form: dict, filename: str = "import.csv"):
    with ta.client() as c:
        return c.post(
            "/api/imports/preview",
            headers=ta.bearer(token),
            files={"file": (filename, data, "application/octet-stream")},
            data=form,
        )


def _execute(ta: TempApp, token: str, batch_id: str, body: dict | None = None):
    with ta.client() as c:
        return c.post(
            f"/api/imports/{batch_id}/execute",
            headers=ta.bearer(token),
            json=body,
        )


class TestUnifiedImportUsers(unittest.TestCase):
    def tearDown(self) -> None:
        reset_env_defaults()

    def test_preview_writes_no_business_data(self) -> None:
        with TempApp() as ta:
            token = ta.login("admin", "admin123")
            data = _csv(
                "姓名,学号,用户名,手机,邮箱,组织,备注\n"
                "张三,20260001,zhangsan,13800000011,zhangsan@example.com,某大学,\n"
                "李四,20260002,lisi,13800000012,,某大学,\n"
                ",20260003,badname,,,某大学,\n"
            )
            with ta.session() as db:
                before = db.query(Account).count()
            r = _preview(ta, token, data, {"kind": "users"})
            self.assertEqual(r.status_code, 200, r.text)
            body = r.json()
            self.assertEqual(body["total"], 3)
            self.assertEqual(body["executable"], 2)
            self.assertEqual(body["failed"], 1)
            self.assertEqual(body["errors"][0]["reason"], "姓名为空")
            with ta.session() as db:
                self.assertEqual(db.query(Account).count(), before, "预检不得写入业务数据")
                self.assertEqual(db.query(ImportRow).count(), 3)

    def test_execute_users_batch_and_reexecute_idempotent(self) -> None:
        with TempApp() as ta:
            token = ta.login("admin", "admin123")
            data = _csv(
                "姓名,学号,用户名,手机,邮箱,组织,备注\n"
                "张三,20260001,zhangsan,13800000011,zhangsan@example.com,某大学,\n"
                "李四,20260002,lisi,13800000012,,某大学,\n"
            )
            r = _preview(ta, token, data, {"kind": "users"})
            batch_id = r.json()["id"]
            r = _execute(ta, token, batch_id)
            self.assertEqual(r.status_code, 200, r.text)
            body = r.json()
            self.assertEqual(body["succeeded"], 2)
            self.assertEqual(body["failed"], 0)
            self.assertTrue(body.get("default_password"))
            with ta.session() as db:
                zhangsan = db.query(Account).filter(Account.username == "zhangsan").one()
                lisi = db.query(Account).filter(Account.username == "lisi").one()
                # 批次共用一次密码哈希（1000 行从分钟级降到单次）
                self.assertEqual(zhangsan.password_hash, lisi.password_hash)
                self.assertTrue(zhangsan.must_change_password)
                profile = db.query(UserProfile).filter(UserProfile.account_id == zhangsan.id).one()
                self.assertEqual(profile.verify_status, VerifyStatus.approved)
                batch = db.get(ImportBatch, batch_id)
                self.assertEqual(batch.status.value, "completed")

            # 重复执行：幂等返回，不重复建号
            r = _execute(ta, token, batch_id)
            self.assertEqual(r.status_code, 200, r.text)
            self.assertEqual(r.json()["succeeded"], 2)
            with ta.session() as db:
                self.assertEqual(
                    db.query(Account).filter(Account.username.in_(["zhangsan", "lisi"])).count(), 2
                )

    def test_execute_revalidates_uniqueness(self) -> None:
        """预检通过后他人抢注用户名 → 执行时该行失败，其余行不受影响。"""
        with TempApp() as ta:
            token = ta.login("admin", "admin123")
            data = _csv(
                "姓名,学号,用户名,手机,邮箱,组织,备注\n"
                "张三,20260001,zhangsan,13800000011,,某大学,\n"
                "李四,20260002,lisi,13800000012,,某大学,\n"
            )
            r = _preview(ta, token, data, {"kind": "users"})
            batch_id = r.json()["id"]
            # 预检后抢注 zhangsan
            with ta.session() as db:
                from app.core.security import hash_password

                db.add(
                    Account(
                        username="zhangsan",
                        password_hash=hash_password("somepass123"),
                        role="user",
                    )
                )
                db.commit()
            r = _execute(ta, token, batch_id)
            self.assertEqual(r.status_code, 200, r.text)
            body = r.json()
            self.assertEqual(body["succeeded"], 1)
            self.assertEqual(body["failed"], 1)
            reasons = [e["reason"] for e in body["errors"]]
            self.assertTrue(any("用户名已存在" in x for x in reasons), reasons)
            with ta.session() as db:
                self.assertIsNotNone(db.query(Account).filter(Account.username == "lisi").first())

    def test_wrong_confirm_hash_rejected(self) -> None:
        with TempApp() as ta:
            token = ta.login("admin", "admin123")
            data = _csv("姓名,学号,用户名\n张三,20260001,zhangsan\n")
            r = _preview(ta, token, data, {"kind": "users"})
            batch_id = r.json()["id"]
            r = _execute(ta, token, batch_id, {"file_sha256": "0" * 64})
            self.assertEqual(r.status_code, 409, r.text)
            # 非创建者不能执行
            issuer = ta.login("issuer", "issuer123")
            r = _execute(ta, issuer, batch_id)
            self.assertEqual(r.status_code, 403, r.text)


class TestUnifiedImportIssue(unittest.TestCase):
    def tearDown(self) -> None:
        reset_env_defaults()

    def test_issue_batch_duplicates_and_unverified_precheck(self) -> None:
        with TempApp() as ta:
            token = ta.login("admin", "admin123")
            tmpl = _template_id(ta)
            data = _csv("用户标识\nyouth1\nyouth1\nyouth2\nnosuchuser\n")
            r = _preview(ta, token, data, {"kind": "issue", "template_id": tmpl, "quantity": "2"})
            self.assertEqual(r.status_code, 200, r.text)
            body = r.json()
            self.assertEqual(body["total"], 4)
            self.assertEqual(body["executable"], 1)
            reasons = {e["row"]: e["reason"] for e in body["errors"]}
            self.assertIn("重复", reasons[2])
            self.assertIn("核验", reasons[3])
            self.assertIn("无法唯一识别", reasons[4])

            before = _coupon_count(ta, "youth1")
            r = _execute(ta, token, batch_id=body["id"])
            self.assertEqual(r.status_code, 200, r.text)
            self.assertEqual(r.json()["succeeded"], 1)
            self.assertEqual(_coupon_count(ta, "youth1") - before, 2)

            # 重复执行不重复发券
            r = _execute(ta, token, batch_id=body["id"])
            self.assertEqual(_coupon_count(ta, "youth1") - before, 2)

    def test_issue_execute_rechecks_eligibility(self) -> None:
        """预检通过后用户进入复核 → 执行时该行资格拒绝（预检不代替执行检查）。"""
        with TempApp() as ta:
            token = ta.login("admin", "admin123")
            tmpl = _template_id(ta)
            data = _csv("用户标识\nyouth1\n")
            r = _preview(ta, token, data, {"kind": "issue", "template_id": tmpl, "quantity": "1"})
            batch_id = r.json()["id"]
            yid = _account_id(ta, "youth1")
            with ta.session() as db:
                db.query(UserProfile).filter(UserProfile.account_id == yid).update(
                    {"verify_status": VerifyStatus.pending}
                )
                db.commit()
            before = _coupon_count(ta, "youth1")
            r = _execute(ta, token, batch_id)
            self.assertEqual(r.status_code, 200, r.text)
            body = r.json()
            self.assertEqual(body["succeeded"], 0)
            self.assertEqual(body["failed"], 1)
            self.assertIn("核验", body["errors"][0]["reason"])
            self.assertEqual(_coupon_count(ta, "youth1"), before)

    def test_ambiguous_identifier_reported(self) -> None:
        """两个用户同学号：按学号导入必须报告歧义而不是静默选一个。"""
        with TempApp() as ta:
            token = ta.login("admin", "admin123")
            tmpl = _template_id(ta)
            with ta.session() as db:
                from app.core.security import hash_password

                for name in ("twin_a", "twin_b"):
                    acc = Account(
                        username=name, password_hash=hash_password("pass1234"), role="user"
                    )
                    db.add(acc)
                    db.flush()
                    db.add(
                        UserProfile(
                            account_id=acc.id,
                            real_name=name,
                            student_no="DUP-001",
                            verify_status=VerifyStatus.approved,
                        )
                    )
                db.commit()
            data = _csv("用户标识\nDUP-001\n")
            r = _preview(ta, token, data, {"kind": "issue", "template_id": tmpl, "quantity": "1"})
            self.assertEqual(r.status_code, 200, r.text)
            body = r.json()
            self.assertEqual(body["executable"], 0)
            self.assertIn("歧义", body["errors"][0]["reason"])


class TestUnifiedImportPoints(unittest.TestCase):
    def tearDown(self) -> None:
        reset_env_defaults()

    def test_points_batch_validation_and_resume(self) -> None:
        """混合行预检 + 执行期失败行可修复后续执，已成功行不重复入账。"""
        with TempApp() as ta:
            token = ta.login("admin", "admin123")
            # 新 approved 用户用于执行期失败场景
            with ta.session() as db:
                from app.core.security import hash_password

                acc = Account(
                    username="resume_u", password_hash=hash_password("pass1234"), role="user"
                )
                db.add(acc)
                db.flush()
                db.add(
                    UserProfile(
                        account_id=acc.id,
                        real_name="续执",
                        verify_status=VerifyStatus.approved,
                    )
                )
                db.commit()
            data = _csv(
                "用户标识,时长(小时),说明\n"
                "youth1,2.5,社区服务\n"
                "resume_u,1,续执行\n"
                "youth1,NaN,\n"
                "youth1,Infinity,\n"
                "youth1,0,\n"
                "youth1,abc,\n"
                "youth1,5,重复行\n"
            )
            r = _preview(ta, token, data, {"kind": "points", "reason": "默认说明"})
            self.assertEqual(r.status_code, 200, r.text)
            body = r.json()
            self.assertEqual(body["total"], 7)
            self.assertEqual(body["executable"], 2)
            reasons = {e["row"]: e["reason"] for e in body["errors"]}
            self.assertIn("有限数值", reasons[3])
            self.assertIn("有限数值", reasons[4])
            self.assertIn("不能为 0", reasons[5])
            self.assertIn("格式无效", reasons[6])
            self.assertIn("重复", reasons[7])

            # 执行前停用 resume_u → 执行期失败
            rid = _account_id(ta, "resume_u")
            with ta.session() as db:
                db.query(Account).filter(Account.id == rid).update({"is_active": False})
                db.commit()
            batch_id = body["id"]
            r = _execute(ta, token, batch_id)
            self.assertEqual(r.status_code, 200, r.text)
            body = r.json()
            self.assertEqual(body["succeeded"], 1)
            self.assertEqual(body["failed"], 6)
            self.assertEqual(_balance(ta, "youth1"), Decimal("12.50"))

            # 恢复 resume_u 后续执：只重试失败行，youth1 不重复入账
            with ta.session() as db:
                db.query(Account).filter(Account.id == rid).update({"is_active": True})
                db.commit()
            r = _execute(ta, token, batch_id)
            self.assertEqual(r.status_code, 200, r.text)
            self.assertEqual(r.json()["succeeded"], 2)
            self.assertEqual(_balance(ta, "youth1"), Decimal("12.50"), "已成功行不得重复入账")
            self.assertEqual(_balance(ta, "resume_u"), Decimal("1.00"))

    def test_rows_pagination_and_csv_export(self) -> None:
        with TempApp() as ta:
            token = ta.login("admin", "admin123")
            lines = ["用户标识,时长(小时)"] + [f"baduser{i},1" for i in range(5)]
            r = _preview(ta, token, _csv("\n".join(lines)), {"kind": "points"})
            batch_id = r.json()["id"]
            with ta.client() as c:
                r = c.get(
                    f"/api/imports/{batch_id}/rows",
                    headers=ta.bearer(token),
                    params={"status": "precheck_failed", "skip": 2, "limit": 2},
                )
                self.assertEqual(r.status_code, 200, r.text)
                self.assertEqual(r.json()["total"], 5)
                self.assertEqual(len(r.json()["items"]), 2)
                self.assertEqual(r.json()["items"][0]["row"], 3)

                r = c.get(f"/api/imports/{batch_id}/rows.csv", headers=ta.bearer(token))
                self.assertEqual(r.status_code, 200, r.text)
                content = r.content.decode("utf-8-sig")
                self.assertIn("行号", content)
                for i in range(5):
                    self.assertIn(f"baduser{i}", content)


class TestImportParseGuards(unittest.TestCase):
    def tearDown(self) -> None:
        reset_env_defaults()

    def test_oversized_cell_and_columns_rejected(self) -> None:
        with TempApp() as ta:
            token = ta.login("admin", "admin123")
            # 超长单元格
            data = _csv("用户标识\n" + "x" * 600 + "\n")
            r = _preview(ta, token, data, {"kind": "issue", "template_id": "t", "quantity": "1"})
            self.assertEqual(r.status_code, 400, r.text)
            self.assertIn("超长单元格", r.json()["detail"])
            # 列数超限
            data = _csv(",".join(["a"] * 70))
            r = _preview(ta, token, data, {"kind": "points"})
            self.assertEqual(r.status_code, 400, r.text)
            self.assertIn("列数", r.json()["detail"])


if __name__ == "__main__":
    unittest.main()
