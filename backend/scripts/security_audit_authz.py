"""
Deep authenticated authorization / IDOR scan (multi-role).

Run with API up and demo seed accounts available:
  python scripts/security_audit_authz.py

Exit 0 if all checks pass; 1 if any FAIL.
"""
from __future__ import annotations

import base64
import json
import sys
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass, field
from typing import Any

BASE = "http://127.0.0.1:19001/api"


@dataclass
class Result:
    name: str
    ok: bool
    detail: str = ""
    severity: str = "high"  # high if fail is security-relevant


@dataclass
class Report:
    items: list[Result] = field(default_factory=list)

    def add(self, name: str, ok: bool, detail: str = "", severity: str = "high") -> None:
        self.items.append(Result(name, ok, detail, severity))
        tag = "PASS" if ok else "FAIL"
        print(f"[{tag}] {name}" + (f" — {detail[:160]}" if detail else ""))

    def summary(self) -> int:
        fails = [r for r in self.items if not r.ok]
        print("---")
        print(f"authz: {len(self.items) - len(fails)} pass, {len(fails)} fail / {len(self.items)} total")
        for f in fails:
            print(f"  FAIL({f.severity}): {f.name} | {f.detail[:200]}")
        return 1 if fails else 0


def req(
    method: str,
    path: str,
    body: Any = None,
    token: str | None = None,
    query: str | None = None,
    timeout: float = 15,
) -> tuple[int, str, dict[str, str]]:
    url = BASE + path
    if query:
        url += "?" + query
    data = None
    h = {"Accept": "application/json"}
    if body is not None:
        data = json.dumps(body).encode()
        h["Content-Type"] = "application/json"
    if token:
        h["Authorization"] = "Bearer " + token
    r = urllib.request.Request(url, data=data, headers=h, method=method)
    try:
        with urllib.request.urlopen(r, timeout=timeout) as resp:
            headers = {k.lower(): v for k, v in resp.headers.items()}
            return resp.status, resp.read().decode(errors="replace"), headers
    except urllib.error.HTTPError as e:
        headers = {k.lower(): v for k, v in e.headers.items()} if e.headers else {}
        return e.code, e.read().decode(errors="replace"), headers
    except Exception as e:  # noqa: BLE001
        return 0, str(e), {}


def login(username: str, password: str) -> str:
    c, t, _ = req("POST", "/auth/login", {"username": username, "password": password})
    if c != 200:
        raise RuntimeError(f"login {username} failed: {c} {t[:200]}")
    return json.loads(t)["access_token"]


def me(token: str) -> dict:
    c, t, _ = req("GET", "/auth/me", token=token)
    assert c == 200, t
    return json.loads(t)


def denied(code: int) -> bool:
    return code in (401, 403, 404)


def not_success_data(code: int) -> bool:
    """True if request did not succeed with usable data (includes validation errors)."""
    return code in (400, 401, 403, 404, 405, 422, 429)


def b64url(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode()


def forge_none_alg_jwt(sub: str) -> str:
    """JWT with alg=none (should be rejected by PyJWT)."""
    header = b64url(json.dumps({"alg": "none", "typ": "JWT"}).encode())
    payload = b64url(json.dumps({"sub": sub, "role": "super_admin"}).encode())
    return f"{header}.{payload}."


def forge_hs256_empty_sig(sub: str) -> str:
    header = b64url(json.dumps({"alg": "HS256", "typ": "JWT"}).encode())
    payload = b64url(json.dumps({"sub": sub, "role": "super_admin"}).encode())
    return f"{header}.{payload}.AAAA"


def main() -> int:
    rep = Report()
    print(f"[*] Target: {BASE}")
    print("[*] Logging in roles...")

    try:
        tok_admin = login("admin", "admin123")
        tok_issuer = login("issuer", "issuer123")
        tok_m1 = login("merchant1", "merchant123")
        tok_m2 = login("merchant2", "merchant123")
        tok_y1 = login("youth1", "youth123")
        tok_y2 = login("youth2", "youth123")
    except RuntimeError as e:
        print(f"[FATAL] {e}")
        print("Need SEED_DEMO_ACCOUNTS and demo passwords (admin/admin123 etc.)")
        return 2

    admin = me(tok_admin)
    y1 = me(tok_y1)
    y2 = me(tok_y2)
    m1 = me(tok_m1)
    m2 = me(tok_m2)
    print(f"    admin={admin['id'][:8]}… youth1={y1['id'][:8]}… youth2={y2['id'][:8]}…")
    print(f"    merchant1={m1.get('merchant_id')} merchant2={m2.get('merchant_id')}")

    # ---------- Vertical: youth must not reach admin surfaces ----------
    print("\n== Vertical privilege (youth) ==")
    for path, method, body in [
        ("/auth/accounts", "GET", None),
        ("/auth/email/smtp-status", "GET", None),
        ("/stats/dashboard", "GET", None),
        ("/stats/audit-logs", "GET", None),
        ("/users", "GET", None),
        ("/users/pending-verifications", "GET", None),
        ("/export/users", "GET", None),
        ("/export/redemptions", "GET", None),
        ("/points/grant", "POST", {"user_id": y1["id"], "change": 1, "reason": "hack"}),
        ("/points/grant-batch", "POST", {"items": [{"user_id": y1["id"], "change": 1}], "reason": "x"}),
        ("/coupons/issue", "POST", {"user_id": y1["id"], "template_id": "x", "quantity": 1}),
        ("/merchants", "POST", {"name": "evil"}),
        ("/auth/issue-admins", "POST", {"username": "eviladmin", "password": "evilpass12"}),
    ]:
        c, t, _ = req(method, path, body, token=tok_y1)
        # FastAPI may 404 if route role-gated differently; 422 for bad body still means auth passed!
        # Critical: 200 means success; 422 after auth is still a problem for write endpoints if body is wrong
        # For grant with wrong schema might be 422 - check if we got past auth
        if path == "/points/grant" and c == 422:
            # try correct schema from API
            c, t, _ = req(
                "POST",
                "/points/grant",
                {"user_id": y1["id"], "amount": 1, "reason": "hack"},
                token=tok_y1,
            )
        ok = denied(c) or (c == 404 and "dashboard" in path)
        # 422 with role check usually happens after auth - if require_roles fails it's 403
        if c == 422 and method == "POST":
            # body validation after auth = privilege escalation to "can call endpoint"
            # Actually require_roles runs as Depends before body validation in FastAPI... 
            # Order: path deps then body. require_roles is Depends so runs first → 403 if no role.
            ok = False  # wait, if 422, auth passed
            # In FastAPI, dependency injection for route runs before body validation for the endpoint.
            # Actually for POST, both are resolved - security deps typically first.
            # If we get 422, the user was authorized for the route. That's a FAIL for youth on admin routes.
            ok = False
            # Unless it's a route youth is allowed on - none of these are
            ok = c in (401, 403, 404)
        rep.add(f"youth blocked {method} {path}", ok, f"{c} {t[:80]}")

    # ---------- Merchant must not reach admin / other user PII ----------
    print("\n== Vertical privilege (merchant) ==")
    for path in [
        "/auth/accounts",
        "/stats/dashboard",
        "/stats/audit-logs",
        "/users",
        "/export/users",
        f"/users/{y1['id']}",
        f"/users/{y1['id']}/bank-card",
        f"/points/users/{y1['id']}",
    ]:
        c, t, _ = req("GET", path, token=tok_m1)
        rep.add(f"merchant blocked GET {path}", denied(c) or c == 404, f"{c}")

    # issuer cannot manage accounts / smtp / reset others as super only endpoints
    print("\n== Vertical privilege (issuer) ==")
    c, t, _ = req("GET", "/auth/email/smtp-status", token=tok_issuer)
    rep.add("issuer blocked smtp-status", denied(c), f"{c}")
    c, t, _ = req(
        "POST",
        f"/auth/accounts/{y1['id']}/reset-password",
        {"new_password": "hacked999"},
        token=tok_issuer,
    )
    rep.add("issuer cannot reset user password", denied(c), f"{c} {t[:60]}")
    c, t, _ = req("GET", f"/users/{y1['id']}/bank-card", token=tok_issuer)
    rep.add("issuer cannot reveal full bank card", denied(c), f"{c}")

    # ---------- Horizontal IDOR: youth2 must not access youth1 resources ----------
    print("\n== Horizontal IDOR (youth2 → youth1) ==")
    c, t, _ = req("GET", f"/users/{y1['id']}", token=tok_y2)
    rep.add("youth2 cannot GET youth1 profile by id", denied(c), f"{c}")

    c, t, _ = req("GET", f"/users/{y1['id']}/verifications", token=tok_y2)
    rep.add("youth2 cannot list youth1 verifications", denied(c), f"{c}")

    c, t, _ = req("GET", f"/users/{y1['id']}/bank-card", token=tok_y2)
    rep.add("youth2 cannot reveal youth1 bank card", denied(c), f"{c}")

    c, t, _ = req("GET", f"/points/users/{y1['id']}", token=tok_y2)
    rep.add("youth2 cannot read youth1 points", denied(c), f"{c}")

    # coupons: list instances with user_id filter as youth should only see self
    c, t, _ = req("GET", "/coupons/instances", token=tok_y2, query=f"user_id={y1['id']}")
    if c == 200:
        data = json.loads(t)
        items = data.get("items") if isinstance(data, dict) else data
        if items is None and isinstance(data, list):
            items = data
        if isinstance(data, dict) and "items" in data:
            items = data["items"]
        leaked = [i for i in (items or []) if i.get("user_id") == y1["id"] and i.get("user_id") != y2["id"]]
        # youth filter forces own user_id in API — items should only be y2's
        foreign = [i for i in (items or []) if i.get("user_id") and i.get("user_id") != y2["id"]]
        rep.add(
            "youth2 coupon list cannot include youth1 coupons",
            len(foreign) == 0,
            f"foreign={len(foreign)} total={len(items or [])}",
        )
    else:
        rep.add("youth2 coupon instances accessible", c in (200, 403), f"{c}")

    # live-code IDOR: get youth1 coupon id via admin, try as youth2
    c, t, _ = req("GET", "/coupons/instances", token=tok_admin, query=f"user_id={y1['id']}&limit=5")
    y1_coupon_id = None
    if c == 200:
        payload = json.loads(t)
        items = payload.get("items") or []
        if items:
            y1_coupon_id = items[0]["id"]
    if y1_coupon_id:
        c, t, _ = req("GET", f"/coupons/instances/{y1_coupon_id}/live-code", token=tok_y2)
        rep.add("youth2 cannot get youth1 live-code", denied(c), f"{c} {t[:60]}")
        c, t, _ = req("POST", f"/coupons/instances/{y1_coupon_id}/void", {"reason": "steal"}, token=tok_y2)
        rep.add("youth2 cannot void youth1 coupon", denied(c) or c in (400, 422), f"{c}")
        c, t, _ = req("GET", f"/coupons/instances/{y1_coupon_id}/live-code", token=tok_m1)
        rep.add("merchant cannot get user live-code", denied(c), f"{c}")
    else:
        rep.add("youth1 has coupon for live-code IDOR", False, "no coupon — seed demo coupon?", "info")

    # ---------- Cross-merchant isolation ----------
    print("\n== Cross-merchant ==")
    c, t, _ = req("GET", "/coupons/instances", token=tok_m1, query="limit=50")
    if c == 200:
        items = json.loads(t).get("items") or []
        mid = m1.get("merchant_id")
        wrong = [i for i in items if i.get("merchant_id") and i.get("merchant_id") != mid]
        rep.add("merchant1 instances only own shop", len(wrong) == 0, f"wrong={len(wrong)} n={len(items)}")
    else:
        rep.add("merchant1 list instances", False, f"{c}")

    # redeem/preview other merchant's coupon if we can find one
    c, t, _ = req("GET", "/coupons/instances", token=tok_admin, query=f"merchant_id={m2.get('merchant_id')}&limit=5")
    if c == 200:
        items = json.loads(t).get("items") or []
        other = [i for i in items if i.get("status") == "unused"]
        if other:
            code = other[0].get("code")
            c2, t2, _ = req("GET", "/coupons/preview", token=tok_m1, query=urllib.parse.urlencode({"code": code}))
            # should be 400 not this shop
            rep.add(
                "merchant1 cannot preview merchant2 coupon",
                c2 in (400, 403, 404),
                f"{c2} {t2[:80]}",
            )
        else:
            rep.add("cross-merchant preview sample", True, "no unused m2 coupon (skip)", "info")
    else:
        rep.add("admin list m2 coupons", c == 200, f"{c}", "info")

    # ---------- Bank card reveal only super_admin ----------
    print("\n== Bank card ==")
    c, t, _ = req("GET", f"/users/{y1['id']}/bank-card", token=tok_admin)
    # 404 if unbound is OK; 200 only for admin
    rep.add(
        "admin bank-card reveal only 200 or 404",
        c in (200, 404),
        f"{c}",
    )
    if c == 200 and "card_number" in t:
        # ensure youth cannot
        pass
    for role_name, tok in [("youth1", tok_y1), ("merchant1", tok_m1), ("issuer", tok_issuer)]:
        c, t, _ = req("GET", f"/users/{y1['id']}/bank-card", token=tok)
        rep.add(f"{role_name} cannot reveal bank card", denied(c), f"{c}")

    # ---------- JWT attacks ----------
    print("\n== JWT attacks ==")
    none_tok = forge_none_alg_jwt(admin["id"])
    c, t, _ = req("GET", "/auth/me", token=none_tok)
    rep.add("reject alg=none JWT", c in (401, 403), f"{c}")

    bad = forge_hs256_empty_sig(admin["id"])
    c, t, _ = req("GET", "/auth/me", token=bad)
    rep.add("reject forged HS256 JWT", c in (401, 403), f"{c}")

    # use youth token on admin path
    c, t, _ = req("GET", "/auth/accounts", token=tok_y1)
    rep.add("youth token not accepted for accounts", denied(c), f"{c}")

    # tamper: use admin token path but that's expected to work

    # ---------- Mass assignment / role on register (if possible without SMTP) ----------
    print("\n== Mass assignment ==")
    c, t, _ = req(
        "POST",
        "/auth/register",
        {
            "email": "evil_role_probe@example.com",
            "password": "evilpass12",
            "code": "000000",
            "role": "super_admin",
            "display_name": "evil",
        },
    )
    # should not create super_admin; 400 bad code or validation
    if c == 200:
        acc = json.loads(t)
        rep.add("register ignores role=super_admin", acc.get("role") == "user", f"role={acc.get('role')}")
    else:
        rep.add("register with role field rejected or needs code", c in (400, 422), f"{c} {t[:80]}", "info")

    # ---------- Account takeover paths ----------
    print("\n== Account takeover surfaces ==")
    c, t, _ = req(
        "POST",
        f"/auth/accounts/{admin['id']}/set-active",
        {"is_active": False},
        token=tok_y1,
    )
    rep.add("youth cannot deactivate admin", denied(c), f"{c}")

    c, t, _ = req(
        "POST",
        f"/auth/accounts/{y1['id']}/reset-password",
        {"new_password": "hacked999"},
        token=tok_m1,
    )
    rep.add("merchant cannot reset youth password", denied(c), f"{c}")

    # youth change password with wrong old
    c, t, _ = req(
        "POST",
        "/auth/change-password",
        {"old_password": "wrong-old-pass", "new_password": "newpass999"},
        token=tok_y1,
    )
    rep.add("change-password rejects wrong old password", c in (400, 422), f"{c}")

    # ---------- IDOR on verification review ----------
    print("\n== Verification review ==")
    c, t, _ = req("GET", "/users/pending-verifications", token=tok_admin)
    if c == 200:
        pending = json.loads(t)
        if pending:
            vid = pending[0]["id"]
            c2, t2, _ = req(
                "POST",
                f"/users/verifications/{vid}/review",
                {"approve": True, "review_note": "idor"},
                token=tok_y1,
            )
            rep.add("youth cannot review verification", denied(c2), f"{c2}")
            c3, t3, _ = req(
                "POST",
                f"/users/verifications/{vid}/review",
                {"approve": True, "review_note": "idor"},
                token=tok_m1,
            )
            rep.add("merchant cannot review verification", denied(c3), f"{c3}")
        else:
            rep.add("pending verifications for review IDOR", True, "none pending (skip)", "info")
    else:
        rep.add("admin pending-verifications", c == 200, f"{c}", "info")

    # ---------- Security headers on authenticated response ----------
    print("\n== Headers ==")
    c, t, h = req("GET", "/auth/me", token=tok_y1)
    rep.add(
        "auth response has X-Content-Type-Options",
        h.get("x-content-type-options", "").lower() == "nosniff",
        str(h.get("x-content-type-options")),
        "medium",
    )
    rep.add(
        "auth response has X-Frame-Options",
        h.get("x-frame-options", "").upper() == "DENY",
        str(h.get("x-frame-options")),
        "medium",
    )

    # ---------- Export as wrong roles ----------
    print("\n== Export ==")
    for path in ["/export/redemptions", "/export/coupons", "/export/users", "/export/points-ledger"]:
        c, t, _ = req("GET", path, token=tok_y1)
        rep.add(f"youth blocked {path}", denied(c), f"{c}")

    # merchant may export own redemptions only — must not pull other merchant via query
    mid2 = m2.get("merchant_id") or ""
    c, t, _ = req(
        "GET",
        "/export/redemptions",
        token=tok_m1,
        query=urllib.parse.urlencode({"merchant_id": mid2}),
    )
    if c == 200:
        # CSV should not list the other shop name excessively; structural: request ok but scoped
        rep.add(
            "merchant export redemptions allowed (own shop)",
            True,
            f"status={c} bytes={len(t)}",
            "info",
        )
        # If merchant2 name appears while merchant1 exports with merchant_id=m2, possible leak —
        # soft check: still pass if empty export; flag only if we know m2 name in body AND m1 name absent
        m2_acc = me(tok_m2)
        # cannot easily get merchant name without another call; use admin list
        c_m, t_m, _ = req("GET", f"/merchants/{mid2}", token=tok_admin)
        m2_name = ""
        if c_m == 200:
            m2_name = json.loads(t_m).get("name") or ""
        if m2_name and m2_name in t:
            # might still appear if shared history; compare with m1-only export
            c1, t1, _ = req("GET", "/export/redemptions", token=tok_m1)
            # If forcing merchant_id=m2 yields more m2_name hits than plain export, suspicious
            forced = t.count(m2_name)
            plain = t1.count(m2_name) if c1 == 200 else 0
            rep.add(
                "merchant export ignores other merchant_id filter",
                forced <= plain,
                f"forced_hits={forced} plain_hits={plain} name={m2_name}",
            )
        else:
            rep.add("merchant export no foreign shop name", True, "ok", "info")
    else:
        rep.add("merchant export redemptions", c in (200, 403), f"{c}")

    for path in ["/export/coupons", "/export/users", "/export/points-ledger"]:
        c, t, _ = req("GET", path, token=tok_m1)
        rep.add(f"merchant blocked {path}", denied(c), f"{c}")

    # ---------- Positive control: owner can get own live-code ----------
    print("\n== Positive controls ==")
    if y1_coupon_id:
        c, t, _ = req("GET", f"/coupons/instances/{y1_coupon_id}/live-code", token=tok_y1)
        rep.add("youth1 can get own live-code", c == 200 and "live_code" in t, f"{c}")
    c, t, _ = req("GET", "/auth/me", token=tok_admin)
    rep.add("admin me works", c == 200 and admin["id"] in t, f"{c}")

    return rep.summary()


if __name__ == "__main__":
    raise SystemExit(main())
