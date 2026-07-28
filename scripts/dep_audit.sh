#!/usr/bin/env bash
# Dependency audit: pip-audit (backend) + npm audit (frontend)
# Exit non-zero if high/critical issues found (npm) or pip-audit fails.
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
FAIL=0

echo "==> Backend pip-audit (requirements.txt)"
cd "${ROOT}/backend"
if [[ -x .venv/bin/python ]]; then
  PY=.venv/bin/python
elif command -v python3 >/dev/null 2>&1; then
  PY=python3
else
  PY=python
fi
$PY -m pip install -q "pip-audit>=2.7" || true
if ! $PY -m pip_audit -r requirements.txt --progress-spinner off; then
  echo "pip-audit reported issues" >&2
  FAIL=1
fi

echo ""
echo "==> Frontend npm audit --production (high+)"
cd "${ROOT}/frontend"
if [[ ! -f package-lock.json ]]; then
  echo "package-lock.json missing; run npm install first" >&2
  FAIL=1
else
  # npm audit exits 1 when vulnerabilities at or above audit-level exist
  if ! npm audit --omit=dev --audit-level=high; then
    echo "npm audit reported high/critical issues" >&2
    FAIL=1
  fi
fi

echo ""
if [[ "$FAIL" -ne 0 ]]; then
  echo "dep_audit: FAILED (see above)"
  exit 1
fi
echo "dep_audit: OK"
exit 0
