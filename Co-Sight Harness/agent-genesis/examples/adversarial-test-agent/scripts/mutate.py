#!/usr/bin/env python3
"""mutate.py — 变异算子引擎（AST 发现 + 行级精确变换 + 沙箱强制）。

用法:
  python3 mutate.py --list --target src/pricing.py
      扫描候选变异点（6 类算子），输出 JSON 清单，不落盘。
  python3 mutate.py --apply --target src/pricing.py \
      --mutant '{"id":"M1-1","op":"OP-B1","line":18,"from":">=","to":">"}' \
      --sandbox work/mutation-sandbox
      将变异体写入 <sandbox>/<id>/src/pricing.py（路径强制，拒绝源码树）。

- 变异体落盘路径：`<sandbox>/<id>/<target 原始相对路径>`（保持包结构）
- run_tests.py 用 `--import-root` 指定包根，保证 `import src.xxx` 解析到变异体副本
"""
import argparse
import ast
import json
import os
import re
import sys

SANDBOX_NAME = re.compile(r"^(mutation-)?sandbox(-[\w.-]+)?$")

OPS = {
    "OP-B1": ("boundary-flip", ">="), "OP-A1": ("arithmetic-swap", "+"),
    "OP-C1": ("negate-condition", "if"), "OP-K1": ("constant-tweak", "num"),
}

COMPARE_FLIP = {">=": ">", ">": ">=", "<=": "<", "<": "<=", "==": "!=", "!=": "=="}
ARITH_FLIP = {ast.Add: ast.Sub, ast.Sub: ast.Add, ast.Mult: ast.Div, ast.Div: ast.Mult}


def list_candidates(path: str) -> list:
    src = open(path, encoding="utf-8").read()
    tree = ast.parse(src)
    lines = src.splitlines()
    out = []

    class V(ast.NodeVisitor):
        def visit_Compare(self, node: ast.Compare):
            if len(node.ops) == 1 and len(node.comparators) == 1:
                sym = {
                    ast.GtE: ">=", ast.Gt: ">", ast.LtE: "<=",
                    ast.Lt: "<", ast.Eq: "==", ast.NotEq: "!=",
                }.get(type(node.ops[0]))
                if sym and sym in COMPARE_FLIP:
                    out.append({"op": "OP-B1", "line": node.lineno,
                                "snippet": lines[node.lineno - 1].strip(),
                                "from": sym, "to": COMPARE_FLIP[sym]})
            self.generic_visit(node)

        def visit_BinOp(self, node: ast.BinOp):
            sym = {ast.Add: "+", ast.Sub: "-", ast.Mult: "*", ast.Div: "/"}.get(type(node.op))
            if sym and type(node.op) in ARITH_FLIP:
                out.append({"op": "OP-A1", "line": node.lineno,
                            "snippet": lines[node.lineno - 1].strip(),
                            "from": sym, "to": {ast.Add: "-", ast.Sub: "+", ast.Mult: "/", ast.Div: "*"}[type(node.op)]})
            self.generic_visit(node)

        def visit_If(self, node: ast.If):
            seg = ast.get_source_segment(src, node.test) or ""
            if seg and len(seg) < 60:
                out.append({"op": "OP-C1", "line": node.lineno,
                            "snippet": lines[node.lineno - 1].strip(),
                            "from": f"if {seg}", "to": f"if not ({seg})"})
            self.generic_visit(node)

        def visit_Constant(self, node: ast.Constant):
            if isinstance(node.value, (int, float)) and not isinstance(node.value, bool):
                out.append({"op": "OP-K1", "line": node.lineno,
                            "snippet": lines[node.lineno - 1].strip(),
                            "from": str(node.value), "to": str(node.value + 1)})
            self.generic_visit(node)

    V().visit(tree)
    return out


def apply_mutation(target: str, mutant: dict, sandbox: str) -> str:
    if not SANDBOX_NAME.match(os.path.basename(os.path.normpath(sandbox))):
        raise SystemExit(json.dumps({"error": "REFUSED: 输出目录名必须匹配 (mutation-)?sandbox(-.*)? （CD2 路径强制）"}))
    src = open(target, encoding="utf-8").read()
    lines = src.splitlines()
    lineno = mutant["line"]
    if not (1 <= lineno <= len(lines)):
        raise SystemExit(json.dumps({"error": f"line {lineno} 超出范围"}))
    idx = lineno - 1
    occurrences = lines[idx].count(mutant["from"])
    if occurrences != 1:
        raise SystemExit(json.dumps({"error": f"第 {lineno} 行中 '{mutant['from']}' 出现 {occurrences} 次，无法唯一替换"}))
    lines[idx] = lines[idx].replace(mutant["from"], mutant["to"], 1)
    rel = os.path.basename(target)
    out_dir = os.path.join(sandbox, mutant["id"], os.path.dirname(target) or ".")
    os.makedirs(out_dir, exist_ok=True)
    out_path = os.path.join(out_dir, rel)
    with open(out_path, "w", encoding="utf-8") as fh:
        fh.write("\n".join(lines) + "\n")
    return out_path


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--list", action="store_true")
    ap.add_argument("--apply", action="store_true")
    ap.add_argument("--target", required=True)
    ap.add_argument("--mutant")
    ap.add_argument("--sandbox")
    args = ap.parse_args()

    if args.list:
        print(json.dumps({"candidates": list_candidates(args.target)}, ensure_ascii=False, indent=2))
        return 0
    if args.apply:
        if not args.mutant or not args.sandbox:
            print(json.dumps({"error": "--apply 需要 --mutant 与 --sandbox"}), file=sys.stderr)
            return 2
        path = apply_mutation(args.target, json.loads(args.mutant), args.sandbox)
        print(json.dumps({"mutant": json.loads(args.mutant)["id"], "written": path}))
        return 0
    ap.print_help()
    return 2


if __name__ == "__main__":
    sys.exit(main())
