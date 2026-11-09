"""
check_overfit.py — anti-overfitting 硬校验(借鉴 SkillOpt skill_aware)

输入: stage_3_modifications.json + 源文件 dict(file path -> content)
输出: dict {passed: bool, violations: [{rule_id, mod_id, detail}]}

规则(从 framework_configs/proposal-agent-config.yaml:anti_overfitting_rules 提炼):
R1 禁止引用具体业务术语名(枚举列表,业务方在 user-config.yaml.overfit.business_terms 配)
R2 禁止捏造具体数字阈值(阈值词 + 连续数字)
R3 禁止列举具体 case_id(正则匹配 RAN-/CASE-/TC-/REQ-/TEST- 前缀)
R4 禁止写"差 vs 优"对照示例(检测含"错误示例"或"差:"对比段)
R5 reason 必须证明泛化性(必须含泛化关键词之一)
R6 current_content 必须从原文复制(强制 str in src 校验)
R7 coverage 中 unchanged 也要写 reason(非空)
R8 只能在 H2 层级做合并/补充/拆解(section 必须是 ## 开头)
"""

from __future__ import annotations

import re
from typing import Dict, List

# 8 条规则的常量定义
_CASE_ID_PATTERN = re.compile(r"\b(?:RAN|CASE|TC|REQ|TEST)-\d+")
# R2: 数字阈值模式。匹配 "阈值≥8" / ">=3" / "≤5" / "上限:10" 等
_THRESHOLD_PATTERN = re.compile(
    r"(?:阈值|上限|下限|阈值\s*[为是]|>=|<=|≥|≤|大于等于|小于等于)\s*[\d.]+",
    re.UNICODE,
)
# 数字模式(通用,用于辅助检测捏造数字)
_NUMERIC_PATTERN = re.compile(r"\b\d+(?:\.\d+)?\b")
# R5: reason 泛化性关键词
_GENERALIZATION_KEYWORDS = [
    "通用", "系统", "一致", "共同", "大多数", "通常",
    "general", "systemic", "consistent", "common", "typically",
]
_GENERALIZATION_PATTERN = re.compile(
    "|".join(re.escape(kw) for kw in _GENERALIZATION_KEYWORDS),
    re.IGNORECASE,
)
# R4: 差 vs 优对照示例检测(中文典型写法)
_BAD_VS_GOOD_PATTERN = re.compile(
    r"(?:错\s*误?\s*示\s*例|差\s*[:：]|优\s*[:：]|错误写法|正确写法|不要\s*[::]|应该\s*[::])",
    re.UNICODE,
)


def check_overfit(modifications_json: dict, source_files: Dict[str, str],
                  business_terms: List[str] = None) -> dict:
    """校验 modifications 是否违反 anti-overfitting 8 条硬规则。

    Args:
        modifications_json: stage_3_modifications.json 内容,含 `modifications[]` 和 `coverage[]`
        source_files: {file_path: file_content},用于 R6 校验 current_content 是否在源文件中
        business_terms: 业务方在 user-config.yaml.overfit.business_terms 配置的业务术语列表

    Returns:
        dict {passed: bool, violations: [{rule_id, mod_id, detail, severity}], checked_count: int}
    """
    business_terms = business_terms or []
    violations = []
    checked = 0

    for mod in modifications_json.get("modifications") or []:
        checked += 1
        mod_id = mod.get("mod_id", "?")
        new_content = mod.get("new_content", "") or ""
        reason = mod.get("reason", "") or ""
        current_content = mod.get("current_content") or ""
        section = mod.get("section", "") or ""
        file_path = mod.get("file", "") or ""

        # R1: 业务术语(从 user-config.yaml.overfit.business_terms 读)
        for term in business_terms:
            if not term:
                continue
            if term in new_content or term in reason:
                violations.append({
                    "rule_id": "R1", "mod_id": mod_id, "severity": "high",
                    "detail": f"引用业务术语 {term!r}",
                })

        # R2: 数字阈值(LLM 经常在 new_content 里捏造具体阈值)
        if _THRESHOLD_PATTERN.search(new_content):
            violations.append({
                "rule_id": "R2", "mod_id": mod_id, "severity": "high",
                "detail": f"new_content 含具体数字阈值:{_THRESHOLD_PATTERN.search(new_content).group(0)!r}",
            })

        # R3: case_id 列举(任何地方出现都算)
        if _CASE_ID_PATTERN.search(new_content + "\n" + reason):
            violations.append({
                "rule_id": "R3", "mod_id": mod_id, "severity": "critical",
                "detail": f"出现具体 case_id:{_CASE_ID_PATTERN.findall(new_content + ' ' + reason)[:3]}",
            })

        # R4: 差 vs 优对照示例(LLM 经常在 new_content 里写"错误写法: ... / 正确写法: ...")
        if _BAD_VS_GOOD_PATTERN.search(new_content):
            violations.append({
                "rule_id": "R4", "mod_id": mod_id, "severity": "medium",
                "detail": "new_content 含差 vs 优对照示例",
            })

        # R5: reason 泛化性证明
        if reason and not _GENERALIZATION_PATTERN.search(reason):
            violations.append({
                "rule_id": "R5", "mod_id": mod_id, "severity": "medium",
                "detail": "reason 未证明泛化性(必须含「通用/系统/一致/共同/大多数/通常」等关键词之一)",
            })

        # R6: current_content 必须从原文复制
        src_content = source_files.get(file_path) or source_files.get(
            _normalize_path(file_path), "",
        )
        if current_content and src_content:
            if current_content not in src_content:
                violations.append({
                    "rule_id": "R6", "mod_id": mod_id, "severity": "critical",
                    "detail": f"current_content 不在源文件 {file_path} 中(可能 LLM 凭印象重写)",
                })

        # R8: section 必须是 H2 层级
        if section and not section.lstrip().startswith("## "):
            violations.append({
                "rule_id": "R8", "mod_id": mod_id, "severity": "high",
                "detail": f"section {section!r} 不是 H2 层级(必须以 '## ' 开头)",
            })

    # R7: coverage 中 unchanged 也要写 reason(独立校验)
    for cov in modifications_json.get("coverage") or []:
        if cov.get("status") == "unchanged" and not (cov.get("reason") or "").strip():
            violations.append({
                "rule_id": "R7", "mod_id": f"coverage:{cov.get('file', '?')}",
                "severity": "low",
                "detail": f"coverage 中 {cov.get('file', '?')} 标 unchanged 但 reason 为空",
            })

    return {
        "passed": len(violations) == 0,
        "violations": violations,
        "checked_count": checked,
        "rules_applied": ["R1", "R2", "R3", "R4", "R5", "R6", "R7", "R8"],
    }


def _normalize_path(p: str) -> str:
    """去掉常见前缀,统一路径格式(skill/ 或 skills/ 之后的部分)。"""
    if not p:
        return p
    for marker in ("/skill/", "/skills/"):
        idx = p.find(marker)
        if idx >= 0:
            return p[idx + len(marker):]
    return p
