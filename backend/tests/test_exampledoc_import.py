"""exampledoc 示例文件导入回归：解析格式一致 + 预检拦截 + 全链路执行。

固化 `exampledoc/` 3 类 × 4 格式共 12 个示例文件的行为，防止解析器或
示例文件漂移。用 `tests._helpers.TempApp`（临时 SQLite，不碰真实数据）。

Run from backend/:
  .venv/bin/python -m pytest tests/test_exampledoc_import.py -v
"""

from __future__ import annotations

import unittest
from pathlib import Path

from app.models.entities import Account, CouponInstance, CouponTemplate, PointLedger
from tests._helpers import TempApp, reset_env_defaults

EXAMPLEDOC = Path(__file__).resolve().parents[2] / "exampledoc"
FORMATS = ("csv", "xlsx", "txt", "docx")
EXPECTED_TOTAL = {"users": 6, "issue": 4, "points": 4}
NOT_FOUND = "用户不存在或无法唯一识别（支持用户名/邮箱/手机/学号）"


def _sample(kind: str, fmt: str) -> Path:
    matches = sorted(EXAMPLEDOC.glob(f"{kind}-*.{fmt}"))
    assert len(matches) == 1, f"{kind}.{fmt} 示例文件应恰好一份：{matches}"
    return matches[0]


def _template_id(ta: TempApp) -> str:
    with ta.session() as db:
        return db.query(CouponTemplate).filter(CouponTemplate.name == "餐饮立减券").one().id


def _preview(ta: TempApp, token: str, path: Path, form: dict) -> dict:
    with ta.client() as c:
        r = c.post(
            "/api/imports/preview",
            headers=ta.bearer(token),
            files={"file": (path.name, path.read_bytes(), "application/octet-stream")},
            data=form,
        )
    assert r.status_code == 200, r.text
    return r.json()


def _execute(ta: TempApp, token: str, batch_id: str) -> dict:
    with ta.client() as c:
        r = c.post(f"/api/imports/{batch_id}/execute", headers=ta.bearer(token), json=None)
    assert r.status_code == 200, r.text
    return r.json()


def _rows(ta: TempApp, token: str, batch_id: str) -> list[dict]:
    with ta.client() as c:
        r = c.get(f"/api/imports/{batch_id}/rows", headers=ta.bearer(token), params={"limit": 200})
    assert r.status_code == 200, r.text
    return r.json()["items"]


def _tuples(rows: list[dict]) -> list[tuple]:
    return [(r["row"], r["identifier"], r["status"], r["reason"]) for r in rows]


def _preview_form(kind: str, ta: TempApp) -> dict:
    if kind == "issue":
        return {"kind": kind, "template_id": _template_id(ta), "quantity": "1"}
    if kind == "points":
        return {"kind": kind, "reason": "默认说明"}
    return {"kind": kind}


class TestExampledocFormatParity(unittest.TestCase):
    """同一类文件四种格式解析 / 预检结果必须完全一致。"""

    def tearDown(self) -> None:
        reset_env_defaults()

    def test_precheck_parity_and_counts(self) -> None:
        for kind in EXPECTED_TOTAL:
            per_format: dict[str, list[tuple]] = {}
            for fmt in FORMATS:
                with TempApp() as ta:
                    token = ta.login("admin", "admin123")
                    body = _preview(ta, token, _sample(kind, fmt), _preview_form(kind, ta))
                    self.assertEqual(body["total"], EXPECTED_TOTAL[kind], f"{kind}.{fmt} 行数")
                    per_format[fmt] = _tuples(_rows(ta, token, body["id"]))

            base = per_format["csv"]
            for fmt in FORMATS[1:]:
                self.assertEqual(
                    base, per_format[fmt], f"{kind}: {fmt} 与 csv 解析结果不一致"
                )

            # 用户未导入时 issue / points 逐行拦截，users 全部待执行
            if kind in ("issue", "points"):
                self.assertTrue(all(t[2] == "precheck_failed" for t in base), base)
                self.assertTrue(all(t[3] == NOT_FOUND for t in base), base)
            else:
                self.assertTrue(all(t[2] == "pending" for t in base), base)


class TestExampledocFullSequence(unittest.TestCase):
    """users → issue → points 顺序执行、幂等、冲突与明细导出。"""

    def tearDown(self) -> None:
        reset_env_defaults()

    def test_full_import_sequence(self) -> None:
        with TempApp() as ta:
            token = ta.login("admin", "admin123")
            with ta.session() as db:
                ledgers_before = db.query(PointLedger).count()

            # --- users：6/6 成功，3 封激活邮件，3 个一次性初始凭证 ---
            users_batch = _preview(ta, token, _sample("users", "csv"), {"kind": "users"})
            self.assertEqual((users_batch["total"], users_batch["failed"]), (6, 0))
            users_ex = _execute(ta, token, users_batch["id"])
            self.assertEqual((users_ex["succeeded"], users_ex["failed"]), (6, 0))
            self.assertEqual(users_ex["email_queued"], 3)
            self.assertEqual(
                sorted(c["username"] for c in users_ex.get("credentials", [])),
                ["20260103", "20260105", "zhaoxy"],
            )

            # --- issue：4/4 成功，用户名/邮箱/手机/学号 四种标识各命中一次 ---
            issue_batch = _preview(ta, token, _sample("issue", "csv"), _preview_form("issue", ta))
            self.assertEqual((issue_batch["total"], issue_batch["failed"]), (4, 0))
            issue_ex = _execute(ta, token, issue_batch["id"])
            self.assertEqual((issue_ex["succeeded"], issue_ex["failed"]), (4, 0))
            hit_usernames = set()
            issue_rows = _rows(ta, token, issue_batch["id"])
            with ta.session() as db:
                for row in issue_rows:
                    coupon = db.get(CouponInstance, row["ref_id"])
                    hit_usernames.add(db.get(Account, coupon.user_id).username)
            self.assertEqual(hit_usernames, {"zhangmy", "lisq", "20260103", "20260105"})

            # --- points：3 成功 / 1 失败（第 4 行对 0 余额用户扣减）---
            points_batch = _preview(ta, token, _sample("points", "csv"), _preview_form("points", ta))
            self.assertEqual((points_batch["total"], points_batch["failed"]), (4, 0))
            points_ex = _execute(ta, token, points_batch["id"])
            self.assertEqual((points_ex["succeeded"], points_ex["failed"]), (3, 1))
            failed = [e for e in points_ex["errors"] if e["status"] == "failed"]
            self.assertEqual(failed[0]["row"], 4)
            self.assertEqual(failed[0]["reason"], "时长余额不足")
            with ta.session() as db:
                self.assertEqual(db.query(PointLedger).count(), ledgers_before + 3)

            # --- 幂等：重复 execute 只重试失败行，成功行不重复入账 ---
            points_again = _execute(ta, token, points_batch["id"])
            self.assertEqual((points_again["succeeded"], points_again["failed"]), (3, 1))
            with ta.session() as db:
                self.assertEqual(db.query(PointLedger).count(), ledgers_before + 3)

            # --- 冲突：同一 users 文件重复导入 → 6 行全 precheck_failed ---
            dup = _preview(ta, token, _sample("users", "csv"), {"kind": "users"})
            self.assertEqual((dup["total"], dup["failed"]), (6, 6))
            self.assertEqual({e["reason"] for e in dup["errors"]}, {"用户名已存在"})

            # --- 行明细 rows / rows.csv（UTF-8 BOM）可读 ---
            rows = _rows(ta, token, dup["id"])
            self.assertEqual(len(rows), 6)
            with ta.client() as c:
                r = c.get(f"/api/imports/{dup['id']}/rows.csv", headers=ta.bearer(token))
            self.assertEqual(r.status_code, 200, r.text)
            self.assertTrue(r.content.startswith(b"\xef\xbb\xbf"), "CSV 应带 UTF-8 BOM")
            text = r.content.decode("utf-8-sig")
            self.assertIn("行号", text)
            for real_name in ("张明远", "李思琪", "赵欣怡"):
                self.assertIn(real_name, text)


if __name__ == "__main__":
    unittest.main()
