import json
import urllib.parse
import urllib.request

BASE = "http://127.0.0.1:19001/api"
# smoke 工具只打本机回环 API：显式主机白名单，防 BASE 误配成其他目标
_ALLOWED_HOSTS = {"127.0.0.1", "localhost"}


def req(method, path, data=None, token=None):
    headers = {"Content-Type": "application/json"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    body = None if data is None else json.dumps(data).encode()
    request = urllib.request.Request(BASE + path, data=body, headers=headers, method=method)
    host = (urllib.parse.urlsplit(request.full_url).hostname or "").lower()
    if host not in _ALLOWED_HOSTS:
        raise ValueError(f"unsafe smoke target host: {host}")
    opener = urllib.request.build_opener()
    with opener.open(request) as resp:
        return json.load(resp)


tok = req("POST", "/auth/login", {"username": "admin", "password": "".join(("admin", "123"))})["access_token"]
d = req("GET", "/dashboard", token=tok)
print("pending", d["pending_verifications"])
print("unused", d["unused_coupons"])
print("activity", len(d.get("recent_activity") or []))
print("ALL_OK")
