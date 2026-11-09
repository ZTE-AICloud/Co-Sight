#!/usr/bin/env python3
"""环境检测 — vector-kb-skill 前置条件核对。

fail-closed: 任一必需项不满足即退出码非零并逐条报出, 不静默跳过。
"""
import os
import sys

CHECKS = []


def check(name, ok, detail=""):
    CHECKS.append((name, ok, detail))
    mark = "PASS" if ok else "FAIL"
    print(f"[{mark}] {name}" + (f" — {detail}" if detail else ""))
    return ok


def main():
    py_ok = sys.version_info >= (3, 9)
    check("Python >= 3.9", py_ok, f"current={sys.version.split()[0]}")

    try:
        import pymilvus  # noqa: F401
        check("向量库客户端包可导入", True, "pymilvus")
    except ImportError as e:
        check("向量库客户端包可导入", False, str(e))

    uri = os.environ.get("VECTOR_DB_URI", "http://localhost:19530")
    token = os.environ.get("VECTOR_DB_TOKEN", "")
    try:
        from pymilvus import MilvusClient
        client = MilvusClient(uri=uri, token=token or None)
        client.list_collections()
        check("向量库服务可连通", True, uri)
    except Exception as e:  # noqa: BLE001 — 检测脚本, 报出全部异常类型
        check("向量库服务可连通", False, f"{uri}: {e}")

    need_embedding = "--with-embedding" in sys.argv
    key_present = bool(os.environ.get("OPENAI_API_KEY"))
    check(
        "Embedding 密钥已配置",
        key_present or not need_embedding,
        "OPENAI_API_KEY 未设置" if not key_present else "ok",
    )

    failed = [n for n, ok, _ in CHECKS if not ok]
    if failed:
        print(f"\n环境检测未通过: {len(failed)} 项 — 请回到 SKILL.md 前置条件补齐")
        sys.exit(1)
    print("\n环境检测全部通过")
    sys.exit(0)


if __name__ == "__main__":
    main()
