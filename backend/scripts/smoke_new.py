import json
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
    with opener.open(request) as resp:
        return json.load(resp)


def main() -> None:
    tok = req("POST", "/auth/login", {"username": "admin", "password": "".join(("admin", "123"))})["access_token"]
    users = req("GET", "/users?verify_status=approved", token=tok)
    youth = users["items"][0]
    tpl = req("GET", "/coupons/templates?active_only=true", token=tok)["items"][0]
    batch = req(
        "POST",
        "/coupons/issue-batch",
        {"user_ids": [youth["id"]], "template_id": tpl["id"], "quantity": 1},
        tok,
    )
    code = batch["issued"][0]["code"]
    print("batch_ok", code, "failed", len(batch["failed"]))

    mtok = req("POST", "/auth/login", {"username": "merchant1", "password": "".join(("merchant", "123"))})["access_token"]
    prev = req("GET", f"/coupons/preview?code={code}", token=mtok)
    print("preview", prev["status"], prev["username"])
    stats = req("GET", "/merchant-dashboard", token=mtok)
    print("stats", stats["today_success"], stats["total_success"])
    red = req("POST", "/coupons/redeem", {"code": code}, mtok)
    print("redeem", red["message"])
    detail = req("GET", f"/users/{youth['id']}", token=tok)
    print("detail", detail["verify_status"], detail.get("student_no"))
    print("ALL_OK")


if __name__ == "__main__":
    main()
