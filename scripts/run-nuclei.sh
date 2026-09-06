#!/usr/bin/env bash
# 用自家 nuclei 模板扫描目标（youth-auth-401 / youth-login-sqli / youth-role-idor）
#
# 用法：
#   bash scripts/run-nuclei.sh https://staging.example.com
#   bash scripts/run-nuclei.sh https://staging.example.com reports/nuclei.jsonl
#
# 模板维护约定：新增接口同步加 tools/nuclei-templates/ 模板；接口下线及时删对应模板。
# 安装 nuclei：https://docs.projectdiscovery.io/nuclei/get-started
set -euo pipefail

TARGET="${1:?usage: $0 <target-url> [output-file]}"
OUTPUT="${2:-nuclei-$(date +%Y%m%d-%H%M%S).jsonl}"

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT="$(dirname "$SCRIPT_DIR")"
TEMPLATES="$ROOT/tools/nuclei-templates"

if ! command -v nuclei >/dev/null 2>&1; then
  echo "nuclei not installed. Install: https://docs.projectdiscovery.io/nuclei/get-started" >&2
  exit 2
fi

if [ ! -d "$TEMPLATES" ]; then
  echo "templates dir not found: $TEMPLATES" >&2
  exit 2
fi

mkdir -p "$(dirname "$OUTPUT")"

echo "==> nuclei scan"
echo "    target:    $TARGET"
echo "    templates: $TEMPLATES"
echo "    output:    $OUTPUT"
echo

# -j：JSON Lines 输出；-o：写文件；-silent：只输出结果不打印 banner
# T19：扫描器失败 ≠ 无发现——非零退出且无结果文件时以错误退出，不得当作“无风险”
set +e
nuclei -t "$TEMPLATES" -u "$TARGET" -j -o "$OUTPUT" -silent
code=$?
set -e
if [ "$code" -ne 0 ] && [ ! -s "$OUTPUT" ]; then
  echo "==> nuclei scan FAILED (exit $code), no result file — treat as failure, not 'no findings'" >&2
  exit 3
fi
if [ "$code" -ne 0 ]; then
  echo "==> warning: nuclei exit $code but result file exists; judging by findings" >&2
fi

if [ -s "$OUTPUT" ]; then
  echo
  echo "==> findings:"
  cat "$OUTPUT"
  echo
  total=$(wc -l < "$OUTPUT")
  echo "==> total: $total finding(s) — investigate before release"
  # 非零退出码便于 CI 卡门禁（staging 应 0 高危）
  exit 1
else
  echo "==> scan completed: no findings, all clear"
fi
