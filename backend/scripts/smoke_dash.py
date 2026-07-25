import json
import urllib.request

BASE = "http://127.0.0.1:19001/api"


def req(method, path, data=None, token=None):
    headers = {"Content-Type": "application/json"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    body = None if data is None else json.dumps(data).encode()
    r = urllib.request.Request(BASE + path, data=body, headers=headers, method=method)
    with urllib.request.urlopen(r) as resp:
        return json.load(resp)


tok = req("POST", "/auth/login", {"username": "admin", "password": "admin123"})["access_token"]
d = req("GET", "/dashboard", token=tok)
print("pending", d["pending_verifications"])
print("unused", d["unused_coupons"])
print("activity", len(d.get("recent_activity") or []))
print("ALL_OK")
