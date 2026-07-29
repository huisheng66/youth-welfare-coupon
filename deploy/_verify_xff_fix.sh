#!/usr/bin/env bash
set -euo pipefail
echo "=== ufw web/ssh ==="
ufw status numbered | grep -E '80|443|OpenSSH|cf-origin|Nginx' | head -50
echo
echo "=== realip ==="
wc -l /etc/nginx/conf.d/cloudflare-realip.conf
tail -5 /etc/nginx/conf.d/cloudflare-realip.conf
echo
echo "=== local API XFF spoof (peer=127.0.0.1) ==="
python3 <<'PY'
import json, urllib.request, urllib.error, time
BASE = "http://127.0.0.1:19001/api"
user = f"localxff_{int(time.time())}"

def login(u, headers=None):
    h = {"Content-Type": "application/json"}
    if headers:
        h.update(headers)
    r = urllib.request.Request(
        BASE + "/auth/login",
        data=json.dumps({"username": u, "password": "x"}).encode(),
        headers=h,
        method="POST",
    )
    try:
        with urllib.request.urlopen(r, timeout=8) as resp:
            return resp.status, resp.read()[:60]
    except urllib.error.HTTPError as e:
        return e.code, e.read()[:80]

codes = []
for i in range(15):
    c, b = login(
        user,
        {
            "X-Forwarded-For": f"1.1.1.{i}",
            "CF-Connecting-IP": f"2.2.2.{i}",
            "X-Real-IP": f"3.3.3.{i}",
        },
    )
    codes.append(c)
    if c == 429:
        break
print("spoof codes:", codes)
c2, b2 = login(
    user,
    {
        "X-Forwarded-For": "9.9.9.9",
        "CF-Connecting-IP": "8.8.8.8",
        "X-Real-IP": "7.7.7.7",
    },
)
print("after lock new spoof:", c2, b2)
assert 429 in codes, "expected 429 by username bucket"
assert c2 == 429, "expected still 429 after XFF rotate"
print("PASS username rate limit resists XFF spoof")
PY

echo "=== domain health ==="
curl -sS -m 12 https://youth.huishengbook.us.ci/api/health
echo
echo "=== direct origin from server to public IP (self) ==="
curl -sk -m 5 -o /dev/null -w 'code=%{http_code}\n' --resolve youth.huishengbook.us.ci:443:127.0.0.1 https://youth.huishengbook.us.ci/api/health || true
