#!/usr/bin/env python3
"""parse_diff.py — 统一 git diff → 结构化 JSON。

用法: python3 parse_diff.py <raw.diff>
输出: stdout JSON（结构见 .claude/skills/parse-git-diff/SKILL.md）
退出: 0 成功 / 2 输入非法（非 diff 格式）
"""
import json
import re
import sys

DIFF_HEADER = re.compile(r"^diff --git a/(.+) b/(.+)$")
HUNK_HEADER = re.compile(r"^@@ -(\d+)(?:,\d+)? \+(\d+)(?:,\d+)? @@")

BINARY_MARKERS = ("Binary files", "GIT binary patch")


def parse(text: str) -> dict:
    files = []
    current = None
    hunk = None

    for line in text.splitlines():
        m = DIFF_HEADER.match(line)
        if m:
            current = {
                "path": m.group(2),
                "lang": m.group(2).rsplit(".", 1)[-1] if "." in m.group(2) else "unknown",
                "hunks": [],
                "added_lines": [],
                "is_new": False,
                "is_binary": False,
            }
            files.append(current)
            hunk = None
            continue
        if current is None:
            continue
        if any(marker in line for marker in BINARY_MARKERS):
            current["is_binary"] = True
            continue
        if line.startswith("new file mode"):
            current["is_new"] = True
            continue
        hm = HUNK_HEADER.match(line)
        if hm:
            hunk = {"start": int(hm.group(2)), "added": [], "removed": []}
            current["hunks"].append(hunk)
            continue
        if hunk is None:
            continue
        if line.startswith("+") and not line.startswith("+++"):
            hunk["added"].append(line)
            current["added_lines"].append(line[1:])
        elif line.startswith("-") and not line.startswith("---"):
            hunk["removed"].append(line)

    additions = sum(len(f["added_lines"]) for f in files)
    deletions = sum(
        len(h["removed"]) for f in files for h in f["hunks"]
    )
    return {
        "files": [f for f in files if not f["is_binary"]],
        "stats": {
            "files_changed": len(files),
            "additions": additions,
            "deletions": deletions,
        },
    }


def main() -> int:
    if len(sys.argv) != 2:
        print("用法: parse_diff.py <raw.diff>", file=sys.stderr)
        return 2
    try:
        with open(sys.argv[1], encoding="utf-8", errors="replace") as fh:
            text = fh.read()
    except OSError as exc:
        print(json.dumps({"error": f"read_failed: {exc}"}), file=sys.stderr)
        return 2
    if "diff --git" not in text:
        print(json.dumps({"error": "UNSUPPORTED_FORMAT: 非统一 diff 格式"}), file=sys.stderr)
        return 2
    print(json.dumps(parse(text), ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
