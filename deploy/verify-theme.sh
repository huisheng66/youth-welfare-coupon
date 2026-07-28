#!/usr/bin/env bash
set -euo pipefail
BASE="${1:-http://192.168.159.130}"
html=$(curl -sS "$BASE/")
css_path=$(printf '%s' "$html" | grep -oE 'assets/index-[^"]+\.css' | head -1)
echo "css=$css_path"
css=$(curl -sS "$BASE/$css_path")
if printf '%s' "$css" | grep -q '0f6e6a'; then
  echo "OK: classic brand #0f6e6a present"
else
  echo "FAIL: classic brand missing"
fi
if printf '%s' "$css" | grep -q '007aff'; then
  echo "WARN: Apple blue #007aff still present"
else
  echo "OK: no Apple blue #007aff"
fi
if printf '%s' "$css" | grep -q 'f3f6f8'; then
  echo "OK: classic bg #f3f6f8 present"
fi
