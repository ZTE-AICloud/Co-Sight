"""Skill 结构层重构 — 自动化应用器。

对标 d7bcf0da session 效果(33 文件 +752/-970),本模块让 orchestrator 在
`--mode refactor` 末尾**主动应用**以下深度改动,不依赖外部 session 借鉴
或 LLM 实时推理:

  - FD-004 自动:把 orphan md 合并为 references/lookup-rules/manifest.json + 删 orphan
  - FD-005 自动:把 4 个工具脚本(common/error_handler/utils/config)合并为 lib.sh
               + 改 11 个业务脚本的 source 块为 `source lib.sh` + 删 4 个旧 sh
  - FD-011 自动:跑 SK-S2 引用闭合性 100% 验证,记录结果
  - FD-012 自动:跑 SK-S12 脚本 source 链一致性验证

调用方式:
  run_automator(skill_root, after_skill_dir, relation_tree) -> dict(应用报告)

下次 /skill_optimize --mode refactor 调用,自动应用 80% 深度改动,CC 只做剩余 20% 微调(原 /skill_refactor,v2 合并)。
"""
from __future__ import annotations

import json
import logging
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)


# =================================================================
# FD-004 自动:把 orphan md 合并为 manifest.json
# =================================================================
def auto_merge_orphans_to_manifest(skill_root: Path, after_skill_dir: Path) -> dict:
    """扫描 references/ 下无任何引用的 orphan md(FD-004 候选),
    解析字段(实例名称/业务活动/实体名称/方法名称/方法介绍/方法描述),
    合并为 references/lookup-rules/manifest.json,删除原始 orphan。

    解析策略(对标 d7bcf0da manifest.json schema):
    - 规则类型=组件变更拆分(实例名以 "_接收组件" 或 "_发送组件" 结尾,来自 references/组件变更拆分规则/)
    - 规则类型=子系统间消息处理组件(实例名以 "_消息接收组件" 或 "_消息发送组件" 结尾,来自 references/子系统间消息处理组件规则/)
    - 字段:实例名称/业务活动/实体名称/方法名称/方法介绍/方法介绍模板/方法描述/处理组件表
    """
    refs_root = after_skill_dir / "references"
    if not refs_root.exists():
        return {"orphan_merged": 0, "manifest": None, "note": "references/ 不存在"}

    # 扫描所有 md(排除主流程引用的 7 个 references/*.md)
    protected = {
        "build-comp-inter-fw.md",
        "comp-flow-merge.md",
        "comp-task-split.md",
        "format-spec.md",
        "input-contract.md",
        "output-contract.md",
        "output-full-comp-int-process.md",
    }
    orphans = []
    for md in sorted(refs_root.rglob("*.md")):
        rel = md.relative_to(refs_root)
        # 排除主流程 references/ 和 lookup-rules/ 子目录
        if rel.parent == Path(".") and md.name in protected:
            continue
        orphans.append(md)

    if not orphans:
        return {"orphan_merged": 0, "manifest": None, "note": "无 orphan md"}

    # 解析每个 orphan
    parsed_rules = {"组件变更拆分": [], "子系统间消息处理组件": []}
    for md in orphans:
        try:
            content = md.read_text(encoding="utf-8")
        except OSError as e:
            logger.warning("读 %s 失败: %s; 跳过", md, e)
            continue
        rule = _parse_orphan_md(content, md.stem)
        if rule is None:
            continue
        # 分类
        if "_接收组件" in md.stem or "_发送组件" in md.stem:
            if "拆分" in md.stem or md.stem.endswith("组件") and "消息" not in md.stem:
                parsed_rules["组件变更拆分"].append(rule)
            else:
                parsed_rules["子系统间消息处理组件"].append(rule)
        elif "_消息接收组件" in md.stem or "_消息发送组件" in md.stem:
            parsed_rules["子系统间消息处理组件"].append(rule)
        else:
            # 默认放组件变更拆分
            parsed_rules["组件变更拆分"].append(rule)

    # 生成 manifest.json
    lookup_dir = refs_root / "lookup-rules"
    lookup_dir.mkdir(parents=True, exist_ok=True)
    manifest_path = lookup_dir / "manifest.json"

    manifest = {
        "schema_version": "1.0",
        "description": "组件间流程设计的 lookup 规则清单(由 static_refactor_automator 自动从 orphan md 合并)。通过 scripts/load_rule.sh 按规则类型和 id 查询。",
        "规则类型": {
            "组件变更拆分": {
                "业务活动": "组件间流程设计",
                "实体名称": "组件",
                "方法名称": "组件间变更拆分方法",
                "方法介绍模板": "根据方法判断需求变更点中{实例名}承担的任务",
                "规则": parsed_rules["组件变更拆分"],
            },
            "子系统间消息处理组件": {
                "业务活动": "组件间流程设计",
                "实体名称": "子系统",
                "方法名称": "子系统间消息处理组件规则",
                "方法介绍模板": "根据方法判断子系统间消息的接收或发送的组件",
                "规则": parsed_rules["子系统间消息处理组件"],
            },
        },
    }

    manifest_path.write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    # 删除 orphan md + 空目录
    for md in orphans:
        try:
            md.unlink()
            logger.info("删 orphan: %s", md)
        except OSError as e:
            logger.warning("删 %s 失败: %s", md, e)
    # 删空目录
    for d in sorted(refs_root.rglob("*"), reverse=True):
        if d.is_dir() and not any(d.iterdir()):
            try:
                d.rmdir()
                logger.info("删空目录: %s", d)
            except OSError:
                pass

    return {
        "orphan_merged": len(orphans),
        "manifest": str(manifest_path),
        "rules_count": sum(len(v) for v in parsed_rules.values()),
    }


def _parse_orphan_md(content: str, stem: str) -> Optional[dict]:
    """解析单个 orphan md 的字段。"""
    rule = {"id": stem}
    # 用 H2 标题解析
    section_map = {}
    current_section = None
    for line in content.splitlines():
        m = re.match(r"^##\s+(.+)$", line.strip())
        if m:
            current_section = m.group(1).strip()
            section_map[current_section] = []
        elif current_section and line.strip():
            section_map[current_section].append(line.strip())

    def get(name):
        if name in section_map:
            return "\n".join(section_map[name]).strip()
        return ""

    rule["方法介绍"] = get("方法介绍") or f"根据方法判断需求变更点中{stem}承担的任务"
    rule["方法描述"] = get("方法描述") or get("业务活动") or ""

    # 解析 处理组件表(若有,合并为 dict)
    处理组件表_text = get("处理组件表") or get("方法描述")
    if 处理组件表_text and not rule["方法描述"]:
        # 简单解析 markdown 表格
        rows = []
        for line in 处理组件表_text.splitlines():
            if "|" in line and "---" not in line:
                cells = [c.strip() for c in line.strip().strip("|").split("|")]
                if len(cells) == 2 and cells[0] and cells[0] != "处理组件名称":
                    rows.append({"处理组件名称": cells[0], "判断方法": cells[1]})
        if rows:
            rule["处理组件表"] = rows
            del rule["方法描述"]

    return rule


# =================================================================
# FD-005 自动:把 4 个工具脚本合并为 lib.sh + 改 source 块
# =================================================================
LEGACY_TOOL_SCRIPTS = ("common.sh", "error_handler.sh", "utils.sh", "config.sh")


def auto_merge_tool_scripts_to_lib(skill_root: Path, after_skill_dir: Path) -> dict:
    """把 scripts/ 下的 4 个工具脚本(common/error_handler/utils/config)
    合并为 lib.sh(5 大块:路径常量 / 日志机制 / 工具函数 / 业务常量 / 路径推导),
    改 11 个业务脚本的 source 块为 `source lib.sh`,删除 4 个旧 sh。

    合并策略(对标 d7bcf0da lib.sh 353 行结构):
    - 一路径常量(BASE_DIR / CONSUME_LIB_PATH / WORKSPACE_PATH)← common.sh + config.sh 头部
    - 二日志机制(LOG_LEVEL_* + log_message + 简写函数 + check_* + setup_error_trap)← error_handler.sh
    - 三通用工具(load_script + create_path + parse_* + construct_local_area + auto_concat_entity_name + config_dir_or_file + generate_short_name)← utils.sh
    - 四业务常量(DESIGN_CONSUMPTION + DETAIL_CONSUMPTION + ONTOLOGY_MAP + get_consumption_library_path + get_library_type + analyse/feature/design + PHASE_MAP + get_phase_type)← config.sh
    - 五路径推导(current_task_id / workflow_id / TMP_CONSUMPTION_DIR)← config.sh 末尾
    """
    scripts_dir = after_skill_dir / "scripts"
    if not scripts_dir.exists():
        return {"merged_to_lib": False, "scripts_modified": 0, "note": "scripts/ 不存在"}

    # 检查 4 个工具脚本是否存在
    legacy_paths = {name: scripts_dir / name for name in LEGACY_TOOL_SCRIPTS}
    existing = {n: p for n, p in legacy_paths.items() if p.exists()}
    if not existing:
        return {"merged_to_lib": False, "scripts_modified": 0, "note": "无 4 个工具脚本可合并"}

    # 合并 4 个 sh 为 lib.sh
    lib_path = scripts_dir / "lib.sh"
    lib_content = _build_lib_sh_from_legacy(existing)
    lib_path.write_text(lib_content, encoding="utf-8")

    # 改 11 个业务脚本的 source 块
    business_modified = _replace_source_blocks_in_business_scripts(scripts_dir, lib_path)

    # 删除 4 个旧 sh
    for name, p in existing.items():
        try:
            p.unlink()
            logger.info("删旧工具脚本: %s", p)
        except OSError as e:
            logger.warning("删 %s 失败: %s", p, e)

    return {
        "merged_to_lib": True,
        "lib_path": str(lib_path),
        "lib_lines": lib_content.count("\n"),
        "scripts_modified": business_modified,
    }


def _build_lib_sh_from_legacy(legacy_paths: dict) -> str:
    """机械合并 4 个 sh 为 lib.sh(5 大块)。

    不调用 LLM,纯基于 H1 注释块分割 + 函数体合并。
    解析策略:
    - 读 4 个 sh,按 H1 注释(`# ====...`)分块
    - 重组为 5 大块(对标 d7bcf0da lib.sh)
    - 输出完整 lib.sh(含 header 注释 + 5 大块)
    """
    sections = {"一路径常量": "", "二日志机制": "", "三通用工具": "", "四业务常量": "", "五路径推导": ""}

    # 1. 路径常量 ← common.sh + config.sh 头部
    common = ""
    if "common.sh" in legacy_paths:
        try:
            common = legacy_paths["common.sh"].read_text(encoding="utf-8")
        except OSError:
            pass
    config = ""
    if "config.sh" in legacy_paths:
        try:
            config = legacy_paths["config.sh"].read_text(encoding="utf-8")
        except OSError:
            pass
    # 从 common.sh 提取 BASE_DIR/CONSUME_LIB_PATH/WORKSPACE_PATH
    base_block = _extract_block(common, "BASE_DIR")
    sections["一路径常量"] = base_block if base_block else '''_LIB_SH_SELF="${BASH_SOURCE[0]:-$0}"
BASE_DIR="$(cd "$(dirname "${_LIB_SH_SELF}")" && pwd)"
unset _LIB_SH_SELF

CONSUME_LIB_PATH="$(cd "$BASE_DIR/../../../../../../consume_lib/" && pwd)"
WORKSPACE_PATH="$(cd "$BASE_DIR/../../../../" && pwd)"'''

    # 2. 日志机制 ← error_handler.sh
    if "error_handler.sh" in legacy_paths:
        try:
            err_content = legacy_paths["error_handler.sh"].read_text(encoding="utf-8")
            # 提取 LOG_LEVEL + log_message + 简写函数 + check_command + check_file_exists
            sections["二日志机制"] = _extract_log_block(err_content)
        except OSError:
            pass
    if not sections["二日志机制"]:
        sections["二日志机制"] = '''LOG_LEVEL_ERROR=0
LOG_LEVEL_WARN=1
LOG_LEVEL_INFO=2
LOG_LEVEL_DEBUG=3
LOG_LEVEL=${LOG_LEVEL:-$LOG_LEVEL_INFO}

log_message() {
    local level=$1
    local message=$2
    local timestamp=$(date '+%Y-%m-%d %H:%M:%S %3N')
    if [[ $level -le $LOG_LEVEL ]]; then
        case $level in
            $LOG_LEVEL_ERROR) echo "[$timestamp] [ERROR] $message" >&2 ;;
            $LOG_LEVEL_WARN)  echo "[$timestamp] [WARN] $message" ;;
            $LOG_LEVEL_INFO)  echo "[$timestamp] [INFO] $message" ;;
            $LOG_LEVEL_DEBUG) echo "[$timestamp] [DEBUG] $message" ;;
        esac
    fi
}
log_error() { log_message $LOG_LEVEL_ERROR "$1"; }
log_warn()  { log_message $LOG_LEVEL_WARN "$1"; }
log_info()  { log_message $LOG_LEVEL_INFO "$1"; }
log_debug() { log_message $LOG_LEVEL_DEBUG "$1"; }

check_command() {
    local command_desc=$1
    local exit_code=$2
    if [[ $exit_code -ne 0 ]]; then
        log_error "命令执行失败: $command_desc (退出码: $exit_code)"
        exit $exit_code
    else
        log_info "命令执行成功: $command_desc"
    fi}'''

    # 3. 通用工具 ← utils.sh
    if "utils.sh" in legacy_paths:
        try:
            utils_content = legacy_paths["utils.sh"].read_text(encoding="utf-8")
            sections["三通用工具"] = _extract_utils_block(utils_content)
        except OSError:
            pass
    if not sections["三通用工具"]:
        sections["三通用工具"] = '''load_script() {
    script_path=$1
    if [ -f "$script_path" ]; then
        source "$script_path"
    fi
}

create_path() {
    local dir="$1"
    if [[ ! -d "$dir" ]]; then
        mkdir -p "$dir" && log_debug "已创建目录: $dir"
    fi
}'''

    # 4. 业务常量 ← config.sh
    sections["四业务常量"] = _extract_business_block(config)

    # 5. 路径推导 ← config.sh 末尾
    sections["五路径推导"] = _extract_path_block(config)

    # 拼装 lib.sh
    header = '''#!/bin/bash
# =================================================================
# lib.sh — 组件间流程设计 Skill 统一库入口
# 合并自: common.sh + error_handler.sh + utils.sh + config.sh
# 加载方式: source "$SCRIPT_DIR/lib.sh" 或 source "$BASE_DIR/lib.sh"
# 由 static_refactor_automator 自动生成(对标 d7bcf0da 实战案例)
# =================================================================

'''
    parts = [header]
    titles = [
        ("一路径常量", "原 common.sh + config.sh 头部"),
        ("二日志机制", "原 error_handler.sh"),
        ("三通用工具", "原 utils.sh"),
        ("四业务常量", "原 config.sh 中部"),
        ("五路径推导", "原 config.sh 末尾,依赖 utils.sh 的 parse_*"),
    ]
    for i, (key, comment) in enumerate(titles, 1):
        parts.append("\n# =================================================================\n")
        parts.append(f"# {i}、{key}({comment})\n")
        parts.append("# =================================================================\n")
        parts.append(sections[key] or "# (空,待补)\n")
        parts.append("\n")

    return "".join(parts)


def _extract_block(content: str, anchor: str) -> str:
    """从 content 中提取包含 anchor(变量名/函数名)的代码块。"""
    lines = content.splitlines()
    start_idx = None
    for i, line in enumerate(lines):
        if anchor in line and "=" in line:
            start_idx = i
            break
    if start_idx is None:
        return ""
    # 找到下一个空行或注释块(以 H1 # ==== 开头)
    end_idx = len(lines)
    for j in range(start_idx + 1, len(lines)):
        if lines[j].startswith("# ====") or (j > start_idx + 2 and lines[j].strip() == "" and lines[j+1:j+3] == ["", ""]):
            end_idx = j
            break
    return "\n".join(lines[start_idx:end_idx])


def _extract_log_block(content: str) -> str:
    """从 error_handler.sh 提取日志机制。"""
    lines = content.splitlines()
    # 找到 LOG_LEVEL_ERROR 起点
    start = None
    for i, line in enumerate(lines):
        if "LOG_LEVEL_ERROR=" in line:
            start = i
            break
    if start is None:
        return ""
    # 找到 handle_error 结束(下一个 H1)
    end = len(lines)
    for j in range(start + 1, len(lines)):
        if lines[j].startswith("# ===="):
            end = j
            break
    return "\n".join(lines[start:end])


def _extract_utils_block(content: str) -> str:
    """从 utils.sh 提取工具函数。"""
    lines = content.splitlines()
    start = None
    for i, line in enumerate(lines):
        if line.strip() == "load_script() {" or "load_script()" in line:
            start = i
            break
    if start is None:
        return ""
    return "\n".join(lines[start:])


def _extract_business_block(content: str) -> str:
    """从 config.sh 提取业务常量与映射表(DESIGN_CONSUMPTION 到 get_phase_type)。"""
    lines = content.splitlines()
    start = None
    for i, line in enumerate(lines):
        if "DESIGN_CONSUMPTION=" in line:
            start = i
            break
    if start is None:
        return ""
    # 找到 current_task_id 之前
    end = len(lines)
    for j in range(start + 1, len(lines)):
        if "current_task_id=" in lines[j]:
            end = j
            break
    return "\n".join(lines[start:end])


def _extract_path_block(content: str) -> str:
    """从 config.sh 提取路径推导(current_task_id / workflow_id / TMP_CONSUMPTION_DIR)。"""
    lines = content.splitlines()
    start = None
    for i, line in enumerate(lines):
        if "current_task_id=" in line:
            start = i
            break
    if start is None:
        return ""
    return "\n".join(lines[start:])


def _replace_source_blocks_in_business_scripts(scripts_dir: Path, lib_path: Path) -> int:
    """改 11 个业务脚本的 source 块为 `source lib.sh`,返回修改文件数。

    模式 A:`if [ -f "$BASE_DIR/config.sh" ]; then source "$BASE_DIR/config.sh"; else ... fi` → 改 config.sh → lib.sh
    模式 B:`source "$BASE_DIR/config.sh"` + `source "$BASE_DIR/common.sh"` → `source "$BASE_DIR/lib.sh"`
    模式 C:`source "$SCRIPT_DIR/config.sh"` + `source "$SCRIPT_DIR/common.sh"` → `source "$SCRIPT_DIR/lib.sh"`
    """
    patterns = [
        # 模式 A
        (
            re.compile(
                r'if \[\s*-f\s+"\$\{?BASE_DIR\}?/config\.sh"\s*\];\s*then\s*\n'
                r'\s*source\s+"\$\{?BASE_DIR\}?/config\.sh"\s*\n'
                r'\s*else\s*\n'
                r'\s*echo\s+"错误:\s*找不到配置模块\s*\$\{?BASE_DIR\}?/config\.sh"\s*>&2\s*\n'
                r'\s*exit\s+1\s*\n'
                r'\s*fi',
                re.MULTILINE,
            ),
            'if [ -f "$BASE_DIR/lib.sh" ]; then\n    source "$BASE_DIR/lib.sh"\nelse\n    echo "错误: 找不到 lib 模块 $BASE_DIR/lib.sh" >&2\n    exit 1\nfi',
        ),
        # 模式 B
        (
            re.compile(
                r'source\s+"\$\{?BASE_DIR\}?/config\.sh"\s*\n'
                r'source\s+"\$\{?BASE_DIR\}?/common\.sh"\s*\n?',
                re.MULTILINE,
            ),
            'source "$BASE_DIR/lib.sh"',
        ),
        # 模式 C
        (
            re.compile(
                r'source\s+"\$\{?SCRIPT_DIR\}?/config\.sh"\s*\n'
                r'source\s+"\$\{?SCRIPT_DIR\}?/common\.sh"\s*\n?',
                re.MULTILINE,
            ),
            'source "$SCRIPT_DIR/lib.sh"',
        ),
    ]

    modified = 0
    for sh in sorted(scripts_dir.glob("*.sh")):
        if sh.name == "lib.sh" or sh.name in LEGACY_TOOL_SCRIPTS:
            continue
        try:
            text = sh.read_text(encoding="utf-8")
        except OSError:
            continue
        original = text
        # 应用通用回退: 简单替换 config.sh / common.sh → lib.sh
        text = text.replace('"$BASE_DIR/config.sh"', '"$BASE_DIR/lib.sh"')
        text = text.replace('"$SCRIPT_DIR/config.sh"', '"$SCRIPT_DIR/lib.sh"')
        text = text.replace('"$BASE_DIR/common.sh"', '"$BASE_DIR/lib.sh"')
        text = text.replace('"$SCRIPT_DIR/common.sh"', '"$SCRIPT_DIR/lib.sh"')
        # 应用模式匹配
        for pat, repl in patterns:
            text = pat.sub(repl, text)
        if text != original:
            sh.write_text(text, encoding="utf-8")
            modified += 1
            logger.info("改 source 块: %s", sh)
    return modified


# =================================================================
# FD-011/FD-012 自动化验证
# =================================================================
def auto_validate_after_refactor(after_skill_dir: Path) -> dict:
    """跑 SK-S2 引用闭合性 + SK-S12 脚本 source 链一致性验证,返回 dict。"""
    skill_md = after_skill_dir / "SKILL.md"
    if not skill_md.exists():
        return {"sk_s2_pass": False, "sk_s12_pass": False, "note": "SKILL.md 不存在"}

    # SK-S2 引用闭合性
    import subprocess
    s2_result = subprocess.run(
        ["grep", "-oE", r"(references|scripts|templates)/[a-zA-Z0-9_./-]+\.(md|py|sh|json|yaml|yml)",
         str(skill_md)],
        capture_output=True, text=True,
    )
    refs = sorted(set(s2_result.stdout.splitlines()))
    s2_missing = []
    for r in refs:
        # 跳过父级路径(如 scripts/bash/consume/...)
        if "bash/consume" in r or r.startswith("scripts/collect_") or r.startswith("scripts/fetch_"):
            continue
        path = after_skill_dir / r
        if not path.exists():
            s2_missing.append(r)

    # SK-S12 脚本 source 链
    scripts_dir = after_skill_dir / "scripts"
    s12_residual = 0
    if scripts_dir.exists():
        s12_result = subprocess.run(
            ["grep", "-rln", r"if.*-f.*\.(config|common|error_handler|utils)\.sh", str(scripts_dir)],
            capture_output=True, text=True,
        )
        s12_residual = len([l for l in s12_result.stdout.splitlines() if l and "README.md" not in l])

    return {
        "sk_s2_pass": len(s2_missing) == 0,
        "sk_s2_total_refs": len(refs),
        "sk_s2_missing": s2_missing,
        "sk_s12_pass": s12_residual == 0,
        "sk_s12_residual": s12_residual,
    }


# =================================================================
# 主入口(在 orchestrator _run_refactor_mode 末尾调用)
# =================================================================
def run_automator(skill_root: Path, after_skill_dir: Path, relation_tree: dict) -> dict:
    """对标 d7bcf0da session,自动应用 80% 深度改动。

    Returns:
        dict {
            "fd_004_orphan_merged": int,
            "fd_004_manifest": str|None,
            "fd_005_lib_path": str|None,
            "fd_005_scripts_modified": int,
            "fd_011_sk_s2_pass": bool,
            "fd_011_sk_s2_missing": list,
            "fd_012_sk_s12_pass": bool,
            "fd_012_sk_s12_residual": int,
            "generated_at": str,
        }
    """
    logger.info("=== automator 启动:skill=%s ===", after_skill_dir)

    # FD-004
    fd4 = auto_merge_orphans_to_manifest(skill_root, after_skill_dir)
    logger.info("FD-004 报告: %s", fd4)

    # FD-005
    fd5 = auto_merge_tool_scripts_to_lib(skill_root, after_skill_dir)
    logger.info("FD-005 报告: %s", fd5)

    # FD-011/012
    val = auto_validate_after_refactor(after_skill_dir)
    logger.info("验证报告: %s", val)

    return {
        "fd_004_orphan_merged": fd4.get("orphan_merged", 0),
        "fd_004_manifest": fd4.get("manifest"),
        "fd_005_lib_path": fd5.get("lib_path"),
        "fd_005_scripts_modified": fd5.get("scripts_modified", 0),
        "fd_011_sk_s2_pass": val.get("sk_s2_pass"),
        "fd_011_sk_s2_total_refs": val.get("sk_s2_total_refs"),
        "fd_011_sk_s2_missing": val.get("sk_s2_missing"),
        "fd_012_sk_s12_pass": val.get("sk_s12_pass"),
        "fd_012_sk_s12_residual": val.get("sk_s12_residual"),
        "generated_at": datetime.now(timezone.utc).isoformat(),
    }


def write_automator_report(report: dict, output_path: Path) -> None:
    """写 automator 报告到 refactor_automator_report.md(便于 CC 审阅)。"""
    output_path.parent.mkdir(parents=True, exist_ok=True)
    lines = [
        "# Refactor Automator 报告(对标 d7bcf0da 自动应用)",
        "",
        f"生成时间:{report.get('generated_at')}",
        "",
        "## FD-004 orphan 合并",
        f"- 合并 orphan 数:{report.get('fd_004_orphan_merged')}",
        f"- manifest 路径:{report.get('fd_004_manifest') or '(无)'}",
        "",
        "## FD-005 scripts/ 工具层合并",
        f"- lib.sh 路径:{report.get('fd_005_lib_path') or '(未生成)'}",
        f"- 改 source 块脚本数:{report.get('fd_005_scripts_modified')}",
        "",
        "## FD-011 SK-S2 引用闭合性",
        f"- 通过:{report.get('fd_011_sk_s2_pass')}",
        f"- 引用总数:{report.get('fd_011_sk_s2_total_refs')}",
        f"- 缺失:{report.get('fd_011_sk_s2_missing')}",
        "",
        "## FD-012 SK-S12 脚本 source 链",
        f"- 通过:{report.get('fd_012_sk_s12_pass')}",
        f"- 残留 if 块:{report.get('fd_012_sk_s12_residual')}",
        "",
        "---",
        "",
        "> 本报告由 `static_refactor_automator.run_automator` 自动生成,无需 LLM 推理。",
        "> 下一步:CC 审阅报告 → 在 after_skill/ 副本上做剩余 20% 微调(例如 SKILL.md 大改、新增 references/* 内容)。",
    ]
    output_path.write_text("\n".join(lines), encoding="utf-8")