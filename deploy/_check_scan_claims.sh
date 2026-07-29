#!/usr/bin/env bash
set -euo pipefail
echo "=== nginx version / server_tokens ==="
nginx -v 2>&1 || true
grep -RIn 'server_tokens' /etc/nginx/ 2>/dev/null || echo 'server_tokens not set (default on)'
echo
echo "=== response headers (local origin) ==="
curl -sk -D- -o /dev/null -H 'Host: youth.huishengbook.us.ci' https://127.0.0.1/api/health | tr -d '\r' | head -30
echo
echo "=== env flags ==="
grep -E '^(APP_ENV|SEED|OPENAPI|CORS)' /opt/welfare/backend/.env
echo
echo "=== no pickle in app ==="
grep -RIn 'pickle\|yaml.load\|marshal\|eval(\|exec(' /opt/welfare/backend/app 2>/dev/null || echo 'none in app/'
echo
echo "=== uvicorn/fastapi versions ==="
/opt/welfare/backend/.venv/bin/python -c "import importlib.metadata as m; print('fastapi',m.version('fastapi')); print('uvicorn',m.version('uvicorn')); print('starlette',m.version('starlette'))"
