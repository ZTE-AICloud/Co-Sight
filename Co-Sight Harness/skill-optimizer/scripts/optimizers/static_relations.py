"""
Skill 文件关系树扫描器
====================
框架侧确定性扫描器：对一个 Skill 目录下的所有文件建立「关系树」骨架
（files / edges / reverse_index / orphans / long_unoptimized / summary_table），
供 evaluator / optimizer prompt 注入，让 LLM 对全部文件建立统一认知，
而非只盯着 SKILL.md。

设计原则（见 rules/skillx-alpha-generic.md）：
- 通用：schema 全部相对路径 + 扩展名 + 路径前缀推断 role，无任何业务字段。
- 兜底：所有核心字段由 regex 确定性产出；LLM 只在 subagent 模式可选补充隐式依赖
  （通过 merge_relation_additions 合并）。
- 降级：扫描抛异常时返回空树，不阻断主链路。

用法：
    from optimizers.static_relations import build_relation_tree
    tree = build_relation_tree(skill_root, target_files, protected_assets, history_path)
"""

import json
import logging
import os
import re
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)

SCHEMA_VERSION = 1
GENERATOR = "static_relation_scanner"
# 关系树落盘文件名（workspace 顶层，跨 round 复用；evaluator/optimizer 从此读取）
RELATION_TREE_FILENAME = "skill_file_relations.json"

# 关系树识别的路径扩展名（与 static_optimizer 的 MD/CODE 集合对齐）
_EDGE_EXTS = r"(?:md|py|sh|json|yaml|yml|toml|mjs|js|ts)"
# 反引号包裹的路径引用：`scripts/upload.py`
_RE_BACKTICK = re.compile(r"`([\w./\-]+\." + _EDGE_EXTS + r")`")
# 命令行调用：python3 scripts/x.py / bash x.sh / node x.mjs
_RE_COMMAND = re.compile(
    r"(?:python3?|bash|sh|node)\s+([\w./\-]+\.(?:py|sh|mjs|js|ts))"
)
# 裸相对路径：scripts/upload.py（不以 / 开头，且不紧跟反引号）
_RE_RELATIVE = re.compile(r"(?<![\w`/])((?:[\w\-]+/)+[\w\-]+\." + _EDGE_EXTS + r")")


def _role(rel_path: str, kind: str) -> str:
    """按路径前缀 + 扩展名推断文件角色（通用，无业务字段）。"""
    if rel_path == "SKILL.md":
        return "entrypoint"
    parts = rel_path.split("/")
    top = parts[0] if len(parts) > 1 else ""
    if top == "references":
        return "knowledge"
    if top == "scripts" and kind == "code":
        return "implementation"
    if top == "templates":
        return "template"
    if top in ("assets", "images"):
        return "asset"
    if kind == "md":
        return "doc"
    if kind == "code":
        return "aux_code"
    return "data"


def _norm_path(raw: str) -> str:
    """归一化引用路径：去掉前导 ./ 与结尾标点。"""
    p = raw.strip().lstrip("./").rstrip(".,;:)")
    return p


def _resolve_dst(raw: str, valid_paths: set) -> Optional[str]:
    """把引用字符串解析为 files[] 中真实存在的相对路径，无法解析返回 None。"""
    norm = _norm_path(raw)
    if norm in valid_paths:
        return norm
    # 后缀匹配（唯一）：references/x.md 匹配 sub/references/x.md
    suffix_hits = [vp for vp in valid_paths if vp.endswith("/" + norm)]
    if len(suffix_hits) == 1:
        return suffix_hits[0]
    # basename 匹配（唯一）
    base = norm.split("/")[-1]
    base_hits = [vp for vp in valid_paths if vp.split("/")[-1] == base]
    if len(base_hits) == 1:
        return base_hits[0]
    return None


def _scan_edges(src_rel: str, content: str, valid_paths: set) -> list[dict]:
    """逐行扫描一个文件的所有出向引用边（三类 regex）。"""
    edges: list[dict] = []
    seen: set = set()  # (dst, type) 去重

    def _add(raw: str, etype: str, lineno: int, evidence: str) -> None:
        dst = _resolve_dst(raw, valid_paths)
        if not dst or dst == src_rel:
            return
        key = (dst, etype)
        if key in seen:
            return
        seen.add(key)
        edges.append({
            "src": src_rel, "dst": dst, "type": etype, "loc_src": lineno,
            "evidence": evidence[:120], "confidence": "high",
        })

    for lineno, line in enumerate(content.splitlines(), start=1):
        for m in _RE_BACKTICK.finditer(line):
            _add(m.group(1), "ref_backtick", lineno, "`" + m.group(1) + "`")
        for m in _RE_COMMAND.finditer(line):
            _add(m.group(1), "ref_command", lineno, m.group(0))
        # 裸路径：跳过已被反引号包裹的（反引号内路径已由 _RE_BACKTICK 捕获）
        stripped = line.replace("`", " ")
        for m in _RE_RELATIVE.finditer(stripped):
            _add(m.group(1), "ref_relative", lineno, m.group(1))
    return edges


def _file_meta(f: Path, skill_root: Path, protected_assets: list[str]) -> Optional[dict]:
    """构造单个文件的元信息条目；二进制/不可读返回 None。"""
    from .static_optimizer import classify_file, is_protected

    kind = classify_file(f)
    if kind == "skip":
        return None
    rel = f.relative_to(skill_root).as_posix()
    try:
        content = f.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        content = ""
    lines = content.splitlines()
    heads = [ln for ln in lines if re.match(r"^#{1,6}\s", ln)]
    top_sections = [
        re.sub(r"^#{1,6}\s+", "", ln).strip()[:40]
        for ln in lines if re.match(r"^#{1,2}\s", ln)
    ][:5]
    return {
        "path": rel,
        "abs_path": str(f),
        "kind": kind,
        "extension": f.suffix.lower(),
        "size_bytes": len(content.encode("utf-8")),
        "line_count": len(lines),
        "section_count": len(heads),
        "top_sections": top_sections,
        "role": _role(rel, kind),
        "is_skill_md": rel == "SKILL.md",
        "in_references": rel.startswith("references/"),
        "in_scripts": rel.startswith("scripts/"),
        "in_templates": rel.startswith("templates/"),
        "is_protected": is_protected(rel, protected_assets),
        "_content": content,  # 仅内部用于扫边，最终从输出剔除
    }


def _load_history_changed(history_path: Optional[Path]) -> set:
    """从 static_history.json 汇总历轮 files_changed 并集（通用字段扫描）。"""
    if not history_path or not history_path.exists():
        return set()
    try:
        data = json.loads(history_path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return set()
    rounds = data.get("history", data) if isinstance(data, dict) else data
    changed: set = set()
    if isinstance(rounds, list):
        for r in rounds:
            if not isinstance(r, dict):
                continue
            for key in ("files_changed", "changed_files"):
                for f in r.get(key, []) or []:
                    if isinstance(f, str):
                        changed.add(f)
    return changed


def _human_size(n: int) -> str:
    return f"{n / 1024:.1f}KB" if n >= 1024 else f"{n}B"


# 按 role 划分的默认权重（和不一定为 1，调用方会归一化）
_ROLE_BASE_WEIGHT: dict[str, float] = {
    "entrypoint":     0.55,  # SKILL.md：技能契约层
    "implementation": 0.20,  # scripts/*.sh：实现层
    "knowledge":      0.10,  # references/*.md：知识层
    "template":       0.10,  # templates/*.md：模板层
    "asset":          0.025, # 资源（一般不评分）
    "data":           0.025, # 配置/数据
    "other":          0.025, # 其他
    "doc":            0.025, # 散落文档
    "aux_code":       0.025, # 辅助代码
}


def _compute_file_weight(this_role: str, all_roles: list[str]) -> float:
    """计算单个文件在聚合评分时的权重（按 role 分配 + 同 role 均分）。

    算法：
    1. 按 _ROLE_BASE_WEIGHT 给每个 role 一个基础权重
    2. 同 role 文件均分该 role 的基础权重
    3. 最终归一化（sum → 1.0），保证分母是总和

    这样：
    - SKILL.md 默认权重 ≈ 0.55
    - scripts 多个文件 → 每个 ~0.20/N
    - 总和恒为 1.0（即使 role 权重和不为 1，归一化后保证）
    """
    base = _ROLE_BASE_WEIGHT
    # 统计每个 role 出现次数
    role_counts: dict[str, int] = {}
    for r in all_roles:
        role_counts[r] = role_counts.get(r, 0) + 1
    # 当前 role 的"该 role 文件均分后的基础权重"
    this_count = role_counts.get(this_role, 1)
    this_base = base.get(this_role, 0.05)
    raw_weight = this_base / this_count
    # 全部文件 raw_weight 之和（每个文件一份，N 个文件总和 = base 总和）
    total_raw = sum(base.get(r, 0.05) for r in role_counts)
    if total_raw <= 0:
        return 1.0 / max(1, len(all_roles))  # 退化均分
    return round(raw_weight / total_raw, 6)


def _compute_clusters(
    metas: list[dict],
    edges: list[dict],
    reverse_index: dict,
    orphans: list[str],
) -> list[dict]:
    """按引用关系聚类文件为「关系簇」，让 LLM 跨文件联动考虑修改。

    聚类规则（不假设业务字段，按通用拓扑启发）：
      - 「契约簇」：包含 SKILL.md + 其直接引用的 references/ + templates/（契约核心）
      - 「实现簇」：以 scripts/*.sh 为节点的连通分量（相互调用的脚本）
      - 「孤立文件簇」：无引用也未被引用的文件
      - 「跨簇依赖」：一个文件可能同时出现在多个簇（保留）

    Args:
        metas: 文件元信息列表（已按 size 截断到 max_files）
        edges: src→dst 边列表
        reverse_index: dst→[src...] 反向索引
        orphans: 无引用的文件路径列表

    Returns:
        [{"name": str, "type": "contract"|"implementation"|"orphan"|"mixed",
          "files": [path...], "edge_count": int}, ...]
    """
    valid_paths = {m["path"] for m in metas}
    in_deg = {p: len(reverse_index.get(p, [])) for p in valid_paths}
    out_deg: dict[str, int] = {p: 0 for p in valid_paths}
    for e in edges:
        out_deg[e["src"]] = out_deg.get(e["src"], 0) + 1

    clusters: list[dict] = []

    # 1. 契约簇：SKILL.md + 其 1-hop 引用（BFS 1 层，避免过度膨胀）
    skill_path = "SKILL.md" if "SKILL.md" in valid_paths else None
    if skill_path:
        contract_files = {skill_path}
        # SKILL.md 引用的所有文件
        for e in edges:
            if e["src"] == skill_path and e["dst"] in valid_paths:
                contract_files.add(e["dst"])
        # 反向：引用 SKILL.md 的文件（如果有）
        for src in (r.get("src") for r in reverse_index.get(skill_path, [])):
            if src in valid_paths:
                contract_files.add(src)
        contract_edges = sum(
            1 for e in edges
            if e["src"] in contract_files and e["dst"] in contract_files
        )
        clusters.append({
            "name": "契约簇",
            "type": "contract",
            "files": sorted(contract_files),
            "edge_count": contract_edges,
        })

    # 2. 实现簇：scripts/*.sh 为节点的连通分量（BFS）
    script_paths = {m["path"] for m in metas if m["path"].startswith("scripts/")}
    visited: set = set()
    for sp in sorted(script_paths):
        if sp in visited:
            continue
        # BFS 找连通的脚本
        component = {sp}
        queue = [sp]
        while queue:
            cur = queue.pop(0)
            for e in edges:
                if e["src"] == cur and e["dst"] in script_paths and e["dst"] not in component:
                    component.add(e["dst"])
                    queue.append(e["dst"])
                if e["dst"] == cur and e["src"] in script_paths and e["src"] not in component:
                    component.add(e["src"])
                    queue.append(e["src"])
        visited |= component
        comp_edges = sum(
            1 for e in edges
            if e["src"] in component and e["dst"] in component
        )
        if len(component) > 1:  # 单文件不算"簇"
            clusters.append({
                "name": f"实现簇（{len(component)} 个脚本互联）",
                "type": "implementation",
                "files": sorted(component),
                "edge_count": comp_edges,
            })

    # 3. 孤立文件簇
    if orphans:
        orphan_edges = 0  # orphan 本身无引用
        clusters.append({
            "name": f"孤立文件簇（{len(orphans)} 个无引用）",
            "type": "orphan",
            "files": sorted(set(orphans) & valid_paths),
            "edge_count": orphan_edges,
        })

    # 4. 剩余未聚类的文件（如 templates/ 单独出现未被 SKILL.md 引用的）
    clustered: set = set()
    for c in clusters:
        clustered |= set(c["files"])
    leftover = sorted(valid_paths - clustered)
    if leftover:
        clusters.append({
            "name": f"其他文件（{len(leftover)} 个）",
            "type": "mixed",
            "files": leftover,
            "edge_count": sum(
                1 for e in edges
                if e["src"] in leftover or e["dst"] in leftover
            ),
        })

    return clusters


def build_relation_tree(
    skill_root: Path,
    target_files: list[Path],
    protected_assets: list[str],
    history_path: Optional[Path] = None,
    max_files: int = 50,
) -> dict:
    """扫描 Skill 目录，产出关系树骨架。异常时返回空树（不阻断主链路）。"""
    try:
        return _build_relation_tree_impl(
            skill_root, target_files, protected_assets, history_path, max_files
        )
    except Exception as e:  # noqa: BLE001 — 关系树是辅助信息，绝不能阻断主链路
        logger.warning("关系树扫描失败,降级为空树: %s", e)
        return {
            "schema_version": SCHEMA_VERSION, "generator": GENERATOR,
            "skill_root_abs": str(skill_root), "files": [], "edges": [],
            "reverse_index": {}, "orphans": [], "long_unoptimized": [],
            "summary_table": [], "stats": {"file_count": 0, "edge_count": 0},
            "_error": str(e),
        }


def _build_relation_tree_impl(
    skill_root: Path,
    target_files: list[Path],
    protected_assets: list[str],
    history_path: Optional[Path],
    max_files: int,
) -> dict:
    metas = [
        m for m in (
            _file_meta(f, skill_root, protected_assets) for f in target_files
        ) if m is not None
    ]
    total_files = len(metas)
    # SKILL.md 优先保留，其余按 size 降序，cap 到 max_files
    metas.sort(key=lambda m: (not m["is_skill_md"], -m["size_bytes"]))
    metas = metas[:max_files]
    valid_paths = {m["path"] for m in metas}

    # 扫描出向引用边 + 反向索引
    edges: list[dict] = []
    reverse_index: dict = {}
    for m in metas:
        for e in _scan_edges(m["path"], m.pop("_content"), valid_paths):
            edges.append(e)
            reverse_index.setdefault(e["dst"], []).append(
                {"src": e["src"], "type": e["type"], "loc_src": e["loc_src"]}
            )

    out_deg = {p: 0 for p in valid_paths}
    for e in edges:
        out_deg[e["src"]] = out_deg.get(e["src"], 0) + 1
    in_deg = {p: len(reverse_index.get(p, [])) for p in valid_paths}

    orphans = [
        m["path"] for m in metas
        if not m["is_skill_md"] and in_deg[m["path"]] == 0 and out_deg[m["path"]] == 0
    ]
    changed = _load_history_changed(history_path)
    long_unoptimized = [
        m["path"] for m in metas
        if not m["is_skill_md"] and m["role"] != "asset" and m["path"] not in changed
    ]

    summary_table = [
        {
            "path": m["path"], "role": m["role"], "size": _human_size(m["size_bytes"]),
            "lines": m["line_count"], "sections": m["section_count"],
            "refs_in": in_deg[m["path"]], "refs_out": out_deg[m["path"]],
            "protected": m["is_protected"],
            "weight": _compute_file_weight(m["role"], [x["role"] for x in metas]),
        }
        for m in metas
    ]

    kinds = [m["kind"] for m in metas]
    clusters = _compute_clusters(metas, edges, reverse_index, orphans)
    return {
        "schema_version": SCHEMA_VERSION,
        "generator": GENERATOR,
        "skill_root_abs": str(skill_root),
        "files": metas,
        "edges": edges,
        "reverse_index": reverse_index,
        "orphans": orphans,
        "long_unoptimized": long_unoptimized,
        "summary_table": summary_table,
        "stats": {
            "file_count": len(metas),
            "total_files_scanned": total_files,
            "truncated": total_files > len(metas),
            "md_count": kinds.count("md"),
            "code_count": kinds.count("code"),
            "edge_count": len(edges),
            "orphan_count": len(orphans),
            "max_indegree": max(in_deg.values(), default=0),
            "max_outdegree": max(out_deg.values(), default=0),
            "cluster_count": len(clusters),
        },
        "clusters": clusters,
    }


def merge_relation_additions(tree: dict, additions: list[dict]) -> dict:
    """合并 LLM（subagent 模式）补充的隐式依赖边，按 (src,dst,type) 去重。

    additions 为可选字段：LLM 不输出则不调用；输出格式非法则跳过单条，不报错。
    """
    if not additions or not isinstance(tree, dict):
        return tree
    existing = {(e["src"], e["dst"], e["type"]) for e in tree.get("edges", [])}
    valid_paths = {m["path"] for m in tree.get("files", [])}
    added = 0
    for a in additions:
        if not isinstance(a, dict):
            continue
        src, dst = a.get("src"), a.get("dst")
        etype = a.get("type", "ref_llm")
        if src not in valid_paths or dst not in valid_paths:
            continue
        key = (src, dst, etype)
        if key in existing:
            continue
        existing.add(key)
        tree.setdefault("edges", []).append({
            "src": src, "dst": dst, "type": etype,
            "loc_src": a.get("loc_src", 0),
            "evidence": str(a.get("evidence", ""))[:120],
            "confidence": a.get("confidence", "medium"),
        })
        tree.setdefault("reverse_index", {}).setdefault(dst, []).append(
            {"src": src, "type": etype, "loc_src": a.get("loc_src", 0)}
        )
        added += 1
    if added:
        tree.setdefault("stats", {})["edge_count"] = len(tree.get("edges", []))
    return tree


def write_relation_tree(tree: dict, out_path: Path) -> None:
    """原子写关系树 JSON（先写 .tmp 再 os.replace，避免并发读到半截文件）。"""
    out_path.parent.mkdir(parents=True, exist_ok=True)
    tmp = out_path.with_suffix(out_path.suffix + ".tmp")
    tmp.write_text(json.dumps(tree, ensure_ascii=False, indent=2), encoding="utf-8")
    os.replace(tmp, out_path)
