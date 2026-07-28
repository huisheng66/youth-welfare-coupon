"""Parse ZAP HTML quick report for risk counts and alert names."""
from __future__ import annotations

import re
import sys
from pathlib import Path


def main() -> int:
    path = Path(sys.argv[1] if len(sys.argv) > 1 else "reports/zap-latest.html")
    html = path.read_text(encoding="utf-8", errors="replace")
    print(f"file={path} size={len(html)}")
    for level in ("High", "Medium", "Low", "Informational"):
        # ZAP HTML often: <td>High</td> or risk-3 etc.
        n = len(re.findall(rf">\s*{level}\s*<", html, flags=re.I))
        print(f"{level}: {n}")

    # Alert names: common patterns in ZAP reports
    names: list[str] = []
    names += re.findall(r"<td>\s*([A-Z][^<]{5,100}?)\s*</td>\s*<td>\s*(?:High|Medium|Low|Informational)", html)
    names += re.findall(r"alertname[\"']?\s*[:=]\s*[\"']([^\"']+)", html, flags=re.I)
    names += re.findall(r"<h3>\s*([^<]{5,100}?)\s*</h3>", html, flags=re.I)
    # ZAP 2.x JSON embedded?
    names += re.findall(r'"name"\s*:\s*"([^"]{5,100})"', html)

    # unique preserve order
    seen: set[str] = set()
    uniq: list[str] = []
    for n in names:
        n = n.strip()
        if n and n not in seen and n not in {"High", "Medium", "Low", "Informational"}:
            seen.add(n)
            uniq.append(n)
    print("alerts:")
    for n in uniq[:50]:
        print(f"  - {n}")

    # write summary next to html
    out = path.with_suffix(".summary.md")
    lines = [
        f"# ZAP parse summary",
        "",
        f"- Source: `{path.name}`",
        f"- Size: {len(html)}",
        "",
        "## Counts (HTML markers)",
        "",
    ]
    for level in ("High", "Medium", "Low", "Informational"):
        n = len(re.findall(rf">\s*{level}\s*<", html, flags=re.I))
        lines.append(f"- **{level}**: {n}")
    lines += ["", "## Alert-like names", ""]
    for n in uniq[:50]:
        lines.append(f"- {n}")
    if not uniq:
        lines.append("- (none extracted; open HTML in browser)")
    out.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"wrote {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
