#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""CoSightBot SOC 端到端回归冒烟脚本（可重复执行）。

用法（在本目录=包根下执行，需先 `python scripts/install.py` 完成首装）：

    python scripts/smoke_test.py                # 全量（LLM/embedding 走 data/.env 配置）
    python scripts/smoke_test.py --offline      # 只跑不依赖 LLM/embedding 的静态与闸门用例
    python scripts/smoke_test.py --keep         # 保留临时 HOME（调试用）

覆盖：
  S 系列  静态：compileall / 预检 exit 3 / install 幂等 / stamp 漂移
  B 系列  SOC 链：kb add-builtin→build→list→extract(schema 闸门)→respond→
          review→fill(模拟写入)→fill validate
  N 系列  负例闸门：extract/fill validate 坏输入必须 exit 1；
          无 embedding 配置时 respond 必须硬失败；fill 拒绝覆盖原件（S-06）；
          fill 拒绝未命中条目误标 FC

判定全部基于退出码 + 结构化 JSON 断言，零目测。任一 FAIL → 总退出码 1。
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path

WORKDIR = Path(__file__).resolve().parents[1]
RUNTIME = WORKDIR / "runtime" / "soc"
VENV_NAME = ".venv-soc"
STAMP = ".install-stamp-soc"
SKILLS = WORKDIR / "skills"
RESULTS: list[tuple[str, str, str]] = []  # (case, status, detail)

# 子进程环境：剔除外部 ANTHROPIC_*/代理，保证走 data/.env 的配置（可复现）
_STRIP_ENV = ("ANTHROPIC_BASE_URL", "ANTHROPIC_AUTH_TOKEN", "ANTHROPIC_API_KEY",
              "ANTHROPIC_MODEL", "all_proxy", "ALL_PROXY", "http_proxy", "https_proxy",
              "CLAUDE_CODE_SESSION_ID")


def _env(home: Path, extra: dict | None = None) -> dict:
    env = {k: v for k, v in os.environ.items() if k not in _STRIP_ENV}
    env["COSIGHTBOT_HOME"] = str(home)
    if Path("/etc/pki/tls/certs/ca-bundle.crt").exists():
        env.setdefault("SSL_CERT_FILE", "/etc/pki/tls/certs/ca-bundle.crt")
    if extra:
        env.update(extra)
    return env


def run(cmd: list[str], home: Path, timeout: int = 900, extra_env: dict | None = None,
        cwd: Path | None = None) -> subprocess.CompletedProcess:
    return subprocess.run(cmd, capture_output=True, text=True, timeout=timeout,
                          env=_env(home, extra_env), cwd=cwd or WORKDIR)


def _state_root() -> Path:
    """数据根解析链（与 runtime/common/port_resolver.py 一致）。"""
    for env_key in ("COSIGHTBOT_HOME", "CLAUDE_PLUGIN_DATA"):
        v = (os.environ.get(env_key) or "").strip()
        if v:
            return Path(v).expanduser()
    return Path.home() / ".claude" / "plugins" / "data" / "cosightbot"


def py(home: Path, script: str) -> list[str]:
    return [str(home / VENV_NAME / "bin" / "python"), str(script)]


def cheap_install(home: Path) -> None:
    """轻量初始化（等价 install.py 的目录+stamp 部分，跳过 pip 安装）。

    用于"环境已装但无 LLM/embedding 配置"的负例空 HOME——完整 pip 安装
    由 S-03 的真实 install.py 调用覆盖，这里只为负例构造合法 stamp。
    """
    home.mkdir(parents=True, exist_ok=True)
    (home / "logs").mkdir(exist_ok=True)
    stamp = hashlib.sha256((RUNTIME / "requirements.txt").read_bytes()).hexdigest()
    (home / STAMP).write_text(stamp, encoding="utf-8")


def record(case: str, ok: bool | None, detail: str = "") -> None:
    status = "PASS" if ok else ("SKIP" if ok is None else "FAIL")
    RESULTS.append((case, status, detail))
    print(f"[{status}] {case}" + (f" — {detail}" if detail else ""), flush=True)


def last_json(stdout: str) -> dict | None:
    """从 stdout 提取最后一个 JSON 对象。"""
    for line in reversed(stdout.strip().splitlines()):
        line = line.strip()
        if line.startswith("{") and line.endswith("}"):
            try:
                return json.loads(line)
            except json.JSONDecodeError:
                continue
    i, j = stdout.find("{"), stdout.rfind("}")
    if 0 <= i < j:
        try:
            return json.loads(stdout[i:j + 1])
        except json.JSONDecodeError:
            return None
    return None


def skill(rel: str) -> str:
    return str(SKILLS / rel)


def gen_extract_json(tender: Path, out: Path) -> Path:
    """按 cosightbot-soc-extract 的 schema 以脚本方式生成需求提取 JSON
    （等价于 LLM 按 SKILL 产出的结构；冒烟只验证下游链路）。"""
    import openpyxl  # type: ignore
    wb = openpyxl.load_workbook(str(tender))
    items = []
    for ws in wb.worksheets:
        rows = list(ws.iter_rows(values_only=True))
        header_seen = False
        for idx, row in enumerate(rows, start=1):
            vals = [str(c).strip() if c is not None else "" for c in row]
            if not header_seen:
                if any(v in ("编号", "No", "序号", "ID") for v in vals):
                    header_seen = True
                continue
            no, req = vals[0], (vals[1] if len(vals) > 1 else "")
            if not no or not req:
                continue
            # 跳过章节标题行（纯数字编号且存在其子级编号）
            if no.isdigit() and any(str(r[0] or "").strip().startswith(no + ".") for r in rows):
                continue
            items.append({"sheet": ws.title, "row": idx, "requirement": req})
    doc = {"source_file": str(tender), "total_demand_items": len(items), "items": items}
    out.write_text(json.dumps(doc, ensure_ascii=False, indent=2), encoding="utf-8")
    return out


def fill_excel(orig: Path, answered_json: Path, out: Path) -> None:
    """按 cosightbot-soc-fill SKILL 规则以脚本方式回填（等价于 LLM 写入）。"""
    import openpyxl  # type: ignore
    from openpyxl.styles import PatternFill  # type: ignore
    shutil.copy2(orig, out)
    payload = json.loads(answered_json.read_text(encoding="utf-8"))
    items = payload.get("items") if isinstance(payload, dict) else payload
    wb = openpyxl.load_workbook(str(out))

    def norm(s) -> str:
        return " ".join(str(s).replace("\r", " ").replace("\n", " ").split()) if s is not None else ""

    red = PatternFill(start_color="FFFF0000", end_color="FFFF0000", fill_type="solid")
    new_cols = ["检索来源", "检索来源文件", "资料入库时间", "匹配到的需求描述",
                "置信度", "是否冲突", "大模型复核", "其他说明"]
    for ws in wb.worksheets:
        header_row, headers = None, {}
        for row in ws.iter_rows(min_row=1, max_row=min(ws.max_row, 10)):
            for cell in row:
                t = norm(cell.value).lower()
                if t:
                    headers.setdefault(t, cell.column)
            if any(k in headers for k in ("编号", "no", "序号", "id")):
                header_row = row[0].row
                break
        if header_row is None:
            continue
        base_col = ws.max_column
        for offset, name in enumerate(new_cols, start=1):
            ws.cell(row=header_row, column=base_col + offset, value=name)
        col_of = {norm(ws.cell(row=header_row, column=c).value).lower(): c
                  for c in range(1, ws.max_column + 1)}
        comp_col = col_of.get("应答") or col_of.get("compliance")
        notes_col = col_of.get("备注")
        ref_col = col_of.get("参考文件")
        for item in items:
            req = norm(item.get("requirement"))
            if not req:
                continue
            for row in ws.iter_rows(min_row=header_row + 1, max_row=ws.max_row):
                if any(norm(c.value) == req for c in row):
                    r = row[0].row
                    comp = str(item.get("compliance", "") or "").strip()
                    if comp_col and comp:
                        ws.cell(row=r, column=comp_col, value=comp)
                    if notes_col and item.get("remarks"):
                        ws.cell(row=r, column=notes_col, value=item["remarks"])
                    if ref_col and item.get("reference_document"):
                        ws.cell(row=r, column=ref_col, value=item["reference_document"])
                    vals = [item.get("source_type", ""), item.get("source_file", ""),
                            str(item.get("source_time") or item.get("created_at") or ""),
                            item.get("matched_reqs") or item.get("matched_req") or "",
                            str(item.get("confidence", "")), "是" if item.get("conflict") else "否",
                            str(item.get("llm_review_result", "") or ""),
                            str(item.get("review_notes", "") or "")]
                    for offset, v in enumerate(vals, start=1):
                        ws.cell(row=r, column=base_col + offset, value=v)
                    if item.get("conflict"):
                        ws.cell(row=r, column=base_col + 6).fill = red
                    break
    wb.save(str(out))


def main() -> int:
    ap = argparse.ArgumentParser(description="CoSightBot SOC 端到端回归冒烟")
    ap.add_argument("--home", default=None, help="测试数据 HOME（默认临时目录）")
    ap.add_argument("--offline", action="store_true", help="跳过依赖 LLM/embedding 的用例")
    ap.add_argument("--keep", action="store_true", help="保留临时 HOME")
    args = ap.parse_args()

    home = Path(args.home) if args.home else Path(tempfile.mkdtemp(prefix="cosightbot-soc-smoke-"))
    home.mkdir(parents=True, exist_ok=True)
    work = home / "work"
    work.mkdir(exist_ok=True)
    print(f"=== smoke home: {home} ===", flush=True)

    # venv 尚未创建时先首装，再用 venv 解释器重入本脚本
    # （SOC 冒烟主进程需要 openpyxl 模拟 LLM 写 Excel，system python 未必有）。
    # 重入时固定 --home，避免重新生成临时目录导致无限重装。
    venv_python = home / VENV_NAME / "bin" / "python"
    if not venv_python.exists():
        p0 = subprocess.run([sys.executable, "scripts/install.py"], env=_env(home), cwd=WORKDIR)
        if p0.returncode != 0:
            print("❌ install.py 执行失败，无法继续冒烟", file=sys.stderr)
            return 2
        os.execv(str(venv_python), [str(venv_python), str(Path(__file__).resolve()),
                                    *sys.argv[1:], "--home", str(home)])

    offline = args.offline
    env_file = _state_root() / ".env"
    has_llm_cfg = env_file.exists() and "OPENAI_API_KEY=" in env_file.read_text(encoding="utf-8")
    if not offline and not has_llm_cfg:
        print("[warn] data/.env 无 LLM 配置，自动降级 --offline")
        offline = True

    # ---- S 系列：静态 / 安装链路 ----
    p = subprocess.run([sys.executable, "-m", "compileall", "-q",
                        str(RUNTIME), str(SKILLS), str(WORKDIR / "scripts")],
                       capture_output=True, text=True)
    record("S-01 compileall 全量语法", p.returncode == 0, p.stderr.strip()[:200])

    # 未首装预检：探针目录不初始化（state_root 不存在 → exit 3）
    p = run([sys.executable, skill("cosightbot-soc-kb-build/scripts/kb_cli.py"), "list"], home / "uninstalled-probe")
    j = last_json(p.stdout)
    record("S-02 未首装预检 exit 3", p.returncode == 3 and bool(j and j.get("hint") == "please_run_install"),
           f"exit={p.returncode} hint={(j or {}).get('hint')}")

    p = run([sys.executable, "scripts/install.py"], home)
    record("S-03 install.py 初始化 smoke HOME", p.returncode == 0 and (home / STAMP).exists())
    p2 = run([sys.executable, "scripts/install.py"], home)
    record("S-04 install.py 幂等重跑", p2.returncode == 0)

    # stamp 漂移：preflight 比对 requirements.txt 的 sha256，追加注释行即应触发 exit 3
    req = RUNTIME / "requirements.txt"
    orig_bytes = req.read_bytes()
    req.write_bytes(orig_bytes + b"\n# smoke-drift-probe\n")
    p = run(py(home, skill("cosightbot-soc-kb-build/scripts/kb_cli.py")) + ["list"], home)
    j = last_json(p.stdout)
    record("S-05 requirements 漂移检测", p.returncode == 3 and bool(j and "requirements" in str(j.get("reason", ""))),
           f"exit={p.returncode}")
    req.write_bytes(orig_bytes)
    run([sys.executable, "scripts/install.py"], home)  # 恢复 stamp

    # 把包内 data/.env 的有效配置复制进 smoke HOME（模拟用户配置）
    smoke_env = home / ".env"
    if env_file.exists():
        lines = [l for l in env_file.read_text(encoding="utf-8").splitlines()
                 if l.strip() and not l.strip().startswith("#")]
        with smoke_env.open("a", encoding="utf-8") as f:
            f.write("\n" + "\n".join(lines) + "\n")

    tender = WORKDIR / "knowledge" / "sample-tender.xlsx"

    # ---- 纯离线负例闸门（不依赖 LLM/embedding）----
    bad1 = work / "bad-schema.json"
    bad1.write_text(json.dumps({"items": [{"sheet": "技术需求", "row": 2, "requirement": "x", "compliance": "MAYBE"}]},
                               ensure_ascii=False), encoding="utf-8")
    p = run(py(home, skill("cosightbot-soc-extract/scripts/validate.py")) + [str(bad1)], home)
    record("N-02 extract validate 非法 compliance 拒绝", p.returncode == 1, f"exit={p.returncode}")

    bad2 = work / "bad-empty.json"
    bad2.write_text('{"items": []}', encoding="utf-8")
    p = run(py(home, skill("cosightbot-soc-extract/scripts/validate.py")) + [str(bad2)], home)
    record("N-03 extract validate 空 items 拒绝", p.returncode == 1, f"exit={p.returncode}")

    # fill validate 负例：产物路径=原件路径必须拒绝（S-06）
    p = run(py(home, skill("cosightbot-soc-fill/scripts/validate.py")) +
            [str(tender), str(tender), str(tender)], home)
    record("N-04 fill validate 拒绝覆盖原件（S-06）", p.returncode == 1, f"exit={p.returncode}")

    # 重复 requirement 回归：按原 Excel sheet/row 区分相同文本，并核对各自行的判定值。
    duplicate_dir = work / "duplicate-requirement"
    duplicate_dir.mkdir(exist_ok=True)
    duplicate_source = duplicate_dir / "duplicate.xlsx"
    duplicate_items = duplicate_dir / "duplicate.json"
    duplicate = "设备须支持双机热备"
    duplicate_new_columns = [
        "检索来源", "检索来源文件", "资料入库时间", "匹配到的需求描述",
        "置信度", "是否冲突", "大模型复核", "其他说明",
    ]
    import openpyxl  # type: ignore
    duplicate_wb = openpyxl.Workbook()
    duplicate_ws = duplicate_wb.active
    duplicate_ws.title = "技术需求"
    duplicate_headers = ["编号", "需求", "应答", *duplicate_new_columns]
    duplicate_ws.append(duplicate_headers)
    duplicate_ws.append(["1.1", duplicate, "FC", *([""] * len(duplicate_new_columns))])
    duplicate_ws.append(["2.1", duplicate, "PC", *([""] * len(duplicate_new_columns))])
    duplicate_wb.save(duplicate_source)
    duplicate_items.write_text(json.dumps({"items": [
        {"sheet": "技术需求", "row": 2, "requirement": duplicate, "compliance": "FC"},
        {"sheet": "技术需求", "row": 3, "requirement": duplicate, "compliance": "PC"},
    ]}, ensure_ascii=False), encoding="utf-8")

    correct_output = duplicate_dir / "correct.xlsx"
    duplicate_wb.save(correct_output)
    p = run(py(home, skill("cosightbot-soc-fill/scripts/validate.py")) +
            [str(duplicate_source), str(duplicate_items), str(correct_output)], home)
    record("N-07 fill validate 接受重复文本的正确逐行回填",
           p.returncode == 0, f"exit={p.returncode}")

    swapped_output = duplicate_dir / "swapped.xlsx"
    swapped_wb = openpyxl.load_workbook(duplicate_source)
    swapped_ws = swapped_wb["技术需求"]
    swapped_ws.cell(row=2, column=3, value="PC")
    swapped_ws.cell(row=3, column=3, value="FC")
    swapped_wb.save(swapped_output)
    p = run(py(home, skill("cosightbot-soc-fill/scripts/validate.py")) +
            [str(duplicate_source), str(duplicate_items), str(swapped_output)], home)
    record("N-08 fill validate 拒绝重复文本回填错行",
           p.returncode == 1 and "与 JSON 判定" in p.stdout, f"exit={p.returncode}")

    ambiguous_items = duplicate_dir / "ambiguous.json"
    ambiguous_items.write_text(json.dumps({"items": [
        {"requirement": duplicate, "compliance": "FC"},
    ]}, ensure_ascii=False), encoding="utf-8")
    p = run(py(home, skill("cosightbot-soc-fill/scripts/validate.py")) +
            [str(duplicate_source), str(ambiguous_items), str(correct_output)], home)
    record("N-09 fill validate 拒绝无来源行的重复文本",
           p.returncode == 1 and "缺少 sheet/row" in p.stdout, f"exit={p.returncode}")

    # 无 embedding 配置时 respond 必须硬失败（非零退出，绝不产出占位应答）
    empty_home = home / "empty-env-home"
    cheap_install(empty_home)
    dummy = work / "dummy.json"
    dummy.write_text('{"items": [{"sheet": "技术需求", "row": 2, "requirement": "x"}]}', encoding="utf-8")
    p = run(py(home, skill("cosightbot-soc-respond/scripts/respond.py")) + [str(dummy)], empty_home)
    record("N-06 无 embedding 配置 respond 硬失败", p.returncode != 0, f"exit={p.returncode}")

    if offline:
        print_summary(home, args.keep)
        return summarize_exit()

    # ---- B 系列：SOC 链 ----
    kb_src = WORKDIR / "knowledge" / "sample-kb"
    p = run(py(home, skill("cosightbot-soc-kb-build/scripts/kb_cli.py")) +
            ["add-builtin", "--kb-id", "sample", "--source-dir", str(kb_src)], home)
    record("B-01 kb add-builtin", p.returncode == 0, f"exit={p.returncode}")
    p = run(py(home, skill("cosightbot-soc-kb-build/scripts/kb_cli.py")) + ["build", "sample"], home, timeout=1800)
    record("B-02 kb build", p.returncode == 0 and '"ok": true' in p.stdout, f"exit={p.returncode}")
    p = run(py(home, skill("cosightbot-soc-kb-build/scripts/kb_cli.py")) + ["list"], home)
    j = last_json(p.stdout)
    built = any(k.get("kb_id") == "sample" and k.get("built") for k in (j or {}).get("kbs", []))
    record("B-03 kb list 注册+就绪", bool(j and j.get("ok") and built))

    p = run(py(home, skill("cosightbot-soc-extract/scripts/inspect_excel.py")) + [str(tender)], home)
    j = last_json(p.stdout)
    record("B-04 extract inspect", p.returncode == 0 and bool(j and j.get("ok")), f"exit={p.returncode}")

    extract_json = gen_extract_json(tender, work / "smoke-需求提取.json")
    p = run(py(home, skill("cosightbot-soc-extract/scripts/validate.py")) + [str(extract_json)], home)
    record("B-05 extract validate schema 闸门", p.returncode == 0, f"exit={p.returncode}")
    n_items = len(json.loads(extract_json.read_text(encoding="utf-8"))["items"])
    record("B-06 提取条目数>0", n_items > 0, f"items={n_items}")

    p = run(py(home, skill("cosightbot-soc-respond/scripts/respond.py")) + [str(extract_json)], home, timeout=1800)
    answered = extract_json.with_name(extract_json.stem + "-已应答.json")
    record("B-07 respond 批量应答", p.returncode == 0 and answered.exists(), f"exit={p.returncode}")
    if answered.exists():
        payload = json.loads(answered.read_text(encoding="utf-8"))
        items = payload.get("items") if isinstance(payload, dict) else payload
        matched = [it for it in items if str(it.get("compliance", "")).strip()]
        unmatched = [it for it in items if not str(it.get("compliance", "")).strip()]
        src_ok = all(it.get("matched_req") and it.get("source_file") for it in matched)
        record("B-08 命中条目 100% 带来源", bool(matched) and src_ok, f"matched={len(matched)}")
        leak = [it for it in matched if "未命中" in str(it.get("review_notes", ""))]
        record("B-09 未命中标记不泄漏进命中条目", not leak, f"leak={len(leak)}")
        record("B-10 未命中条目形态（若有）",
               all(it.get("confidence") == 0.0 and "未命中" in str(it.get("review_notes", "")) for it in unmatched),
               f"unmatched={len(unmatched)}")

        p = run(py(home, skill("cosightbot-soc-review/scripts/review.py")) + [str(answered)], home, timeout=1800)
        reviewed = answered.with_name(answered.stem.replace("-已应答", "") + "-已大模型复核.json")
        if not reviewed.exists():
            cands = list(work.glob("*复核*.json"))
            reviewed = cands[0] if cands else reviewed
        record("B-11 review 大模型复核", p.returncode == 0 and reviewed.exists(), f"exit={p.returncode}")

        final_json = reviewed if reviewed.exists() else answered
        out_xlsx = work / "sample-tender-应答后.xlsx"
        fill_excel(tender, final_json, out_xlsx)
        p = run(py(home, skill("cosightbot-soc-fill/scripts/validate.py")) +
                [str(tender), str(final_json), str(out_xlsx)], home)
        record("B-12 fill validate 闸门", p.returncode == 0, f"exit={p.returncode}")
        record("B-13 原标书未被覆盖（S-06）", out_xlsx.exists() and out_xlsx.resolve() != tender.resolve())

        # N-05：fill validate 未命中约束负例——未命中条目被误标 FC 必须拒绝
        dup = work / "neg-unmatched.json"
        dup.write_text(json.dumps({"items": [
            {"requirement": json.loads(extract_json.read_text(encoding="utf-8"))["items"][0]["requirement"],
             "compliance": "", "confidence": 0.0, "matched_req": "", "conflict": False,
             "review_notes": "未命中知识库（相似度阈值 0.45），需人工应答"}]}, ensure_ascii=False),
            encoding="utf-8")
        neg_out = work / "neg-应答后.xlsx"
        import openpyxl  # type: ignore
        shutil.copy2(tender, neg_out)
        wb = openpyxl.load_workbook(str(neg_out))
        ws = wb.worksheets[0]
        req0 = json.loads(dup.read_text(encoding="utf-8"))["items"][0]["requirement"]
        for row in ws.iter_rows():
            for c in row:
                if c.value and str(c.value).strip() == req0:
                    ws.cell(row=c.row, column=3, value="FC")
        base_col = ws.max_column
        for offset, name in enumerate(["检索来源", "检索来源文件", "资料入库时间", "匹配到的需求描述",
                                       "置信度", "是否冲突", "大模型复核", "其他说明"], start=1):
            ws.cell(row=1, column=base_col + offset, value=name)
        wb.save(str(neg_out))
        p = run(py(home, skill("cosightbot-soc-fill/scripts/validate.py")) +
                [str(tender), str(dup), str(neg_out)], home)
        record("N-05 fill validate 拒绝未命中条目误标 FC", p.returncode == 1, f"exit={p.returncode}")

    print_summary(home, args.keep)
    return summarize_exit()


def print_summary(home: Path, keep: bool) -> None:
    total = len(RESULTS)
    passed = sum(1 for _, s, _ in RESULTS if s == "PASS")
    failed = [r for r in RESULTS if r[1] == "FAIL"]
    skipped = sum(1 for _, s, _ in RESULTS if s == "SKIP")
    print("\n===== 冒烟汇总 =====")
    print(f"total={total} pass={passed} fail={len(failed)} skip={skipped}")
    for case, _, detail in failed:
        print(f"  ❌ {case} — {detail}")
    if failed:
        print(f"home 保留于: {home}")
    elif not keep:
        shutil.rmtree(home, ignore_errors=True)
        print("（临时 HOME 已清理）")


def summarize_exit() -> int:
    return 1 if any(s == "FAIL" for _, s, _ in RESULTS) else 0


if __name__ == "__main__":
    sys.exit(main())
