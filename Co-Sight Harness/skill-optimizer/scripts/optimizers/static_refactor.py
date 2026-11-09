"""Skill 结构层重构 - LLM 诊断 + 知识注入(极简版)。

CC /skill_optimize --mode refactor 流程(原 /skill_refactor,v2 合并):
- orchestrator 跑本模块产出 refactor_diagnosis.md(真 LLM 调)
- CC 主对话自己进 plan mode 读 diagnosis + relation tree → 合成 plan → 用 Edit 应用

本模块只做"数据收集",不做 apply / verify / auto-fix(由 CC 承担)。
"""
from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)


# 6 份重构/检查文档路径(inject 到 system message 作为知识基础)
# 顺序原则:① 分层与目录结构 → ② 重构模式库 → ③ 性能与 token 优化 →
#           ④ 极致代码化(LLM vs 脚本分工,2026-07 新增) → ⑤ 完整性验证 → ⑥ 等效性回归
KNOWLEDGE_DOCS = (
    "docs/重构原则-skill分层与目录结构.md",
    "docs/重构原则-skill重构模式库.md",
    "docs/重构原则-skill性能与token优化.md",
    "docs/重构原则-skill极致代码化.md",
    "docs/重构后检查-Skill完整性验证.md",
    "docs/重构后检查-等效性与回归测试.md",
)


def load_knowledge(project_root: Path) -> str:
    """加载 5 份重构文档,失败文件跳过。"""
    chunks: list[str] = []
    for rel in KNOWLEDGE_DOCS:
        path = project_root / rel
        if not path.exists():
            continue
        try:
            chunks.append(f"\n\n===== {rel} =====\n\n{path.read_text(encoding='utf-8')}")
        except OSError as e:
            logger.warning("读取 %s 失败: %s", path, e)
    return "".join(chunks)


def build_diagnose_prompt(
    skill_root: Path,
    relation_tree: dict,
    skill_md_text: str,
    knowledge: str,
    expert_guidance: str = "",
) -> str:
    """构造 skill-refactor-agent diagnose 模式的 user prompt。"""
    rt_summary = {
        "files": relation_tree.get("files", []),
        "orphans": relation_tree.get("orphans", []),
        "long_unoptimized": relation_tree.get("long_unoptimized", []),
        "summary_table": relation_tree.get("summary_table", []),
        "clusters": relation_tree.get("clusters", []),
        "stats": relation_tree.get("stats", {}),
    }
    skill_md_excerpt = skill_md_text[:8000]
    if len(skill_md_text) > 8000:
        skill_md_excerpt += f"\n\n... (剩余 {len(skill_md_text) - 8000} 字符已截断)"

    expert_block = (
        f"## 用户专家指引(最高优先级)\n\n{expert_guidance}\n\n"
        if expert_guidance else ""
    )

    return (
        "# 任务:结构层重构诊断\n\n"
        f"## 目标 Skill\n\n- skill_root: `{skill_root}`\n"
        f"- SKILL.md 长度: {len(skill_md_text)} 字符\n\n"
        "## SKILL.md 内容(前 8000 字符)\n\n"
        f"```\n{skill_md_excerpt}\n```\n\n"
        "## 关系树快照\n\n"
        f"```json\n{json.dumps(rt_summary, ensure_ascii=False, indent=2)[:8000]}\n```\n\n"
        + expert_block
        + "## 你的任务\n\n"
        "基于上述知识文档(已在 system message)、关系树与 SKILL.md,产出**两类内容**:\n\n"
        "1. **findings[]**:微诊断列表(每条 FD-XXX 含 id/file/pattern/severity/principle_ref/evidence/before/recommendation)\n"
        "2. **cluster_observations[]**:宏观观察(1-2 句话每条)\n\n"
        "## JSON schema(严格)\n\n"
        "```json\n"
        "{\n"
        '  "findings": [\n'
        "    {\n"
        '      "id": "FD-001",\n'
        '      "file": "SKILL.md",\n'
        '      "pattern": "P-xxx",\n'
        '      "severity": "CRITICAL|HIGH|MEDIUM|LOW",\n'
        '      "principle_ref": "<文档> §<章节>",\n'
        '      "evidence": "<SKILL.md line range>",\n'
        '      "before": "<待修改的精确字符串片段,grep -F 唯一命中>",\n'
        '      "recommendation": "<高层修复方向>"\n'
        "    }\n"
        "  ],\n"
        '  "cluster_observations": [{"cluster": "...", "observation": "..."}]\n'
        "}\n"
        "```\n\n"
        "## d7bcf0da 实战案例 13 类必查 FD(对标 session:d7bcf0da,共 33 文件 +752/-970)\n\n"
        "**重要**:findings 应**至少覆盖以下 13 类**;不适用时输出 severity=LOW + recommendation='不适用,因 <原因>'。\n\n"
        "| FD 编号 | 必查主题 | 严重度 |\n"
        "|---|---|:---:|\n"
        "| FD-001 | frontmatter description 4 要素公式化 | HIGH |\n"
        "| FD-002 | §3 硬约束外置到 references/execution-rules.md | HIGH |\n"
        "| FD-003 | §7 任务完成标准外置到 references/execution-rules.md | HIGH |\n"
        "| FD-004 | orphan 文件合并到 references/lookup-rules/manifest.json | HIGH |\n"
        "| FD-005 | scripts/ 工具层合并(对标 lib.sh 353 行) | HIGH |\n"
        "| FD-006 | scripts/load_rule.sh + table_io.sh + scripts/README.md | MEDIUM |\n"
        "| FD-007 | references/router.md(5 Procedure 流程图外移) | MEDIUM |\n"
        "| FD-008 | references/io-contract.md(13 项过程产物路径外移) | MEDIUM |\n"
        "| FD-009 | references/skill-assets.md(资产目录树外移) | MEDIUM |\n"
        "| FD-010 | templates/README.md(模板目录索引) | LOW |\n"
        "| FD-011 | SKILL.md 引用闭合性验证 | HIGH |\n"
        "| FD-012 | scripts/ source 链一致性预检 | MEDIUM |\n"
        "| FD-013 | 关键路径/中间层保留验证 | MEDIUM |\n"
        "| FD-014 | **DF-M4 脚本独立:SKILL.md 内联 >10 行 Python/Shell 代码块** | **HIGH** |\n"
        "| FD-015 | **Description 4 要素公式:缺\"输入/输出/触发/做什么\"中任一项** | **HIGH** |\n"
        "| FD-016 | **scripts/ 脚本依赖 LLM 上下文(从环境变量读 session_id 等)** | **MEDIUM** |\n\n"
        "## 硬约束\n\n"
        "- findings 上限 20 条,**至少包含 FD-001 ~ FD-016 中的适用项**(FD-014/015/016 来自极致代码化原则,DF-M4 + Description 4 要素 + 脚本独立性,详见 `docs/重构原则-skill极致代码化.md` §7)\n"
        "- before 必须 grep -F 唯一命中 SKILL.md 或对应文件\n"
        "- 严格 JSON 输出,**无 markdown 包裹**\n"
    )


def write_diagnosis(llm_result: dict, output_path: Path) -> None:
    """写 LLM 诊断结果到 refactor_diagnosis.md(JSON 格式)。"""
    output_path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "schema_version": 1,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "finding_count": len(llm_result.get("findings", [])),
        "findings": llm_result.get("findings", []),
        "cluster_observations": llm_result.get("cluster_observations", []),
    }
    output_path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def run_diagnose(
    skill_root: Path,
    relation_tree: dict,
    skill_md_text: str,
    project_root: Path,
    expert_guidance: str = "",
    debug_label: str = "refactor_diagnose",
) -> Optional[dict]:
    """调 LLM 跑诊断,返回 dict 或 None(降级时)。"""
    from optimizers.static_llm import LLMConfig, call_llm_json

    config_path = project_root / "config" / "optimize-user-config.yaml"
    try:
        cfg = LLMConfig.from_yaml(config_path).with_env_override()
    except (ValueError, OSError) as e:
        logger.warning("LLM 配置加载失败: %s;降级到 skipped 路径", e)
        return None

    knowledge = load_knowledge(project_root)
    if not knowledge:
        logger.warning("5 份知识文档全部缺失,降级")
        return None

    skill_md_path = skill_root / "SKILL.md"
    if not skill_md_path.exists():
        return None

    user_prompt = build_diagnose_prompt(
        skill_root, relation_tree, skill_md_text, knowledge, expert_guidance,
    )
    system_msg = (
        "你是 skill-refactor-agent,基于以下 5 份文档知识做结构层重构诊断。"
        "严格按 user prompt 中的 JSON schema 输出,无 markdown 包裹。\n\n"
        f"===== 知识文档 =====\n\n{knowledge}"
    )
    try:
        return call_llm_json(
            prompt=user_prompt,
            system=system_msg,
            config=cfg,
            debug_label=debug_label,
        )
    except Exception as e:  # noqa: BLE001
        logger.warning("LLM 诊断失败: %s", e)
        return None
