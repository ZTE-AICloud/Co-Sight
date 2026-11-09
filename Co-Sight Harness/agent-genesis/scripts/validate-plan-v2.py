#!/usr/bin/env python3
"""validate-plan-v2 — matching-decision v2 / build-plan v2 结构校验

用法:
  python3 scripts/validate-plan-v2.py --decision <v2.md> [--build-plan <v2.md>] [--catalog <pattern-catalog.yaml>]

退出码: 0 = PASS, 1 = FAIL。输出 JSON verdict + findings。
设计为 D1 golden 校验与 G017 M4/M6 的共享解析器（G017 bash 调用本脚本取 JSON）。
--build-plan 时附物化对账（matching 表 vs build-plan 增量表逐行）——step-3 边界由
main agent 接线调用（FAIL → step-3 既有 retry 回路），非注册 gate。
"""
import argparse
import json
import re
import sys

import yaml

PAT_ID = re.compile(r"^[A-Z]+[0-9]+$")
DERIVED_FROM = re.compile(r"^acceptance_criteria\[[0-9]+\]$")
REJECTED_REF = re.compile(r"^rejected\[([A-Z]+[0-9]+)\]$")
VALID_ROLES = {"rule_file", "executor_subagent", "schema", "workflow_step",
               "claude_md_section", "settings", "script"}
VALID_TRIGGERS = {"S1", "S2", "S3", "S4"}
VALID_SCOPE = {"K1_reusable", "K2_triggerable", "K3_llm_judgment", "K4_context_budget"}
FILE_TYPES = {"claude_md", "workflow_md", "rule", "schema", "subagent", "skill",
              "script", "fixture", "test", "settings", "gates_yaml", "other"}
INVARIANT_TYPES = {"frontmatter_field_nonempty", "frontmatter_field_absent",
                   "file_reference_exists", "content_contains", "py_compile", "json_schema_valid"}


def parse_md_yaml(path):
    """从 markdown 提取 frontmatter + 所有 ```yaml 块。返回 (frontmatter_dict, [yaml_block_dicts], error)"""
    text = open(path, encoding="utf-8").read()
    m = re.match(r"^---\n(.*?)\n---\n", text, re.DOTALL)
    if not m:
        return None, [], "frontmatter 缺失"
    try:
        fm = yaml.safe_load(m.group(1))
    except yaml.YAMLError as e:
        return None, [], f"frontmatter YAML 解析失败: {e}"
    blocks = []
    for bm in re.finditer(r"```yaml\n(.*?)```", text, re.DOTALL):
        try:
            blocks.append(yaml.safe_load(bm.group(1)))
        except yaml.YAMLError as e:
            return fm, blocks, f"yaml 块解析失败: {e}"
    return fm, blocks, None


def check(cond, msg, findings, sev="FAIL"):
    if not cond:
        findings.append({"severity": sev, "check": msg})


def _section(text, name):
    """提取 "## name[任意后缀]" 到下一个 "## " 之间的文本（标题允许括号注释）"""
    m = re.search(rf"^## {re.escape(name)}[^\n]*\n(.*?)(?=^## |\Z)", text, re.DOTALL | re.MULTILINE)
    return m.group(1) if m else ""


def validate_decision(path, catalog_ids):
    fm, _, err = parse_md_yaml(path)
    findings = []
    if err:
        return {"target": path, "verdict": "FAIL", "findings": [{"severity": "FAIL", "check": err}]}
    sp = fm.get("selected_patterns") or []
    check(isinstance(sp, list) and len(sp) > 0, "selected_patterns 非空数组", findings)
    for p in sp:
        check(bool(PAT_ID.match(str(p))), f"selected_patterns 含非法 ID: {p}", findings)
        if catalog_ids is not None:
            check(str(p) in catalog_ids, f"selected_patterns 含 catalog 外 ID: {p}", findings)
    rj = fm.get("rejected") or []
    for r in rj:
        check(isinstance(r, dict) and PAT_ID.match(str(r.get("pattern_id", ""))) and r.get("reason"),
              f"rejected 条目非法: {r}", findings)
    bt = fm.get("build_type") or {}
    # 归一化: build_type 为 str（存量 fixture 形态）按 {type: bt} 处理，拒绝 AttributeError 崩溃
    if isinstance(bt, str):
        bt = {"type": bt}
    if not isinstance(bt, dict):
        bt = {}
    check(bt.get("type") in ("single", "multi_agent"), "build_type.type ∈ {single, multi_agent}", findings)
    if bt.get("type") == "multi_agent":
        check(bool(bt.get("topology")), "multi_agent 须声明 topology", findings)
    text = open(path, encoding="utf-8").read()
    check("## 结构决策" in text, "正文含「结构决策」节", findings)
    check("## 决策物化" in text, "正文含「决策物化」节", findings)

    # ── M4/M5/M6（G017 扩展检查；finding.check 以 M4_/M5_/M6_ 前缀）──
    mat_sec = _section(text, "决策物化")
    struct_sec = _section(text, "结构决策")
    mat_ids, roles = [], []
    for line in mat_sec.splitlines():
        if not line.strip().startswith("|"):
            continue
        cells = [c.strip() for c in line.strip().strip("|").split("|")]
        if len(cells) >= 3 and PAT_ID.match(cells[0]):
            mat_ids.append(cells[0])
            for tok in re.split(r"[,，、\s]+", cells[2]):
                if tok and "—" not in tok and tok != "(external)":
                    roles.append((cells[0], tok))
    for p in sp:
        check(p in mat_ids, f"M4_uncovered_pattern: {p} 无物化条目", findings)
    for pid, role in roles:
        check(role in VALID_ROLES, f"M5_invalid_role: {pid} → {role}", findings)

    sub_rows = [l for l in struct_sec.splitlines()
                if l.strip().startswith("|") and re.search(r"\|\s*S[0-9]+\s*\|", l)]
    skill_count = len(re.findall(r"scope_trigger:\s*(K[1-4])", struct_sec))
    for l in sub_rows:
        cells = [c.strip() for c in l.strip().strip("|").split("|")]
        if len(cells) >= 2:
            check(cells[1] in VALID_TRIGGERS, f"M5_invalid_trigger: {cells[0]} → {cells[1]}", findings)
    invalid_scope = [m for m in re.findall(r"scope_trigger:\s*([A-Za-z0-9_]+)", struct_sec)
                     if m not in VALID_SCOPE]
    for s in invalid_scope:
        check(False, f"M5_invalid_scope_trigger: {s}", findings)

    btype = bt.get("type")
    if btype == "multi_agent":
        topo = str(bt.get("topology", ""))
        check(bool(topo), "M6_missing_topology", findings)
        check(2 <= len(sub_rows) <= 5, f"M6_subagent_count: multi_agent 须 2≤n≤5, 实际 {len(sub_rows)}", findings)
        base_map = {"W1_stage_parallel": "W1", "W3_mapreduce": "W3", "W4_leader_worker": "W4"}
        for prefix, base in base_map.items():
            if topo.startswith(prefix):
                check(base in [str(x) for x in sp],
                      f"M6_topology_base_not_selected: {topo} 需要 {base} ∈ selected_patterns", findings)
        if topo.startswith("W5_wrap"):
            check("base_topology" in text, "M6_W5_wrap_without_base_topology", findings)
    elif btype == "single":
        check(len(sub_rows) == 0, f"M6_single_with_subagents: single 不应有 subagent 行, 实际 {len(sub_rows)}", findings)
    check(0 <= skill_count <= 3, f"M6_skill_count: 须 0≤n≤3, 实际 {skill_count}", findings)

    return {"target": path, "verdict": "PASS" if not findings else "FAIL", "findings": findings,
            "selected_patterns": sp,
            "rejected_ids": [r["pattern_id"] for r in rj if isinstance(r, dict) and "pattern_id" in r],
            "build_type": bt,
            "materialization_ids": mat_ids}


def check_materialization_reconciliation(decision_mat_ids, build_mat_entries, findings):
    """物化对账（matching 表 vs build-plan 增量表逐行）。

    增量契约: mechanism/verify 单源在 matching-decision「决策物化」表，build-plan
    增量表唯一增量是 target_files 路径绑定。逐行核三件事——
    转写回潮（表内重新携带 mechanism/verify）/ 双向闭合（matching 每行恰有一个绑定行,
    绑定行不得发明 matching 表外模式）/ 无重复绑定行。
    decision_mat_ids 为 None（decision 解析失败或未伴随）时只查转写回潮, 跳过对账。
    """
    entries = [e for e in (build_mat_entries or []) if isinstance(e, dict)]
    for e in entries:
        for key in ("mechanism", "verify"):
            if key in e:
                check(False, f"MAT_transcription_duplicate: {e.get('pattern_id')} "
                             f"增量表携带 {key}（单源在 matching-decision）", findings)
    if decision_mat_ids is None:
        return
    counts = {}
    for e in entries:
        pid = str(e.get("pattern_id"))
        counts[pid] = counts.get(pid, 0) + 1
    for pid in decision_mat_ids:
        check(pid in counts, f"MAT_missing_binding: {pid} matching 表有物化行, "
                             f"build-plan 增量表无绑定", findings)
    for pid, n in sorted(counts.items()):
        check(n == 1, f"MAT_duplicate_binding: {pid} 在 build-plan 增量表出现 {n} 次", findings)
        check(pid in decision_mat_ids, f"MAT_unbound_pattern: {pid} 不在 matching-decision "
                                       f"物化表（绑定不得发明模式）", findings)


def validate_build_plan(path, catalog_ids, rejected_ids, selected_patterns, decision_mat_ids=None):
    fm, blocks, err = parse_md_yaml(path)
    findings = []
    if err:
        return {"target": path, "verdict": "FAIL", "findings": [{"severity": "FAIL", "check": err}]}
    check(fm.get("plan_version") == "2.0", "plan_version == 2.0", findings)
    check(fm.get("mode") in ("greenfield", "incremental"), "mode 合法", findings)
    # M7: executor_protocol 废除校验——字段任何残留值一律 FAIL（强制清理）
    ep = fm.get("executor_protocol")
    if ep is not None:
        check(False, f"M7_executor_protocol_deprecated: {ep}（字段已废除——删除该行）", findings)
    sp = fm.get("selected_patterns") or []
    if selected_patterns:
        check(set(sp) == set(selected_patterns), "frontmatter.selected_patterns 与决策一致", findings)

    mats = [b for b in blocks if isinstance(b, dict) and "materialization" in b]
    # 双形态归一: 平铺 path: 为权威形态（schemas/build-plan.schema.yaml），嵌套 file: 包裹取内层
    files = [b["file"] if isinstance(b.get("file"), dict) else b
             for b in blocks if isinstance(b, dict)]
    files = [f for f in files if "path" in f]
    check(len(mats) == 1 and isinstance(mats[0]["materialization"], list) and len(mats[0]["materialization"]) > 0,
          "恰有一个非空 materialization 块", findings)
    check(len(files) > 0, "至少一个 file 块", findings)

    mat_ids = []
    if mats:
        for e in mats[0]["materialization"]:
            if not isinstance(e, dict):
                check(False, f"物化条目非对象: {e}", findings)
                continue
            check(PAT_ID.match(str(e.get("pattern_id", ""))), f"物化条目 pattern_id 非法: {e}", findings)
            mat_ids.append(str(e.get("pattern_id")))
            check(isinstance(e.get("target_files"), list) and len(e["target_files"]) > 0,
                  f"{e.get('pattern_id')} target_files 非空", findings)
            if catalog_ids is not None:
                check(str(e.get("pattern_id")) in catalog_ids, f"物化含 catalog 外 ID: {e.get('pattern_id')}", findings)
    # 物化对账（matching 表 vs 增量表逐行, 含转写回潮检查）
    check_materialization_reconciliation(decision_mat_ids,
                                         mats[0].get("materialization") if mats else None,
                                         findings)
    # M4: selected ⊆ materialized
    for p in sp:
        check(p in mat_ids, f"M4 物化覆盖率: {p} 无物化条目", findings)

    file_paths = set()
    for f in files:
        fp = f.get("path", "")
        check(bool(fp), "file.path 非空", findings)
        file_paths.add(fp)
        check(f.get("type") in FILE_TYPES, f"{fp} type 非法: {f.get('type')}", findings)
        if f.get("generation") == "copy":
            # copy 条目: 确定性直拷（g025），必填 source（插件内模板路径）；
            # 跳过 brief 长度/数组字段/invariant/anti_pattern 语义检查（G014 不适用于逐字拷贝），
            # G023 cross 存在性照查（原 G009 已删，gate 治理阶段 2）
            check(bool(f.get("source")), f"{fp} copy 条目缺 source", findings)
            continue
        for k in ("deps", "read_first", "materializes", "invariants", "acceptance", "anti_patterns"):
            check(isinstance(f.get(k), list), f"{fp} 缺数组字段 {k}", findings)
        check(bool(f.get("brief")) and len(str(f.get("brief"))) >= 50, f"{fp} brief ≥50 字符", findings)
        for mpat in f.get("materializes") or []:
            check(str(mpat) in sp, f"{fp} materializes 含非选中模式: {mpat}", findings)
        for inv in f.get("invariants") or []:
            check(inv.get("type") in INVARIANT_TYPES, f"{fp} invariant 类型非法: {inv}", findings)
            df = inv.get("derived_from")
            if df:
                check(bool(DERIVED_FROM.match(df)), f"{fp} derived_from 格式非法: {df}", findings)
        for ap in f.get("anti_patterns") or []:
            m = REJECTED_REF.match(str(ap.get("ref", "")))
            check(m is not None, f"{fp} anti_patterns.ref 格式非法: {ap}", findings)
            if m and rejected_ids is not None:
                check(m.group(1) in rejected_ids, f"{fp} anti_patterns 引用了未拒绝的模式: {m.group(1)}", findings)
    # 物化 target_files 闭合: 每个 target_file 在文件清单中
    if mats:
        for e in mats[0]["materialization"]:
            if not isinstance(e, dict):
                continue  # 非对象条目已在上方逐条报「物化条目非对象」, 此处只防崩
            for tf in e.get("target_files") or []:
                check(tf in file_paths, f"物化 target_file 不在文件清单: {tf}（{e.get('pattern_id')}）", findings)

    # M8: 批次闭合（提速方案 OPT-2）。frontmatter 无 batches → 跳过（兼容存量）。
    # 检查: generate 文件恰属一批 / 批内无 deps 边 / copy 条目不入批 / 无未知文件
    batches = fm.get("batches")
    if isinstance(batches, list) and batches:
        gen_paths, copy_paths, path2deps = set(), set(), {}
        for f in files:
            fp = f.get("path", "")
            if not fp:
                continue
            if f.get("generation", "generate") == "copy":
                copy_paths.add(fp)
            else:
                gen_paths.add(fp)
            path2deps[fp] = [d for d in (f.get("deps") or []) if d]
        seen = {}
        for bi, batch in enumerate(batches):
            if not isinstance(batch, list):
                check(False, f"M8_batch_shape: 批次 {bi} 非数组", findings)
                continue
            batch_set = set()
            for fp in batch:
                if fp not in file_paths:
                    check(False, f"M8_unknown_file: 批次 {bi} 含未声明文件 {fp}", findings)
                    continue
                if fp in seen:
                    check(False, f"M8_duplicate_file: {fp} 重复入批（批 {seen[fp]} 与 批 {bi}）", findings)
                    continue
                seen[fp] = bi
                if fp in copy_paths:
                    check(False, f"M8_copy_in_batch: copy 条目 {fp} 不得入批（g025 直拷先行）", findings)
                batch_set.add(fp)
            for fp in batch_set:
                for dep in path2deps.get(fp, []):
                    if dep in batch_set:
                        check(False, f"M8_intra_batch_dep: {fp} 依赖同批文件 {dep}", findings)
        for fp in sorted(gen_paths - set(seen)):
            check(False, f"M8_file_not_batched: generate 文件 {fp} 未入任何批次", findings)

    return {"target": path, "verdict": "PASS" if not findings else "FAIL", "findings": findings}


def load_catalog_ids(path):
    try:
        cat = yaml.safe_load(open(path, encoding="utf-8"))
    except Exception:
        return None
    ids = set()
    def walk(node):
        if isinstance(node, dict):
            for k, v in node.items():
                if PAT_ID.match(str(k)):
                    ids.add(str(k))
                walk(v)
        elif isinstance(node, list):
            for i in node:
                walk(i)
    walk(cat)
    return ids or None


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--decision", required=True)
    ap.add_argument("--build-plan")
    ap.add_argument("--catalog", default="knowledge/shared/pattern-catalog.yaml")
    args = ap.parse_args()
    catalog_ids = load_catalog_ids(args.catalog)

    results = [validate_decision(args.decision, catalog_ids)]
    rejected_ids = results[0].get("rejected_ids")
    selected = results[0].get("selected_patterns")
    if args.build_plan:
        results.append(validate_build_plan(args.build_plan, catalog_ids, rejected_ids, selected,
                                           results[0].get("materialization_ids")))

    overall = "PASS" if all(r["verdict"] == "PASS" for r in results) else "FAIL"
    print(json.dumps({"validator": "validate-plan-v2", "overall": overall, "results": results},
                     ensure_ascii=False, indent=1))
    sys.exit(0 if overall == "PASS" else 1)


if __name__ == "__main__":
    main()
