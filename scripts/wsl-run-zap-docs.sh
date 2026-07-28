#!/usr/bin/env bash
# ZAP quick scan against API docs root (returns 2xx)
set -uo pipefail
TARGET="${1:-http://172.29.0.1:19001/docs}"
REPORT_DIR="/mnt/d/卡系统/reports"
mkdir -p "$REPORT_DIR"
STAMP=$(date +%Y%m%d-%H%M%S)
HTML="$REPORT_DIR/zap-baseline-$STAMP.html"
LOG="$REPORT_DIR/zap-console-$STAMP.log"
MD="$REPORT_DIR/zap-baseline-$STAMP.md"

echo "Target=$TARGET"
code=$(curl -s -o /dev/null -w "%{http_code}" --connect-timeout 5 "$TARGET" || echo fail)
echo "HTTP $code"
if [[ "$code" != "200" && "$code" != "301" && "$code" != "302" ]]; then
  # fallback health
  TARGET="${TARGET%/docs}/api/health"
  code=$(curl -s -o /dev/null -w "%{http_code}" --connect-timeout 5 "$TARGET" || echo fail)
  echo "fallback Target=$TARGET HTTP $code"
fi

/opt/zap/zap.sh -cmd \
  -quickurl "$TARGET" \
  -quickout "$HTML" \
  -quickprogress \
  2>&1 | tee "$LOG"
ZAP_EXIT=${PIPESTATUS[0]}

python3 - "$HTML" "$MD" "$TARGET" "$ZAP_EXIT" <<'PY'
import re, sys, pathlib
html_path, md_path, target, zap_exit = sys.argv[1:5]
p = pathlib.Path(html_path)
html = p.read_text(encoding="utf-8", errors="replace") if p.exists() else ""
lines = [
    "# OWASP ZAP quick scan summary",
    "",
    f"- Target: `{target}`",
    f"- ZAP exit: {zap_exit}",
    f"- Report: `{html_path}`",
    f"- Size: {len(html)} bytes",
    "",
    "## Notes",
    "",
    "- Scan started from `/docs` (or `/api/health`) because site root returns 404.",
    "- This is a ZAP *quick* scan (spider + active), not the full Docker baseline policy.",
    "",
    "## Risk keywords in HTML",
    "",
]
for level in ["High", "Medium", "Low", "Informational", "False Positive"]:
    # count table cells / badges
    n = len(re.findall(rf"\b{level}\b", html))
    lines.append(f"- **{level}**: ~{n} text hits")
lines.append("")
# extract alert-like headings
titles = re.findall(r"<h[23][^>]*>([^<]{4,120})</h[23]>", html, flags=re.I)
if titles:
    lines.append("## Headings")
    lines.append("")
    for t in titles[:40]:
        lines.append(f"- {t.strip()}")
    lines.append("")
# common ZAP report: alert name in <td>
alerts = re.findall(
    r"alertname[\"']?\s*[:=]\s*[\"']([^\"']+)",
    html,
    flags=re.I,
)
if not alerts:
    alerts = re.findall(r">((?:Cross Site|SQL|Path|Remote|Server|Content|X-|Cookie|CSRF|Session|Open|Incomplete)[^<]{0,80})<", html)
if alerts:
    lines.append("## Alert-like strings")
    lines.append("")
    for a in list(dict.fromkeys(alerts))[:40]:
        lines.append(f"- {a.strip()}")
pathlib.Path(md_path).write_text("\n".join(lines) + "\n", encoding="utf-8")
print("WROTE", md_path)
print("EXIT", zap_exit)
print("HTML_EXISTS", p.exists(), "SIZE", len(html))
PY

echo "DONE exit=$ZAP_EXIT html=$HTML"
exit 0
