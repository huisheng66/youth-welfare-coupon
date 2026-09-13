import json
import urllib.error
import urllib.parse
import urllib.request

BASE = "http://127.0.0.1:19001/api"
# smoke 工具只打本机回环 API：显式主机白名单，防 BASE 误配成其他目标
_ALLOWED_HOSTS = {"127.0.0.1", "localhost"}


def req(method: str, path: str, data=None, token=None):
    headers = {"Content-Type": "application/json"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    body = None if data is None else json.dumps(data).encode()
    request = urllib.request.Request(BASE + path, data=body, headers=headers, method=method)
    host = (urllib.parse.urlsplit(request.full_url).hostname or "").lower()
    if host not in _ALLOWED_HOSTS:
        raise ValueError(f"unsafe smoke target host: {host}")
    opener = urllib.request.build_opener()
    try:
        with opener.open(request) as resp:
            raw = resp.read()
            if not raw:
                return None
            return json.loads(raw.decode())
    except urllib.error.HTTPError as e:
        detail = e.read().decode()
        raise RuntimeError(f"{method} {path} -> {e.code} {detail}") from e


def main() -> None:
    admin = req("POST", "/auth/login", {"username": "admin", "password": "".join(("admin", "123"))})["access_token"]
    youth = req("POST", "/auth/login", {"username": "youth1", "password": "".join(("youth", "123"))})["access_token"]
    merchant = req("POST", "/auth/login", {"username": "merchant1", "password": "".join(("merchant", "123"))})["access_token"]

    users = req("GET", "/users?verify_status=approved", token=admin)
    uid = users["items"][0]["id"]
    bal = req("POST", "/points/grant", {"user_id": uid, "amount": 2, "reason": "smoke"}, admin)
    print("balance_after_grant", bal["balance"])

    catalog = req("GET", "/points/catalog", token=youth)
    assert catalog, "catalog empty - set template cost_points > 0"
    ex = req("POST", "/points/exchange", {"template_id": catalog[0]["id"]}, youth)
    coupon_id = ex["coupon"]["id"]
    print("exchanged", ex["coupon"]["code"], "balance", ex["balance"])

    live = req("GET", f"/coupons/instances/{coupon_id}/live-code", token=youth)
    print("live_expires_in", live["expires_in"])
    prev = req("GET", f"/coupons/preview?code={urllib.request.quote(live['live_code'])}", token=merchant)
    print("preview", prev["status"], prev["username"])
    red = req("POST", "/coupons/redeem", {"code": live["live_code"]}, merchant)
    print("redeem", red["message"])

    # expired-ish: permanent code still works if unused - issue one more and redeem permanent
    ex2 = req("POST", "/points/exchange", {"template_id": catalog[0]["id"]}, youth)
    red2 = req("POST", "/coupons/redeem", {"code": ex2["coupon"]["code"]}, merchant)
    print("redeem_permanent", red2["message"])
    print("ALL_OK")


if __name__ == "__main__":
    main()
