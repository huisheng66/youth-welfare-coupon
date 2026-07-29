#!/usr/bin/env bash
set -euo pipefail
echo "=== schema ==="
sed -n '157,172p' /opt/welfare/backend/app/schemas/auth.py
echo "=== endpoint ==="
sed -n '396,418p' /opt/welfare/backend/app/api/auth.py
echo "=== sample 422s ==="
curl -sS -m 10 -X POST http://127.0.0.1:19001/api/auth/issue-admins \
  -H 'Content-Type: application/json' -d '{}'
echo
curl -sS -m 10 -X POST http://127.0.0.1:19001/api/auth/issue-admins \
  -H 'Content-Type: application/json' -d '{"username":"i1","password":"12345678"}'
echo
curl -sS -m 10 -X POST http://127.0.0.1:19001/api/auth/issue-admins \
  -H 'Content-Type: application/json' -d '{"username":"issuerok","password":"1234567"}'
echo
# login as admin if possible? skip
# check body size of real 422 pattern
python3 - <<'PY'
from pydantic import ValidationError
import sys
sys.path.insert(0,'/opt/welfare/backend')
from app.schemas.auth import CreateIssueAdminIn
import json
for c in [
  {},
  {"username":"ab","password":"12345678"},
  {"username":"issuer1","password":"short"},
  {"username":"issuer1","password":"12345678","display_name":""},
]:
  try:
    CreateIssueAdminIn(**c)
    print('ok', c)
  except ValidationError as e:
    s=e.json()
    print('fail', c, 'len', len(s))
    print(s[:200])
PY
