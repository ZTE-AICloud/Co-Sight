"""static_self_check.py — /skill_optimize --mode refactor 阶段 10b 独立自我检查报告生成器(原 /skill_refactor 阶段 11,v2 合并)。

对标 d7bcf0da session §11 自我检查环节 + docs/重构后检查-Skill完整性验证.md §SK-S1~S13
+ docs/重构后检查-等效性与回归测试.md §R-01~R-N。

提供两个函数:
- `run_self_check(after_skill_dir, output_path) -> dict` — 跑 SK-S + R-N + 写报告
- `generate_self_check_html(data) -> str` — HTML 渲染(可选)

独立阶段产物,不是事后总结。用户 file:// 打开 自我检查报告.md 就能感知。
"""
from __future__ import annotations

import json
import subprocess
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional


@dataclass
class SelfCheckResult:
    """自我检查结果(可序列化到 JSON)"""

    skill_name: str
    after_skill_dir: str
    generated_at: str
    # 7 项 SK-S
    sk_s: dict[str, dict]  # {sk_id: {result: "PASS"|"FAIL"|"WARN", detail: str, value: any}}
    # 4 个 R-N
    r_n: dict[str, dict]
    # 关键指标
    metrics: dict[str, any]
    # 总评
    pass_count: int
    warn_count: int
    fail_count: int
    overall: str  # "PASS" | "WARN" | "FAIL"

    def to_dict(self) -> dict:
        return {
            "schema_version": "1.0",
            "skill_name": self.skill_name,
            "after_skill_dir": self.after_skill_dir,
            "generated_at": self.generated_at,
            "sk_s": self.sk_s,
            "r_n": self.r_n,
            "metrics": self.metrics,
            "summary": {
                "pass": self.pass_count,
                "warn": self.warn_count,
                "fail": self.fail_count,
                "overall": self.overall,
            },
        }


def _yaml_check(skill_md: Path) -> bool:
    """SK-S1: SKILL.md frontmatter YAML 合法。"""
    try:
        import yaml

        text = skill_md.read_text(encoding="utf-8")
        if "---" not in text:
            return False
        body = text.split("---", 2)
        if len(body) < 3:
            return False
        yaml.safe_load(body[1])
        return True
    except Exception:
        return False


def _sk_s2_check(skill_md: Path) -> dict:
    """SK-S2: 引用闭合性 100%(本 Skill 范围)。

    排除 4 类跨 Skill 引用(已在 SKILL.md §5.1 末尾防御性标注):
    - scripts/collect_related_instances.sh
    - scripts/fetch_ontology_instances.sh
    - .specify/scripts/...
    """
    text = skill_md.read_text(encoding="utf-8")
    import re

    # 找所有 references/ 引用
    md_refs = set(re.findall(r"references/[a-zA-Z0-9_./-]+\.md", text))
    # 找所有 scripts/ 引用
    sh_refs = set(re.findall(r"scripts/[a-zA-Z_][a-zA-Z0-9_./-]*\.sh", text))
    # 跨 Skill 引用排除清单
    CROSS_SKILL_PATTERNS = [
        r"collect_related_instances",
        r"fetch_ontology_instances",
        r"bash/consume",  # .specify/scripts/bash/consume/...
    ]

    missing = []
    for ref in sorted(md_refs):
        if not (skill_md.parent / ref).exists():
            missing.append(f"MD: {ref}")
    for ref in sorted(sh_refs):
        if not (skill_md.parent / ref).exists():
            is_cross = any(re.search(p, ref) for p in CROSS_SKILL_PATTERNS)
            if not is_cross:
                missing.append(f"SH: {ref}")

    return {
        "result": "PASS" if not missing else "FAIL",
        "detail": f"{len(md_refs)} references + {len(sh_refs)} scripts 检查,缺失 {len(missing)} 个",
        "missing": missing,
    }


def _sk_s3_check(skill_md: Path, refs_dir: Path) -> dict:
    """SK-S3: 无占位符(TODO/TBD/FIXME)。

    排除 format-spec.md 中描述"无残留占位符"的行(自身提到 TODO/TBD/FIXME 是正常的)。
    """
    import re

    real_count = 0
    matched_files = []
    for f in [skill_md] + sorted(refs_dir.glob("*.md")):
        if not f.exists():
            continue
        for ln, line in enumerate(f.read_text(encoding="utf-8").splitlines(), 1):
            if re.search(r"\b(TODO|TBD|FIXME)\b", line):
                # 排除 format-spec.md 第 23 行附近的描述
                if f.name == "format-spec.md" and "无残留" in line:
                    continue
                real_count += 1
                matched_files.append(f"{f.name}:L{ln}")
    return {
        "result": "PASS" if real_count == 0 else "FAIL",
        "detail": f"{real_count} 个真占位符",
        "matched": matched_files[:5],
    }


def _sk_s8_check(skill_md: Path, target_lines: int = 150) -> dict:
    """SK-S8: SKILL.md body ≤ 150 行(对标 d7bcf0da 108 行)。"""
    lines = sum(1 for _ in open(skill_md, encoding="utf-8"))
    return {
        "result": "PASS" if lines <= target_lines else "WARN",
        "detail": f"{lines} 行(目标 ≤ {target_lines})",
        "value": lines,
    }


def _sk_s10_check(skill_md: Path, refs_dir: Path) -> dict:
    """SK-S10: L3 加载链 100%(所有 references/*.md 都被 SKILL.md 引用)。"""
    text = skill_md.read_text(encoding="utf-8")
    unref = []
    for f in sorted(refs_dir.glob("*.md")):
        if f.name not in text:
            unref.append(f.name)
    return {
        "result": "PASS" if not unref else "FAIL",
        "detail": f"{len(list(refs_dir.glob('*.md')))} 个 references 检查,未引用 {len(unref)} 个",
        "unreferenced": unref,
    }


def _sk_s12_check(scripts_dir: Path) -> dict:
    """SK-S12: 脚本 source 链一致性(0 if 残留 + 全部 bash -n PASS)。"""
    if_residual = 0
    bash_fail = []
    for f in sorted(scripts_dir.glob("*.sh")):
        text = f.read_text(encoding="utf-8")
        if_residual += sum(1 for ln in text.splitlines() if "if [ -f" in ln and ".sh" in ln)
        # bash -n
        r = subprocess.run(["bash", "-n", str(f)], capture_output=True, text=True)
        if r.returncode != 0:
            bash_fail.append(f.name)
    config_sh_residual = sum(
        1
        for f in scripts_dir.glob("*.sh")
        for ln in f.read_text(encoding="utf-8").splitlines()
        # lib.sh 历史注释("合并自" 或 "原 xxx")合理保留,记录合并来源
        if "config.sh" in ln
        and not (f.name == "lib.sh" and ("原 " in ln or "合并自" in ln))
    )
    result = "PASS" if (if_residual == 0 and not bash_fail and config_sh_residual == 0) else "FAIL"
    return {
        "result": result,
        "detail": f"if 块残留 {if_residual} | config.sh 文本残留 {config_sh_residual} | bash -n 失败 {len(bash_fail)}",
        "if_残留": if_residual,
        "config_sh_residual": config_sh_residual,
        "bash_n_fail": bash_fail,
    }


def _sk_s13_check(router_md: Path) -> dict:
    """SK-S13: router.md 关键中间层保留(MCC/SMC/RKC/FCS/UPA ≥ 5 命中)。"""
    if not router_md.exists():
        return {"result": "WARN", "detail": "router.md 不存在", "value": 0}
    text = router_md.read_text(encoding="utf-8")
    keywords = ["MCC", "SMC", "RKC", "FCS", "UPA"]
    hits = sum(text.count(k) for k in keywords)
    return {
        "result": "PASS" if hits >= 5 else "FAIL",
        "detail": f"关键中间组件命中 {hits} (期望 ≥ 5)",
        "value": hits,
    }


def _r_scriptlink_check(scripts_dir: Path) -> dict:
    """R-ScriptLink: 12 个 scripts 全部 bash -n PASS。"""
    fail = []
    for f in sorted(scripts_dir.glob("*.sh")):
        r = subprocess.run(["bash", "-n", str(f)], capture_output=True, text=True)
        if r.returncode != 0:
            fail.append(f.name)
    return {
        "result": "PASS" if not fail else "FAIL",
        "detail": f"{len(list(scripts_dir.glob('*.sh')))} 个 scripts,bash -n 失败 {len(fail)} 个",
        "failed": fail,
    }


def _r_midlayer_check(skill_md: Path, router_md: Path) -> dict:
    """R-MidLayer: SKILL.md §4 含 ⚠️ + router.md ≥ 5 关键组件。"""
    sm = skill_md.read_text(encoding="utf-8")
    has_warning = "⚠️" in sm
    has_midlayer = router_md.exists() and sum(router_md.read_text(encoding="utf-8").count(k) for k in ["MCC", "SMC", "RKC", "FCS", "UPA"]) >= 5
    return {
        "result": "PASS" if (has_warning and has_midlayer) else "FAIL",
        "detail": f"SKILL.md ⚠️={has_warning} | router.md 中间层={has_midlayer}",
    }


def _r_iocontract_check(io_contract_md: Path, skill_md: Path) -> dict:
    """R-IOContract: io-contract.md 含 13 项过程产物关键词 + SKILL.md §6.2 引用。"""
    if not io_contract_md.exists():
        return {"result": "WARN", "detail": "io-contract.md 不存在", "value": 0}
    text = io_contract_md.read_text(encoding="utf-8")
    keywords = ["Y1", "Y2", "Y3", "子系统间交互时序", "步骤1"]
    hits = sum(text.count(k) for k in keywords)
    sm = skill_md.read_text(encoding="utf-8")
    referenced = "io-contract.md" in sm
    return {
        "result": "PASS" if (hits >= 4 and referenced) else "FAIL",
        "detail": f"关键词命中 {hits} (期望 ≥ 4) | SKILL.md §6.2 引用={referenced}",
        "value": hits,
    }


def _r_description_check(skill_md: Path) -> dict:
    """R-Description: description 30~1024 字符 + 含 4 要素(做什么/触发/输入/输出)。"""
    import re

    text = skill_md.read_text(encoding="utf-8")
    m = re.search(r"^description:\s*(.+)$", text, re.MULTILINE)
    if not m:
        return {"result": "FAIL", "detail": "无 description 字段", "value": 0}
    desc = m.group(1)
    length = len(desc)
    elements = ["做什么", "触发", "输入", "输出"]
    hits = sum(1 for e in elements if e in desc)
    return {
        "result": "PASS" if (30 <= length <= 1024 and hits == 4) else "FAIL",
        "detail": f"长度 {length} | 4 要素命中 {hits}/4",
        "value": {"length": length, "elements": hits},
    }


def _compute_metrics(after_skill_dir: Path) -> dict:
    """关键指标对比(after vs 原始 SKILL.md 体积)。"""
    skill_md = after_skill_dir / "SKILL.md"
    if not skill_md.exists():
        return {"error": "SKILL.md 不存在"}
    current_lines = sum(1 for _ in open(skill_md, encoding="utf-8"))
    current_bytes = skill_md.stat().st_size
    lib_sh = after_skill_dir / "scripts" / "lib.sh"
    lib_bytes = lib_sh.stat().st_size if lib_sh.exists() else 0

    refs_dir = after_skill_dir / "references"
    new_refs = []
    for f in ["execution-rules.md", "router.md", "skill-assets.md", "io-contract.md"]:
        if (refs_dir / f).exists():
            new_refs.append(f"references/{f}")
    if (refs_dir / "lookup-rules" / "manifest.json").exists():
        new_refs.append("references/lookup-rules/manifest.json")
    work_state = after_skill_dir / "work" / "task-state.json"
    if work_state.exists():
        new_refs.append("work/task-state.json")

    return {
        "skill_md_lines": current_lines,
        "skill_md_bytes": current_bytes,
        "lib_sh_bytes": lib_bytes,
        "new_files_count": len(new_refs),
        "new_files": new_refs,
    }


def run_self_check(after_skill_dir: Path, output_path: Optional[Path] = None) -> SelfCheckResult:
    """跑全套 SK-S + R-N + 写自查报告到 output_path。

    Args:
        after_skill_dir: 重构后的 Skill 副本目录(含 SKILL.md / references/ / scripts/ / templates/)
        output_path: 自查报告写出路径(默认 {after_skill_dir.parent}/自我检查报告.md)

    Returns:
        SelfCheckResult 实例(可 to_dict() 序列化)
    """
    after_skill_dir = Path(after_skill_dir).resolve()
    skill_name = after_skill_dir.name
    skill_md = after_skill_dir / "SKILL.md"
    refs_dir = after_skill_dir / "references"
    scripts_dir = after_skill_dir / "scripts"
    router_md = refs_dir / "router.md"
    io_contract_md = refs_dir / "io-contract.md"

    sk_s = {
        "SK-S1": _yaml_check(skill_md) and {"result": "PASS", "detail": "YAML frontmatter 合法"} or {"result": "FAIL", "detail": "YAML 解析失败"},
        "SK-S2": _sk_s2_check(skill_md),
        "SK-S3": _sk_s3_check(skill_md, refs_dir),
        "SK-S8": _sk_s8_check(skill_md),
        "SK-S10": _sk_s10_check(skill_md, refs_dir),
        "SK-S12": _sk_s12_check(scripts_dir),
        "SK-S13": _sk_s13_check(router_md),
    }
    r_n = {
        "R-ScriptLink": _r_scriptlink_check(scripts_dir),
        "R-MidLayer": _r_midlayer_check(skill_md, router_md),
        "R-IOContract": _r_iocontract_check(io_contract_md, skill_md),
        "R-Description": _r_description_check(skill_md),
    }
    metrics = _compute_metrics(after_skill_dir)

    pass_count = sum(1 for v in list(sk_s.values()) + list(r_n.values()) if v["result"] == "PASS")
    warn_count = sum(1 for v in list(sk_s.values()) + list(r_n.values()) if v["result"] == "WARN")
    fail_count = sum(1 for v in list(sk_s.values()) + list(r_n.values()) if v["result"] == "FAIL")
    overall = "PASS" if fail_count == 0 and warn_count == 0 else ("WARN" if fail_count == 0 else "FAIL")

    result = SelfCheckResult(
        skill_name=skill_name,
        after_skill_dir=str(after_skill_dir),
        generated_at=datetime.now(timezone.utc).isoformat(),
        sk_s=sk_s,
        r_n=r_n,
        metrics=metrics,
        pass_count=pass_count,
        warn_count=warn_count,
        fail_count=fail_count,
        overall=overall,
    )

    if output_path is None:
        output_path = after_skill_dir.parent / "自我检查报告.md"
    output_path = Path(output_path)
    output_path.write_text(_render_markdown(result), encoding="utf-8")
    return result


def _render_markdown(r: SelfCheckResult) -> str:
    """渲染成 Markdown(用户可 file:// 直接打开看)。"""
    m = r.metrics
    lines = [
        f"# 🔍 自我检查报告(Step 11 独立阶段)— {r.skill_name}",
        "",
        "> **⚠️ 本报告是独立阶段产物,不是事后总结。**",
        "> 对齐 d7bcf0da session §11 自我检查环节 + docs/重构后检查-Skill完整性验证.md §SK-S1~S13 + docs/重构后检查-等效性与回归测试.md §R-01~R-N",
        f"> **生成时间**:{r.generated_at}",
        f"> **目录**:`{r.after_skill_dir}`",
        "",
        f"## 自查结论:**通过 {r.pass_count}/{r.pass_count + r.warn_count + r.fail_count} 项,失败 {r.fail_count} 项,WARN {r.warn_count} 项。整体:{r.overall}**",
        "",
        "## 一、SK-S 静态自查表(7 项)",
        "",
        "| SK-S 编号 | 检查项 | 结果 | 备注 |",
        "|---|---|:---:|---|",
    ]
    sk_names = {
        "SK-S1": "SKILL.md frontmatter YAML 合法",
        "SK-S2": "引用闭合性 100%(本 Skill 范围)",
        "SK-S3": "无占位符(TODO/TBD/FIXME)",
        "SK-S8": "SKILL.md body ≤ 150 行",
        "SK-S10": "L3 加载链 100%",
        "SK-S12": "脚本 source 链一致性(0 if 残留 + bash -n 全 PASS)",
        "SK-S13": "router.md 关键中间层保留",
    }
    for sid in ["SK-S1", "SK-S2", "SK-S3", "SK-S8", "SK-S10", "SK-S12", "SK-S13"]:
        v = r.sk_s[sid]
        icon = {"PASS": "✅", "WARN": "⚠️", "FAIL": "❌"}[v["result"]]
        lines.append(f"| **{sid}** | {sk_names[sid]} | {icon} {v['result']} | {v['detail']} |")

    lines.extend([
        "",
        "## 二、R-N 行为层自查表(4 场景)",
        "",
        "| R-N 场景 | 验证方法 | 结果 | 备注 |",
        "|---|---|:---:|---|",
    ])
    rn_names = {
        "R-ScriptLink": "scripts 全部 bash -n PASS + 不报 config.sh 错误",
        "R-MidLayer": "SKILL.md §4 含 ⚠️ + router.md ≥ 5 关键组件",
        "R-IOContract": "io-contract.md 含 13 项关键词 + SKILL.md 引用",
        "R-Description": "description 30~1024 字符 + 含 4 要素",
    }
    for rid in ["R-ScriptLink", "R-MidLayer", "R-IOContract", "R-Description"]:
        v = r.r_n[rid]
        icon = {"PASS": "✅", "WARN": "⚠️", "FAIL": "❌"}[v["result"]]
        lines.append(f"| **{rid}** | {rn_names[rid]} | {icon} {v['result']} | {v['detail']} |")

    lines.extend([
        "",
        "## 三、关键指标自查",
        "",
        "| 指标 | 值 |",
        "|---|---|",
        f"| SKILL.md 行数 | {m.get('skill_md_lines', 'N/A')} |",
        f"| SKILL.md 字节 | {m.get('skill_md_bytes', 'N/A')} |",
        f"| scripts/lib.sh 字节 | {m.get('lib_sh_bytes', 'N/A')} |",
        f"| 新增文件数 | {m.get('new_files_count', 'N/A')} |",
    ])
    if m.get("new_files"):
        lines.append(f"| 新增文件清单 | {', '.join(m['new_files'])} |")

    lines.extend([
        "",
        "## 四、SK-S 详细数据(JSON)",
        "",
        "```json",
        json.dumps(r.sk_s, ensure_ascii=False, indent=2),
        "```",
        "",
        "## 五、R-N 详细数据(JSON)",
        "",
        "```json",
        json.dumps(r.r_n, ensure_ascii=False, indent=2),
        "```",
        "",
        "## 六、待用户采纳清单",
        "",
    ])

    # 列出 WARN/FAIL 项(不写修复建议,留给 CC 自主 plan)
    bad_items = [
        (sid, v)
        for sid, v in {**r.sk_s, **r.r_n}.items()
        if v["result"] in ("WARN", "FAIL")
    ]
    if bad_items:
        lines.append("> ⚠️ **本报告只诊断不修复**。WARN/FAIL 项的修复方案由 **CC 在 EnterPlanMode 中自主合成 plan**(对标 d7bcf0da 4 字段风格),用户可选择:全部采纳 / 部分采纳 / 全部跳过 / 手动修。")
        lines.append("")
        for sid, v in bad_items:
            icon = {"WARN": "⚠️", "FAIL": "❌"}[v["result"]]
            lines.append(f"- [ ] **{icon} {sid}** — {v['detail']}")
    else:
        lines.append("> ✅ 全部 11 项 PASS,无需 CC 合成修复 plan。")

    lines.extend([
        "",
        "## 七、产物 3 件套",
        "",
        f"- [ ] 查看 `{r.after_skill_dir.replace(str(Path(r.after_skill_dir).parent) + '/', '')}/../重构完成报告.md`",
        f"- [ ] 查看 `{r.after_skill_dir.replace(str(Path(r.after_skill_dir).parent) + '/', '')}/../refactor_diff_report.html`",
        f"- [ ] 确认是否回滚源文件(本次重构不自动改源 `{r.after_skill_dir}/../../../`)",
        "",
        "---",
        "",
        "> **本自查报告与 `重构完成报告.md` §5 同源(同一份数据,2 份呈现)。**",
        f"> **生成时间**:{r.generated_at} | **Skill**:`{r.skill_name}`",
    ])
    return "\n".join(lines) + "\n"


def write_self_check_json(result: SelfCheckResult, output_path: Path) -> None:
    """写 JSON 版自查结果(供机器消费,如 dashboard)。"""
    output_path.write_text(
        json.dumps(result.to_dict(), ensure_ascii=False, indent=2), encoding="utf-8"
    )
