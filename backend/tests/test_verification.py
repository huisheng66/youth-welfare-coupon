"""T11：核验快照、并发审核、批量逐条结果、导入来源。"""

from __future__ import annotations

import unittest

from tests._helpers import TempApp, reset_env_defaults


def _pending_of(ta: TempApp, username: str) -> dict:
    admin = ta.login("admin", "admin123")
    with ta.client() as c:
        r = c.get("/api/users/pending-verifications", headers=ta.bearer(admin))
    assert r.status_code == 200, r.text
    return next(item for item in r.json() if item["username"] == username)


def _user_id(ta: TempApp, username: str) -> str:
    with ta.session() as db:
        from app.models.entities import Account

        return db.query(Account).filter(Account.username == username).one().id


class TestVerificationSnapshots(unittest.TestCase):
    def tearDown(self) -> None:
        reset_env_defaults()

    def test_pending_list_uses_application_snapshot(self) -> None:
        with TempApp() as ta:
            pending = _pending_of(ta, "youth2")
            self.assertTrue(pending["snapshot_available"])
            self.assertEqual(pending["real_name"], "王青年")
            self.assertEqual(pending["snapshot_real_name"], "王青年")
            self.assertEqual(pending["snapshot_version"], 1)
            self.assertEqual(pending["source"], "user_submit")

    def test_approved_identity_change_creates_pending_snapshot(self) -> None:
        with TempApp() as ta:
            token = ta.login("youth1", "youth123")
            with ta.client() as c:
                r = c.put(
                    "/api/users/me/profile",
                    headers=ta.bearer(token),
                    json={"real_name": "核验后修改的姓名"},
                )
                self.assertEqual(r.status_code, 200, r.text)
                self.assertEqual(r.json()["verify_status"], "pending")
                again = c.post(
                    "/api/users/me/verifications",
                    headers=ta.bearer(token),
                    json={"material_note": "重复提交应被拒绝"},
                )
                self.assertEqual(again.status_code, 400, again.text)

            pending = _pending_of(ta, "youth1")
            self.assertEqual(pending["real_name"], "核验后修改的姓名")
            self.assertEqual(pending["snapshot_real_name"], "核验后修改的姓名")
            self.assertEqual(pending["source"], "profile_change")
            self.assertGreaterEqual(pending["snapshot_version"], 2)

    def test_pending_identity_change_supersedes_old_application(self) -> None:
        with TempApp() as ta:
            old = _pending_of(ta, "youth2")
            token = ta.login("youth2", "youth123")
            with ta.client() as c:
                r = c.put(
                    "/api/users/me/profile",
                    headers=ta.bearer(token),
                    json={"real_name": "改过的待审姓名", "organization": "新组织"},
                )
                self.assertEqual(r.status_code, 200, r.text)
                self.assertEqual(r.json()["verify_status"], "pending")

            admin = ta.login("admin", "admin123")
            with ta.client() as c:
                stale = c.post(
                    f"/api/users/verifications/{old['id']}/review",
                    headers=ta.bearer(admin),
                    json={"approve": True, "expected_version": old["snapshot_version"]},
                )
                self.assertEqual(stale.status_code, 400, stale.text)
                self.assertIn("已处理", stale.json()["detail"])

            new = _pending_of(ta, "youth2")
            self.assertNotEqual(new["id"], old["id"])
            self.assertEqual(new["real_name"], "改过的待审姓名")
            self.assertEqual(new["organization"], "新组织")
            self.assertEqual(new["current_real_name"], "改过的待审姓名")

            with ta.session() as db:
                from app.models.entities import UserVerification, VerifyStatus

                old_row = db.get(UserVerification, old["id"])
                self.assertEqual(old_row.status, VerifyStatus.superseded)
                self.assertEqual(old_row.snapshot_real_name, "王青年")

            with ta.client() as c:
                ok = c.post(
                    f"/api/users/verifications/{new['id']}/review",
                    headers=ta.bearer(admin),
                    json={"approve": True, "expected_version": new["snapshot_version"]},
                )
                self.assertEqual(ok.status_code, 200, ok.text)
                self.assertEqual(ok.json()["status"], "approved")

    def test_second_reviewer_cannot_overwrite(self) -> None:
        with TempApp() as ta:
            pending = _pending_of(ta, "youth2")
            admin = ta.login("admin", "admin123")
            issuer = ta.login("issuer", "issuer123")
            with ta.client() as c:
                first = c.post(
                    f"/api/users/verifications/{pending['id']}/review",
                    headers=ta.bearer(admin),
                    json={"approve": True, "expected_version": pending["snapshot_version"]},
                )
                self.assertEqual(first.status_code, 200, first.text)
                second = c.post(
                    f"/api/users/verifications/{pending['id']}/review",
                    headers=ta.bearer(issuer),
                    json={"approve": False, "review_note": "想驳回"},
                )
                self.assertEqual(second.status_code, 400, second.text)

            with ta.session() as db:
                from app.models.entities import UserProfile, UserVerification, VerifyStatus

                row = db.get(UserVerification, pending["id"])
                profile = db.get(UserProfile, row.profile_id)
                self.assertEqual(row.status, VerifyStatus.approved)
                self.assertEqual(profile.verify_status, VerifyStatus.approved)

    def test_expected_version_mismatch_is_conflict(self) -> None:
        with TempApp() as ta:
            pending = _pending_of(ta, "youth2")
            admin = ta.login("admin", "admin123")
            with ta.client() as c:
                r = c.post(
                    f"/api/users/verifications/{pending['id']}/review",
                    headers=ta.bearer(admin),
                    json={"approve": True, "expected_version": pending["snapshot_version"] + 9},
                )
                self.assertEqual(r.status_code, 409, r.text)
            still = _pending_of(ta, "youth2")
            self.assertEqual(still["id"], pending["id"])

    def test_batch_review_returns_per_item_results(self) -> None:
        with TempApp() as ta:
            pending = _pending_of(ta, "youth2")
            admin = ta.login("admin", "admin123")
            missing = "00000000-0000-0000-0000-000000000000"
            with ta.client() as c:
                r = c.post(
                    "/api/users/verifications/batch-review",
                    headers=ta.bearer(admin),
                    json={
                        "verification_ids": [pending["id"], pending["id"], missing],
                        "approve": True,
                    },
                )
                self.assertEqual(r.status_code, 200, r.text)
                body = r.json()
                self.assertEqual(body["succeeded"], 1)
                self.assertEqual(body["already_processed"], 1)
                self.assertEqual(body["not_found"], 1)
                self.assertEqual(len(body["items"]), 3)
                self.assertEqual(body["items"][0]["result"], "success")
                self.assertEqual(body["items"][1]["result"], "already_processed")
                self.assertEqual(body["items"][2]["result"], "not_found")
                self.assertIn("成功 1", body["message"])


class TestImportVerificationProvenance(unittest.TestCase):
    def tearDown(self) -> None:
        reset_env_defaults()

    def test_import_creates_approved_verification_with_source(self) -> None:
        data = (
            "姓名,学号,用户名,手机,组织,备注\n"
            "导入快照,20269999,snapuser,13800000999,导入组织,\n"
        ).encode("utf-8")
        with TempApp() as ta:
            token = ta.login("issuer", "issuer123")
            with ta.client() as c:
                r = c.post(
                    "/api/users/import",
                    headers=ta.bearer(token),
                    files={"file": ("users.csv", data, "text/csv")},
                    data={"dry_run": "false", "notify": "false"},
                )
                self.assertEqual(r.status_code, 200, r.text)
                self.assertEqual(r.json()["succeeded"], 1)

            uid = _user_id(ta, "snapuser")
            with ta.session() as db:
                from app.models.entities import UserProfile, UserVerification, VerificationSource, VerifyStatus

                profile = db.query(UserProfile).filter(UserProfile.account_id == uid).one()
                self.assertEqual(profile.verify_status, VerifyStatus.approved)
                row = (
                    db.query(UserVerification)
                    .filter(UserVerification.profile_id == profile.id)
                    .one()
                )
                self.assertEqual(row.status, VerifyStatus.approved)
                self.assertEqual(row.source, VerificationSource.bulk_import)
                self.assertEqual(row.snapshot_real_name, "导入快照")
                self.assertEqual(row.snapshot_student_no, "20269999")
                self.assertEqual(row.snapshot_organization, "导入组织")
                self.assertEqual(row.snapshot_version, 1)
                self.assertIn("users.csv", row.material_note)
                self.assertIn("issuer", row.material_note)
