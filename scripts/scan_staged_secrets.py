#!/usr/bin/env python3
"""扫描 Git 暂存内容 / 指定基准差异中的疑似凭据。

输出只含「文件:行号: 规则名」，绝不回显匹配内容（脱敏要求）。
命中即退出码 1，供本地与 CI 门禁使用。

用法：
  python scripts/scan_staged_secrets.py                # 扫描 git diff --cached
  python scripts/scan_staged_secrets.py --ref origin/main
                                                       # 扫描 ref...HEAD 的变更行
  python scripts/scan_staged_secrets.py --tree         # 全量扫描已跟踪文件
                                                       #（新分支首次推送等无基准场景）

误报处理：在匹配行追加标记 `secret-scan:allow` 即跳过该行。
"""

from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path

# 排除第三方/演示数据目录：测试夹具与字典文件充满假凭据，扫描它们只会制造噪音。
# deploy/archive/ 是已泄漏并要求轮换的历史脚本存档（见 deploy/README.md），
# 作为审计记录保留，但不作为增量扫描对象。
EXCLUDE_PREFIXES = (
    "backend/tests/",
    "frontend/e2e/",
    "frontend/node_modules/",
    "backend/.venv/",
    "frontend/dist/",
    "tools/",
    ".zcode/",
    "deploy/archive/",
)

# 仅全量扫描（--tree）时额外排除：后端既有审计/冒烟脚本含大量演示凭据夹具，
# 逐行标注误报成本过高；增量扫描（CI 门禁主路径）仍然覆盖该目录。
TREE_ONLY_EXCLUDES = ("backend/scripts/",)

# (规则名, 正则)。关注高置信度凭据形态，避免把普通业务代码挡在门外。
PATTERNS: list[tuple[str, str]] = [
    ("private-key-block", r"-----BEGIN (?:RSA |EC |DSA |OPENSSH |PGP )?PRIVATE KEY-----"),
    ("aws-access-key-id", r"\bAKIA[0-9A-Z]{16}\b"),
    ("slack-token", r"\bxox[baprs]-[0-9A-Za-z-]{10,}\b"),
    ("generic-api-key-assign", r"(?i)\b(?:api[_-]?key|api[_-]?secret|access[_-]?key)\b[\"']?\s*[:=]\s*[\"'][^\"'\s{$][^\"']{7,}[\"']"),
    # 覆盖 password/passwd/pwd/pass（含 SSH_PASS、DB_PASS 等项目实际命名）
    ("password-assign-literal", r"(?i)\b(?P<key>[A-Za-z0-9_]*(?:password|passwd|pwd|pass)[A-Za-z0-9_]*)\b[\"']?\s*[:=]\s*[\"'](?P<val>[^\"'\s{$][^\"']{7,})[\"']"),
    # 覆盖带驱动前缀的 scheme：mysql+pymysql://、postgresql+psycopg2:// 等（审查报告 F04）
    ("db-url-with-credentials", r"(?i)\b(?:mysql|mariadb|postgres(?:ql)?|mongodb(?:\+srv)?)(?:\+[a-z0-9_]+)?://[^\s/:@]+:(?P<val>[^\s/@]{4,})@"),
    ("jwt-hardcoded-secret", r"(?i)secret_key\s*[:=]\s*[\"'][A-Za-z0-9+/_-]{16,}[\"']"),
]

ALLOW_MARKER = "secret-scan:allow"

# 值为环境变量引用（$VAR / ${VAR}）或常见文档占位符时不算凭据
PLACEHOLDER_VALUES = frozenset(
    {
        "password",
        "passwd",
        "pass",
        "密码",
        "你的密码",
        "my_password",
        "changeme",
        "change_me",
        "change-me",
        "example",
        "placeholder",
        "your_password",
        "your-password",
        "xxx",
    }
)


def _is_placeholder_value(value: str) -> bool:
    if "$" in value:
        return True
    v = value.strip()
    # <合成密码> / <your-password> 这类尖括号占位符
    if v.startswith("<") and v.endswith(">"):
        return True
    return v.lower() in PLACEHOLDER_VALUES


def _run_git(args: list[str], cwd: Path) -> str:
    proc = subprocess.run(
        ["git", "-c", "core.quotepath=off", *args], cwd=str(cwd), capture_output=True, text=True, encoding="utf-8", errors="replace"
    )
    if proc.returncode != 0:
        raise RuntimeError(f"git {' '.join(args)} failed: {proc.stderr.strip()}")
    return proc.stdout


def _changed_lines(diff_text: str) -> list[tuple[str, int, str]]:
    """从 unified diff 提取新增行：[(path, lineno, line)]。"""
    results: list[tuple[str, int, str]] = []
    path = ""
    new_lineno = 0
    for line in diff_text.splitlines():
        if line.startswith("+++ b/"):
            path = line[6:]
        elif line.startswith("+++ "):
            path = line[4:]
        elif line.startswith("@@"):
            # @@ -a,b +c,d @@ → 新文件起始行 c
            after = line.split("+", 1)[1].split(" ", 1)[0]
            new_lineno = int(after.split(",")[0])
        elif line.startswith("+") and not line.startswith("+++"):
            results.append((path, new_lineno, line[1:]))
            new_lineno += 1
        elif line.startswith((" ", "\\")):
            if not line.startswith("\\"):
                new_lineno += 1
    return results


def _tree_files(cwd: Path) -> list[str]:
    out = _run_git(["ls-files"], cwd)
    return [p for p in out.splitlines() if p.strip()]


def scan(targets: list[tuple[str, int, str]], extra_excludes: tuple[str, ...] = ()) -> list[str]:
    excludes = EXCLUDE_PREFIXES + extra_excludes
    findings: list[str] = []
    for path, lineno, text_line in targets:
        if any(path.startswith(p) for p in excludes):
            continue
        if ALLOW_MARKER in text_line:
            continue
        for rule, pattern in PATTERNS:
            import re

            m = re.search(pattern, text_line)
            if not m:
                continue
            # `reset_password = "reset_password"` 这类键名自指（枚举/常量）不是凭据
            if m.groupdict().get("key") and m.group("key").lower() == m.group("val").lower():
                continue
            # 值为环境变量引用或文档占位符时不算凭据（审查报告 F04：区分字面量）
            val = m.groupdict().get("val")
            if val and _is_placeholder_value(val):
                continue
            findings.append(f"{path}:{lineno}: {rule}")
    return findings


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--ref", help="扫描 git diff <ref>...HEAD 的变更行")
    parser.add_argument("--tree", action="store_true", help="全量扫描已跟踪文件")
    parser.add_argument("--cwd", help="git 仓库根目录（默认当前目录，CI 从仓库根运行）")
    args = parser.parse_args()

    cwd = Path(args.cwd).resolve() if args.cwd else Path.cwd()
    try:
        if args.tree:
            targets = []
            for path in _tree_files(cwd):
                try:
                    content = (cwd / path).read_text(encoding="utf-8", errors="replace")
                except OSError:
                    continue
                for lineno, line in enumerate(content.splitlines(), 1):
                    targets.append((path, lineno, line))
        elif args.ref:
            diff = _run_git(["diff", "--no-color", f"{args.ref}...HEAD"], cwd)
            targets = _changed_lines(diff)
        else:
            diff = _run_git(["diff", "--cached", "--no-color"], cwd)
            targets = _changed_lines(diff)
    except RuntimeError as exc:
        print(f"secret-scan: {exc}", file=sys.stderr)
        return 2

    findings = scan(targets, extra_excludes=TREE_ONLY_EXCLUDES if args.tree else ())
    if findings:
        print(f"secret-scan: 发现 {len(findings)} 处疑似凭据（仅路径与规则，内容不回显）：")
        for f in findings:
            print(f"  {f}")
        print("如属误报，请在对应行追加标记 `secret-scan:allow` 并说明原因。")
        return 1
    print(f"secret-scan: 未发现疑似凭据（扫描 {len(targets)} 行）。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
