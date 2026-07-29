#!/bin/bash
set -e
echo "=== change-password access lines ==="
grep -h change-password /var/log/nginx/access.log /var/log/nginx/access.log.1 2>/dev/null | tail -20 || true

echo "=== 499 client closed (recent) ==="
grep ' 499 ' /var/log/nginx/access.log 2>/dev/null | tail -15 || true

echo "=== journal around change-password ==="
journalctl -u welfare-api --since '2026-07-28 14:20:00' --until '2026-07-28 14:25:00' --no-pager

echo "=== load / mem ==="
uptime
free -h | head -3
nproc

echo "=== bcrypt + endpoint timing (no password change) ==="
cd /opt/welfare/backend
.venv/bin/python3 <<'PY'
import time, json, urllib.request, urllib.error
from app.core.security import hash_password, verify_password

t0 = time.time()
h = hash_password("BenchPass123!")
print(f"hash: {time.time()-t0:.3f}s")
t0 = time.time()
verify_password("BenchPass123!", h)
print(f"verify: {time.time()-t0:.3f}s")
t0 = time.time()
verify_password("BenchPass123!", h)
hash_password("BenchPass123!")
print(f"verify+hash (change-password work): {time.time()-t0:.3f}s")

# login with current admin password — try common, do NOT change password
for pwd in ["Admin@Welfare2026", "admin123"]:
    try:
        req = urllib.request.Request(
            "http://127.0.0.1:19001/api/auth/login",
            data=json.dumps({"username": "admin", "password": pwd}).encode(),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        t0 = time.time()
        with urllib.request.urlopen(req, timeout=30) as r:
            body = json.load(r)
        print(f"login ok with one candidate, time={time.time()-t0:.3f}s token_len={len(body.get('access_token',''))}")
        break
    except urllib.error.HTTPError as e:
        print(f"login fail status={e.code} pwd_try_len={len(pwd)} time~{time.time()-t0:.3f}s")
    except Exception as e:
        print("login error", e)
PY

echo "=== nginx error recent timeouts ==="
grep -iE 'timeout|upstream|timed out' /var/log/nginx/error.log 2>/dev/null | tail -20 || true
