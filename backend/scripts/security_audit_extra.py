"""Additional IDOR / business logic probes."""
from __future__ import annotations

import json
import urllib.error
import urllib.parse
import urllib.request

BASE = "http://127.0.0.1:19001/api"


def req(method, path, body=None, token=None, query=None):
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
        with urllib.request.urlopen(r, timeout=12) as resp:
            return resp.status, resp.read().decode()
    except urllib.error.HTTPError as e:
        return e.code, e.read().decode()


def login(u, p):
    c, t = req("POST", "/auth/login", {"username": u, "password": p})
    assert c == 200, t
    return json.loads(t)["access_token"]


def main():
    youth = login("youth1", "youth123")
    admin = login("admin", "admin123")
    merchant = login("merchant1", "merchant123")
    results = []

    def note(name, ok, detail=""):
        results.append((name, ok, detail))
        print(("PASS" if ok else "FAIL"), name, detail[:120])

    c, t = req("POST", "/coupons/issue", {"user_id": "x", "template_id": "y", "quantity": 1}, youth)
    note("youth cannot issue coupon", c in (401, 403, 422), f"{c}")

    c, t = req("GET", "/coupons/my", token=youth)
    items = json.loads(t) if c == 200 else []
    if items:
        cid = items[0]["id"]
        c2, _ = req("GET", f"/coupons/instances/{cid}/live-code", token=youth)
        note("owner live-code ok", c2 == 200, str(c2))
        c3, t3 = req("GET", f"/coupons/instances/{cid}/live-code", token=merchant)
        note("merchant cannot get user live-code", c3 in (401, 403, 404), f"{c3} {t3[:80]}")
        c4, _ = req("POST", f"/coupons/instances/{cid}/void", {"reason": "hack"}, youth)
        note("youth cannot void coupon", c4 in (401, 403, 404, 422), str(c4))
    else:
        note("youth has coupons for IDOR tests", False, "no coupons")

    c, _ = req("POST", "/coupons/redeem", {"code": "AAAA"})
    note("anon redeem denied", c in (401, 403, 422), str(c))

    c, _ = req("POST", "/points/grant", {"user_id": "x", "amount": 999, "reason": "x"}, youth)
    note("youth cannot grant points", c in (401, 403, 422), str(c))

    q = urllib.parse.urlencode({"date_from": "2020-01-01' OR '1'='1", "date_to": "2099-12-31"})
    c, t = req("GET", "/export/redemptions", token=admin, query=q)
    note(
        "export date filter no 5xx/sql error",
        c in (200, 400, 422) and "sqlalchemy" not in t.lower() and "syntax error" not in t.lower(),
        f"{c}",
    )

    c, t = req("PUT", "/users/me/bank-card", {"card_number": "1234", "bank_name": "x"}, youth)
    note("reject short bank card", c in (400, 422), f"{c} {t[:60]}")

    # path id injection (URL-encoded)
    c, t = req("GET", "/users/" + urllib.parse.quote("' OR '1'='1"), token=admin)
    note("user id path injection not 500", c in (400, 404, 422) and c < 500, str(c))

    # JWT: login then use token on merchant redeem with fake body
    c, t = req("POST", "/coupons/redeem", {"code": "NOTREALCODE123"}, merchant)
    note("merchant redeem invalid code safe", c in (400, 404, 422), f"{c}")

    print("---")
    fails = [r for r in results if not r[1]]
    print(f"extra: {len(results)-len(fails)} pass, {len(fails)} fail")
    return 1 if fails else 0


if __name__ == "__main__":
    raise SystemExit(main())
