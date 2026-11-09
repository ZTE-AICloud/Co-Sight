#!/usr/bin/env python3
"""run_tests.py — 逐变异体运行测试，脚本裁决击杀（IT1）。

用法:
  python3 run_tests.py --tests-dir tests --sandbox work/mutation-sandbox
      sandbox 下每个 M*/ 目录 = 一个变异体（含完整目录树）。
      以 PYTHONPATH=<M 目录> 运行 pytest，测试 import 的目标模块
      即变异体副本。

裁决:
  killed   — pytest 退出码非 0（含断言失败/收集错误/解释器崩溃 = 检出）
  survived — 退出码 0（测试全绿 = 变异体逃逸）
输出 JSON: {results: {M1-1: killed, ...}, summary: {...}}
"""
import argparse
import json
import os
import subprocess
import sys


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--tests-dir", required=True)
    ap.add_argument("--sandbox", required=True)
    ap.add_argument("--import-root", default="",
                    help="每个变异体目录内的包根（如 tests/fixtures）；PYTHONPATH=<M>/<import-root>")
    ap.add_argument("--timeout", type=int, default=120)
    args = ap.parse_args()

    mutants = sorted(
        d for d in os.listdir(args.sandbox)
        if os.path.isdir(os.path.join(args.sandbox, d)) and d.startswith("M")
    )
    if not mutants:
        print(json.dumps({"error": f"sandbox 无变异体目录: {args.sandbox}"}), file=sys.stderr)
        return 2

    results, killed = {}, 0
    for mid in mutants:
        mdir = os.path.join(args.sandbox, mid)
        import_root = os.path.join(mdir, args.import_root) if args.import_root else mdir
        env = dict(os.environ, PYTHONPATH=import_root)
        try:
            proc = subprocess.run(
                [sys.executable, "-m", "pytest", args.tests_dir, "-q", "-p", "no:cacheprovider"],
                env=env, capture_output=True, text=True, timeout=args.timeout,
            )
            verdict = "killed" if proc.returncode != 0 else "survived"
        except subprocess.TimeoutExpired:
            verdict = "killed"  # 超时视为检出（变异导致死循环等）
        results[mid] = verdict
        killed += verdict == "killed"

    summary = {
        "total": len(mutants), "killed": killed,
        "survived": len(mutants) - killed,
        "kill_rate": round(killed / len(mutants), 4) if mutants else 0.0,
    }
    print(json.dumps({"results": results, "summary": summary}, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
