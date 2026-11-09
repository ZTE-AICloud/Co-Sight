"""
工作空间管理模块
================

负责工作空间相关的路径推断、沙箱回拷、文件清理等操作。
"""

from __future__ import annotations

import logging
import os
import shutil
from pathlib import Path
from typing import List, Optional

import yaml
from hooks import HookRegistry


def _resolve_evolve_config_path() -> Path:
    """解析 /skill_evolve 模式的 user-config 路径。

    优先 `config/evolve-user-config.yaml`（v1 重命名后的业务方主入口），
    fallback `config/user-config.yaml`（旧名，向后兼容）。
    """
    config_dir = Path(__file__).parent.parent.parent / "config"
    new_path = config_dir / "evolve-user-config.yaml"
    old_path = config_dir / "user-config.yaml"
    if new_path.exists():
        return new_path
    return old_path


USER_CONFIG_PATH = _resolve_evolve_config_path()


def get_need_cleaned_dirs() -> List[Path]:
    """从 user-config.yaml 读取 paths.need_cleaned_dir（YAML list），返回 Path 列表。

    不通过环境变量中转，list 在 Python 层保持原生 list，避免 join/split 字符串编码循环。
    覆盖优先级:SKILLX_NEED_CLEANED_DIR 环境变量(逗号分隔) > user-config.yaml。
    """
    env_override = os.environ.get("SKILLX_NEED_CLEANED_DIR", "").strip()
    if env_override:
        return [Path(p.strip()) for p in env_override.split(",") if p.strip()]
    if not USER_CONFIG_PATH.exists():
        return []
    with open(USER_CONFIG_PATH, "r", encoding="utf-8") as f:
        cfg = yaml.safe_load(f) or {}
    val = (cfg.get("paths") or {}).get("need_cleaned_dir") or []
    if not isinstance(val, list):
        return []
    return [Path(str(x).strip()) for x in val if str(x).strip()]


def get_case_ids() -> List[str]:
    """从 user-config.yaml 读取 filter.case_ids（YAML list），返回字符串列表。

    不通过环境变量中转，list 在 Python 层保持原生 list，
    各消费侧按需拼接（如 "|" 拼正则、"," 拼命令行参数）。
    """
    if not USER_CONFIG_PATH.exists():
        return []
    with open(USER_CONFIG_PATH, "r", encoding="utf-8") as f:
        cfg = yaml.safe_load(f) or {}
    val = (cfg.get("filter") or {}).get("case_ids") or []
    if not isinstance(val, list):
        return []
    return [str(x).strip() for x in val if str(x).strip()]


def is_baseline_anchored() -> bool:
    """从 user-config.yaml.evolution_strategy.baseline_anchored 读取。

    优先级:env SKILLX_BASELINE_ANCHORED > yaml > False
    缺失时返回 False(保持"继承上轮最佳"行为,向后兼容)。
    """
    env_val = os.environ.get("SKILLX_BASELINE_ANCHORED", "").strip().lower()
    if env_val in ("1", "true", "yes", "on"):
        return True
    # 仅当 env 显式设为 false 类才返 False;空字符串("")=env 未设,应 fall through 走 yaml
    if env_val in ("0", "false", "no", "off"):
        return False
    if not USER_CONFIG_PATH.exists():
        return False
    try:
        with open(USER_CONFIG_PATH, "r", encoding="utf-8") as f:
            cfg = yaml.safe_load(f) or {}
        val = (cfg.get("evolution_strategy") or {}).get("baseline_anchored", False)
        return bool(val)
    except Exception:
        return False

# ──────────────────────────────────────────────────────────
# 共享基础设施函数（被多个子模块使用）
# ──────────────────────────────────────────────────────────

# 模块级 Hook 注册表（避免重复注册警告）
_hook_registry = None


def _get_hook_registry():
    """获取 Hook 注册表（单例模式）"""
    global _hook_registry
    if _hook_registry is None:
        _hook_registry = HookRegistry()
        _hook_registry.load_builtin_hooks()
    return _hook_registry


def _load_eval_env_from_dotenv() -> None:
    """从 .env 文件加载 SKILLX_* 等评测环境变量。

    模块加载时（orchestrator.py 顶部）已加载一次；此处再调一次用于防御性重载
    （如 CLI 参数变更或子模块独立调用时）。找不到 .env 时静默跳过。
    """
    for env_candidate in (Path(__file__).parent.parent / ".env", Path(__file__).parent / ".env"):
        if not env_candidate.exists():
            continue
        for raw_line in env_candidate.read_text(encoding="utf-8").splitlines():
            line = raw_line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, _, val = line.partition("=")
            key, val = key.strip(), val.strip()
            if key and val and (key not in os.environ or key.startswith("SKILLX_")):
                os.environ[key] = val
        break


def clean_eval_data_sandbox(
    base_dir: Path,
    stage: str = "unknown",
    extra_clean_dirs: Optional[List[Path]] = None,
) -> dict:
    """清理业务方评测 data/ 沙箱中除 data/ 目录本身外的全部内容。

    这是 skillx-alpha-agents 中清理业务方评测数据沙箱的唯一入口。
    编排器（baseline/candidate 评测前）和评测器（step 执行前）共用此函数，
    避免重复实现导致的逻辑漂移。

    设计原则（已废弃保留目录设计）：
    - 永远全清 data/ 下的所有子项，保证每次评测完全重新开始
    - 业务方评测管线自行重建其测试数据
    - 编排器不持有任何"保留目录"概念

    Args:
        base_dir: 业务方项目根目录（含 data/）
        stage: 阶段标识，用于日志

    Returns:
        摘要 dict: {
            "removed_dirs": [...],     # 已删除的目录
            "removed_files": [...],    # 已删除的文件
            "failed": [(name, err)]    # 失败项
        }
    """
    data_dir = base_dir / "data"
    if not data_dir.exists():
        return {"removed_dirs": [], "removed_files": [], "failed": []}

    removed_dirs, removed_files, failed = [], [], []
    for child in data_dir.iterdir():
        try:
            if child.is_dir() or child.is_symlink():
                shutil.rmtree(str(child))
                removed_dirs.append(child.name)
            else:
                child.unlink()
                removed_files.append(child.name)
        except Exception as e:
            failed.append((child.name, str(e)))

    print(
        f"    [{stage}] 🧹 清理 data/: 删 {len(removed_dirs)} 目录 {removed_dirs} | "
        f"删 {len(removed_files)} 文件 {removed_files} | "
        f"失败 {len(failed)} 项",
        flush=True,
    )
    summary: dict = {
        "removed_dirs": removed_dirs,
        "removed_files": removed_files,
        "failed": failed,
    }

    # 额外清理目录（list 直接传，避免 env 字符串 join/split 循环）
    for extra_dir in (extra_clean_dirs or []):
        if not extra_dir or extra_dir == data_dir:
            continue
        if not extra_dir.exists():
            print(f"    [{stage}] ⏭️  跳过不存在目录: {extra_dir}", flush=True)
            continue
        rd, rf, ff = [], [], []
        for child in extra_dir.iterdir():
            try:
                (shutil.rmtree(str(child)) if child.is_dir() or child.is_symlink() else child.unlink())
                (rd if child.is_dir() or child.is_symlink() else rf).append(child.name)
            except Exception as e:
                ff.append((child.name, str(e)))
        print(f"    [{stage}] 🧹 清理 {extra_dir}: 删 {len(rd)} 目录 {rd} | 删 {len(rf)} 文件 {rf} | 失败 {len(ff)} 项", flush=True)
        summary["removed_dirs"].extend(rd)
        summary["removed_files"].extend(rf)
        summary["failed"].extend(ff)

    return summary


# 优化阶段允许修改的文件/目录白名单
_ALLOWED_SKILL_FILES = {"SKILL.md"}
_ALLOWED_SKILL_DIRS = {"references", "scripts", "prompts", "templates"}


def _copy_back_whitelisted(tmp_skill_dir: Path, skill_dir: Path, round_num: int = 0) -> None:
    """
    将 /tmp 优化结果拷回 workspace，仅允许白名单内的文件/目录。

    白名单：
    - 文件：SKILL.md
    - 目录：references/, scripts/, prompts/
    - 其他文件/目录将被跳过并记录警告
    """
    logger = logging.getLogger(__name__)

    # 1. 白名单文件
    for fname in _ALLOWED_SKILL_FILES:
        src = tmp_skill_dir / fname
        if src.exists():
            shutil.copy2(str(src), str(skill_dir / fname))

    # 2. 白名单目录（覆盖式拷贝）
    for dname in _ALLOWED_SKILL_DIRS:
        src = tmp_skill_dir / dname
        if src.is_dir():
            dst = skill_dir / dname
            if dst.exists():
                shutil.rmtree(str(dst))
            shutil.copytree(str(src), str(dst))

    # 3. 非白名单条目：跳过并警告
    for item in sorted(tmp_skill_dir.iterdir()):
        if item.name.endswith(".proposed"):
            continue
        if item.name in _ALLOWED_SKILL_FILES:
            continue
        if item.is_dir() and item.name in _ALLOWED_SKILL_DIRS:
            continue
        logger.warning(f"  ⚠️ 跳过非白名单条目: {item.name}（优化结果未拷回）")


def _copy_sandbox_skill_back(sandbox_skill_dir: str, workspace_skill_dir: Path):
    """将沙箱中优化后的 Skill 目录拷回 workspace（白名单过滤）"""
    src = Path(sandbox_skill_dir)
    if not src.exists():
        return
    _copy_back_whitelisted(src, workspace_skill_dir)


def _find_gold_base_dir(workspace: Path, args) -> str:
    """查找 Gold 标准根目录。

    优先级：CLI 参数 > 环境变量 SKILLX_GOLD_DIR。
    """
    if getattr(args, 'gold_dir', ''):
        return args.gold_dir
    env_gold = os.environ.get("SKILLX_GOLD_DIR", "")
    if env_gold and Path(env_gold).exists():
        return env_gold
    if getattr(args, 'llm_judge_skill', ''):
        return args.llm_judge_skill
    return ""


def _build_ran_filter(workspace: Path, args) -> str:
    """从 case_ids 配置构建筛选正则。

    优先级：CLI 参数 > user-config.yaml filter.case_ids。
    未配置时返回空字符串（不过滤，全量跑）。
    """
    case_list = _resolve_case_ids(args)
    if case_list:
        return "|".join(case_list)
    return ""


def _resolve_case_ids(args) -> List[str]:
    """解析 case_ids 列表。

    优先级：CLI 参数 > user-config.yaml filter.case_ids。
    CLI 参数可能是 list 或 str（逗号分隔），统一归一为 list。
    """
    # 1) CLI 参数
    cli_ids = getattr(args, "case_ids", None) if args else None
    if cli_ids:
        if isinstance(cli_ids, list):
            return [str(x).strip() for x in cli_ids if str(x).strip()]
        return [x.strip() for x in str(cli_ids).split(",") if x.strip()]
    # 2) user-config.yaml
    return get_case_ids()


def _revert_to_best_skill(state_engine, best_round: int, current_round: int) -> None:
    """
    回退 Skill 到历史最佳轮次的版本。

    原理：best_skill/ 目录保存了历次评估后的最佳 Skill 副本（与 _restore_best_skill_to_original 同源）。
    回退时将 best_skill/ 完整拷回 workspace skill 目录；best_skill/ 缺失时兜底用 before_skill/。
    """
    workspace_skill_dir = state_engine.skill_dir

    best_skill_dir = state_engine.workspace / "best_skill"
    if not best_skill_dir.exists():
        print("  ⚠️ best_skill/ 不存在，无法回退")
        return

    if workspace_skill_dir.exists():
        shutil.rmtree(str(workspace_skill_dir))

    shutil.copytree(str(best_skill_dir), str(workspace_skill_dir))
    state_engine.skill_path = workspace_skill_dir / "SKILL.md"
    print(f"  ✅ 已从 best_skill/ 回退（来源: Round {best_round}）")

    if not state_engine.skill_path.exists():
        print("  ⚠️ best_skill/ 无 SKILL.md，尝试恢复 before 快照")
        before_dir = state_engine.artifact_store._ensure_round_dir(best_round) / f"round_{best_round}_before_skill"
        if before_dir.exists():
            shutil.rmtree(str(workspace_skill_dir))
            shutil.copytree(str(before_dir), str(workspace_skill_dir))
            state_engine.skill_path = workspace_skill_dir / "SKILL.md"
            print(f"  ✅ 已从 Round {best_round} before 快照回退")


def _load_user_config():
    """
    从 config/user-config.yaml 加载配置到环境变量。

    优先级：CLI 参数 > 系统环境变量 > user-config.yaml
    user-config.yaml 仅注入未设置的变量，不覆盖已有配置。
    同时支持 paths.root 根路径拼接派生 SKILLX_WORKSPACE / SKILLX_SANDBOX_ROOT。
    """
    import yaml

    scripts_dir = Path(__file__).parent.parent
    config_file = scripts_dir.parent / "config" / "evolve-user-config.yaml"
    if not config_file.exists():
        # 向后兼容旧文件名
        config_file = scripts_dir.parent / "config" / "user-config.yaml"
    if not config_file.exists():
        return

    loaded = {}

    try:
        with open(config_file, "r", encoding="utf-8") as f:
            cfg = yaml.safe_load(f) or {}

        # 1. 模型配置 → ANTHROPIC_* 环境变量
        model_cfg = cfg.get("model", {})
        for yaml_key, env_key in [
            ("name", "ANTHROPIC_MODEL"),
            ("base_url", "ANTHROPIC_BASE_URL"),
            ("api_key", "ANTHROPIC_API_KEY"),
        ]:
            val = model_cfg.get(yaml_key, "")
            if val and not os.environ.get(env_key):
                os.environ[env_key] = str(val)
                loaded[env_key] = val

        # 2. 路径配置 → SKILLX_ROOT 环境变量
        # need_cleaned_dir 是 list，由消费侧通过 get_need_cleaned_dirs() 直接从 user-config.yaml 读取，
        # 不再 join 成逗号串注入 env 变量（避免 join/split 字符串编码循环）
        paths_cfg = cfg.get("paths", {})
        val = paths_cfg.get("root")
        # 跳过 ${ENV_VAR} 占位符未解析（PyYAML 不展开 env-var），避免字面量被当作路径段
        if val and not os.environ.get("SKILLX_ROOT"):
            _val_str = str(val).strip()
            if _val_str and not (_val_str.startswith("${") and _val_str.endswith("}")):
                os.environ["SKILLX_ROOT"] = _val_str
                loaded["SKILLX_ROOT"] = val

    except Exception as e:
        print(f"  ⚠️ 加载 user-config.yaml 失败: {e}")
        return

    # 兜底：清理可能被旧版本污染的 ${ENV_VAR} 字面量 env（必须放在 try 外，无论加载成败都执行）
    for _ek in ("SKILLX_ROOT", "SKILLX_WORKSPACE_ROOT", "SKILLX_WORKSPACE", "SKILLX_SANDBOX_ROOT"):
        _ev = os.environ.get(_ek, "")
        if _ev.startswith("${") and _ev.endswith("}"):
            print(f"  🧹 清理污染的 {_ek}={_ev!r}（占位符未解析）")
            os.environ.pop(_ek, None)

    # SKILLX_ROOT 派生子路径
    root = os.environ.get("SKILLX_ROOT", "")
    if root:
        for sub_key, sub_path in [
            ("SKILLX_WORKSPACE", "evolution_workspace"),
            ("SKILLX_SANDBOX_ROOT", "sandbox"),
        ]:
            if not os.environ.get(sub_key):
                os.environ[sub_key] = str(Path(root) / sub_path)
                loaded[sub_key] = "<derived from SKILLX_ROOT>"

    # evidence_paths 段(LLM 评审规则、文件名 glob 等)透传给 LLM 子 Agent 用
    evidence_paths_cfg = cfg.get("evidence_paths", {}) or {}
    if evidence_paths_cfg:
        loaded["evidence_paths"] = evidence_paths_cfg

    if loaded:
        print(f"  📄 user-config.yaml 配置已加载: {len(loaded)} 项")

    return loaded


def populate_pipeline_in_config(config: dict, args) -> dict:
    """将 CLI 上的 pipeline 参数派生为 config["pipeline"] 字段。

    与原 generate_pipeline_config 的差异：
    - 不再生成独立的 pipeline-config.yaml
    - 写入调用方传入的 config["pipeline"]，由 StateEngine 统一持久化
    - 同步把 cleanup/archive 派生信息一并写入，使下游消费者拿到自包含 dict

    返回填充后的 pipeline dict（便于调用方直接 save）。
    """
    pipeline_eval_cmd = getattr(args, 'pipeline_eval_cmd', '') or ''
    pipeline_base_dir = getattr(args, 'pipeline_base_dir', '') or ''
    pipeline_config_path = getattr(args, 'pipeline_config', '') or ''

    # --pipeline-config(YAML)优先：直接解析整个 YAML 写入 config["pipeline"]
    # 修复：仅传 --pipeline-config 时原逻辑早返回，导致 config["pipeline"] 未填充，
    #      eval_pipeline 拿不到 pipeline_config_dict，EvaluatorFactory 返回空、评测失败。
    # 修复：YAML 优先级最高，即使同时传了 --pipeline-eval-cmd / --pipeline-base-dir ，
    #      只要 --pipeline-config 存在且有效，就用 YAML 里的 steps + base_dir，
    #      CLI 参数仅作为 eval_cmd 覆盖。
    if pipeline_config_path:
        from pathlib import Path as _P
        cfg_path = _P(pipeline_config_path)
        if not cfg_path.exists():
            print(f"  ⚠️ --pipeline-config 指向的文件不存在: {pipeline_config_path}")
        else:
            try:
                import yaml as _yaml
                text = cfg_path.read_text(encoding="utf-8")
                cfg = _yaml.safe_load(text) or {}
                pipeline_dict = cfg.get("pipeline", cfg) or {}
                # 同步 cleanup/archive 派生信息
                result_dirs = get_need_cleaned_dirs()
                pipeline_dict["result_extraction"] = pipeline_dict.get("result_extraction") or {}
                if result_dirs:
                    pipeline_dict["result_extraction"]["result_dirs"] = [str(p) for p in result_dirs]
                pipeline_dict.setdefault("archive", {"paths": ["data"]})
                # CLI 覆盖：--pipeline-eval-cmd 替换 YAML 里的 steps[0].command
                if pipeline_eval_cmd and pipeline_dict.get("steps"):
                    pipeline_dict["steps"][0]["command"] = pipeline_eval_cmd
                # CLI 覆盖：--pipeline-base-dir 替换 YAML 里的 base_dir
                if pipeline_base_dir:
                    pipeline_dict["base_dir"] = pipeline_base_dir
                config["pipeline"] = pipeline_dict
                print(f"  📋 已从 --pipeline-config 加载 pipeline 配置: base_dir={pipeline_dict.get('base_dir')}")
                return pipeline_dict
            except Exception as _e:
                print(f"  ⚠️ --pipeline-config 解析失败: {_e}")

    if not pipeline_eval_cmd and not pipeline_base_dir:
        return {}

    # 从 pipeline_eval_cmd 提取 --nodes 值作为 activities（如果有的话）
    activities = []
    if pipeline_eval_cmd:
        import re as _re
        _m = _re.search(r'--nodes\s+([^\s,]+)', pipeline_eval_cmd)
        if _m:
            activities = [_m.group(1)]

    # 步骤类型：默认 script（subprocess 真跑），可用 EVAL_TYPE=cosight_command 切回 LLM 模拟
    step_type = os.environ.get("EVAL_TYPE", "script").strip() or "script"

    # base_dir 优先级：
    # 1. CLI --pipeline-base-dir（最高）
    # 2. 从 pipeline_eval_cmd 的 `cd ... &&` 前缀提取（修复：slash command 执行目录）
    # 3. 默认 "."（项目根目录）
    base_dir = pipeline_base_dir
    if not base_dir and pipeline_eval_cmd:
        import re as _re
        _cd_match = _re.match(r'^cd\s+("[^"]+"|\'[^\']+\'|\S+)\s+&&\s+', pipeline_eval_cmd)
        if _cd_match:
            base_dir = _cd_match.group(1).strip('"\'')
    base_dir = base_dir or "."

    result_dirs = get_need_cleaned_dirs()
    result_dirs = [str(p) for p in result_dirs] if result_dirs else []

    pipeline_dict = {
        "base_dir": base_dir,
        "activities": activities,
        "steps": [
            {
                "name": "eval",
                "type": step_type,
                "command": pipeline_eval_cmd,
                "timeout": 0,
            }
        ]
        if pipeline_eval_cmd else [],
        "result_extraction": {
            "result_dirs": result_dirs,
        },
    }

    # 如果没有直接传入命令，从 pipeline_base_dir 推断默认步骤
    # 旧版曾尝试从 base 下的 yaml 候选文件读取 activities，已废弃：若需自定义命令
    # 请显式传 --pipeline-eval-cmd，或通过 SKILLX_ACTIVITY 环境变量注入。
    if not pipeline_eval_cmd and pipeline_base_dir:
        print(
            "  ⚠️ 已指定 --pipeline-base-dir 但未传 --pipeline-eval-cmd；"
            "将使用 config.json['pipeline'] 的空步骤配置，需外部注入评测命令。"
        )


    pipeline_dict["archive"] = {"paths": ["data"]}

    config["pipeline"] = pipeline_dict
    print(f"  📋 已将 pipeline 配置写入 config.json: base_dir={pipeline_dict['base_dir']}")
    return pipeline_dict


# ── 工作空间路径推断 ──────────────────────────────────────

def extract_sub_activity(args) -> Optional[str]:
    """从评测命令中提取 --sub-activity 参数值。"""
    import re
    pipeline_eval_cmd = getattr(args, 'pipeline_eval_cmd', '') or ''
    if pipeline_eval_cmd:
        m = re.search(r'--sub-activity\s+([^\s]+)', pipeline_eval_cmd)
        if m:
            return m.group(1)
    return None


def infer_evolution_workspace(agent_dir: Path, agent_name: Optional[str] = None) -> Path:
    """
    推断演化任务工作目录，避免污染 Agent 自身目录。

    结构：{root}/evolution_workspace/
    （taskid 子目录直接在 evolution_workspace 下创建，不再插 agent_name 中间层）

    {root} 优先级链：
    1. SKILLX_WORKSPACE_ROOT 环境变量（推荐显式设置）
    2. SKILLX_ROOT 环境变量
    3. agent_dir.parent.parent
    4. **skillx-alpha-agents 工程根的父目录**（=/media/vdb/skillx-alpha）
       （兜底：业务 skill 多在 skillx-alpha 子树里，避免落在 /media 这种过浅路径）

    agent_name 参数仅用于日志/报告，不影响路径推断。
    """
    root_str = os.environ.get("SKILLX_WORKSPACE_ROOT", "") or os.environ.get("SKILLX_ROOT", "")
    # 拒绝 ${ENV_VAR} 未解析字面量作为 root（PyYAML 不展开 env-var），避免字面量被当作路径段拼接
    _root_is_placeholder = root_str.startswith("${") and root_str.endswith("}")
    if root_str and not _root_is_placeholder:
        root = Path(root_str).resolve()
    else:
        # 工程根的父目录（skillx-alpha-agents → /media/vdb/skillx-alpha）
        skillx_alpha_root = Path(__file__).resolve().parent.parent.parent.parent
        root = skillx_alpha_root

    ws = root / "evolution_workspace"
    ws.mkdir(parents=True, exist_ok=True)
    return ws


def resolve_workspace_with_taskid(base_workspace: Path, mode: str = "evolve") -> Path:
    """
    在 evolution_workspace 下解析 taskid 子目录。

    每次运行默认创建新 taskid 目录，避免产物覆盖。
    如需复用已存在的 taskid 目录，需显式将其完整路径作为 --workspace 传入。

    Args:
        base_workspace: evolution_workspace 根目录（不含 taskid）
        mode: 运行模式，决定 taskid 前缀
            - "evolve":   taskid_YYYYMMDD_HHMMSS（/skill_evolve 评测驱动模式，默认）
            - "optimize": skill_optimize_taskid_YYYYMMDD_HHMMSS（/skill_optimize 静态模式）

    Returns:
        taskid 子目录路径
    """
    import re as _re
    from datetime import datetime

    # mode → taskid 前缀 + 显式传入时允许的目录名正则
    if mode == "optimize":
        prefix = "skill_optimize_taskid_"
        # static 模式仅允许新格式（无历史 taskid 目录）
        user_pattern = r"^skill_optimize_taskid_\d{8}_\d{6}$"
    elif mode == "refactor":
        # refactor 模式:接受任何 skill_refactor_* 前缀的目录名(时间戳/自定义),
        # 都视为合法的 taskid,直接 mkdir 复用,避免嵌套
        prefix = "skill_refactor_taskid_"
        user_pattern = r"^skill_refactor_.+$"
    else:
        # evolve 模式：兼容两种命名（旧的 taskid_xxx 和新的 skill_evolve_taskid_xxx）
        prefix = "skill_evolve_taskid_"
        user_pattern = r"^(?:skill_evolve_)?taskid_\d{8}_\d{6}$"

    # 如果用户已经指定了 taskid 目录，直接返回
    if _re.match(user_pattern, base_workspace.name):
        base_workspace.mkdir(parents=True, exist_ok=True)
        return base_workspace

    # 创建新 taskid 子目录
    taskid = datetime.now().strftime(f"{prefix}%Y%m%d_%H%M%S")
    task_dir = base_workspace / taskid
    # 如果同名已存在（同一秒内多次调用），追加计数器
    if task_dir.exists():
        counter = 1
        while (base_workspace / f"{taskid}_{counter:02d}").exists():
            counter += 1
        task_dir = base_workspace / f"{taskid}_{counter:02d}"

    task_dir.mkdir(parents=True, exist_ok=True)
    return task_dir


# ── 架构约束：产物禁止污染工程自身 ──────────────────────

_PROJECT_ROOT: Optional[Path] = None
_SCRIPTS_DIR = Path(__file__).parent.parent  # scripts/


def get_project_root() -> Path:
    """
    返回当前工程的根目录。

    基于 orchestrator.py 的位置推断：scripts/orchestrator.py → 父目录即工程根。
    结果会被缓存，避免重复计算。
    """
    global _PROJECT_ROOT
    if _PROJECT_ROOT is None:
        _PROJECT_ROOT = _SCRIPTS_DIR.parent.resolve()
    return _PROJECT_ROOT


def is_inside_project(path: Path, project_root: Path) -> bool:
    """判断 path 是否位于工程目录内（等于或其子目录）"""
    try:
        path.relative_to(project_root)
        return True
    except ValueError:
        return False


def enforce_evolution_workspace(args) -> Path:
    """
    架构级约束：确保优化产物永远不写在 skillx-alpha-agents工程目录内。

    如果 workspace 指向工程目录或其子目录，自动重定向到
    {project_root.parent}/evolution_workspace/（无 agent_name 中间层）。
    """
    workspace = Path(args.workspace).resolve()
    project_root = get_project_root()

    if is_inside_project(workspace, project_root):
        base_dir = project_root.parent  # skillx-alpha/
        correct_ws = base_dir / "evolution_workspace"
        correct_ws.mkdir(parents=True, exist_ok=True)

        print("\n  ⛔ 工作区位于工程目录内，自动重定向（架构约束）")
        print(f"     原始: {workspace}")
        print(f"     工程: {project_root}")
        print(f"     → 重定向到: {correct_ws}\n")

        args.workspace = correct_ws
        return correct_ws

    return workspace


def setup_eval_env(args):
    """配置评测环境：应用 API 参数到环境变量。"""
    from evaluators.api_config import apply_env_from_args
    apply_env_from_args(args)


def find_agent_dir(skill_path: Path) -> Optional[Path]:
    """从 skill 路径向上查找 Agent 级别的  目录。

    判断标准（按优先级）：
    1.  下包含 skills/ 或 agents/ 或 hooks/
    2.  的父目录不是 skills/（排除 skill 内部的 ）
    3. **不**是 skillx-alpha-agents 工程自身（用框架特征文件识别：orchestrators/ + scripts/optimizers/）

    Args:
        skill_path: SKILL.md 或其所在目录的路径

    Returns:
        Agent 目录路径，未找到返回 None
    """
    p = skill_path
    while p != p.parent:
        cosight_dir = p / "."
        if cosight_dir.is_dir():
            has_skills = (cosight_dir / "skills").is_dir()
            has_agents = (cosight_dir / "agents").is_dir()
            has_hooks = (cosight_dir / "hooks").is_dir()
            is_skill_internal = (p.parent.name == "skills")
            # 跳过 skillx-alpha-agents 工程自身：含 scripts/orchestrators 标识
            # 这种目录是「业务汇总根」或工程工作区，不是真正的业务 agent
            is_framework_or_business_root = (
                (p / "scripts" / "orchestrators").is_dir()
                or (p / "scripts" / "optimizers").is_dir()
            )
            if (has_skills or has_agents or has_hooks) and not is_skill_internal and not is_framework_or_business_root:
                return p
        p = p.parent
    return None


def resolve_skill_path(path: Path) -> Path:
    """将 skill-path 解析为 SKILL.md 文件路径。

    - 传入文件：直接返回
    - 传入目录：自动定位 `{dir}/SKILL.md`
    """
    if path.is_file():
        return path
    if path.is_dir():
        skill_file = path / "SKILL.md"
        if skill_file.is_file():
            return skill_file
    return path


def setup_workspace(args):
    """配置工作区路径 + 架构约束 + taskid 解析。

    标准初始化顺序：
    1. 提取评测命令 → 提取 --sub_activity（仅用于元数据，不影响路径）
    2. 使用 {SKILLX_WORKSPACE 基础目录}/{taskid} 建立 task 路径（无 agent_name 中间层）
    3. 后续写入 config.json + progress.json → 拷贝 skill → 基线评测
    """
    # 加载 .env 文件（兼容 SKILLX_* 显式注入）+ user-config.yaml（paths.root 派生 SKILLX_ROOT）
    _load_eval_env_from_dotenv()
    _load_user_config()

    # 转换路径为 Path 对象
    if args.skill_path:
        args.skill_path = Path(args.skill_path)
        args.skill_path = resolve_skill_path(args.skill_path)

    # 提取 sub_activity（仅用于报告标题等元数据，不再用于路径推断）
    sub_activity = extract_sub_activity(args)

    if args.workspace:
        # 用户显式指定完整路径（如 --workspace /path/to/evolution_workspace）
        args.workspace = Path(args.workspace).resolve()
    elif os.environ.get("SKILLX_WORKSPACE"):
        # SKILLX_WORKSPACE 是基础目录（如 /path/to/evolution_workspace），
        # taskid 子目录直接在它下面创建，不插 agent/sub_activity 中间层
        _skx_ws_str = os.environ["SKILLX_WORKSPACE"]
        if _skx_ws_str.startswith("${") and _skx_ws_str.endswith("}"):
            # 占位符未解析（PyYAML 不展开 env-var），拒绝使用，fallback 到自动推断
            print(f"  ⚠️ SKILLX_WORKSPACE={_skx_ws_str!r} 是占位符字面量,拒绝使用,改用自动推断")
            args.workspace = infer_evolution_workspace(args.skill_path and Path(args.skill_path).parent)
        else:
            base_ws = Path(_skx_ws_str).resolve()
            args.workspace = base_ws
        args.workspace.mkdir(parents=True, exist_ok=True)
    elif args.skill_path:
        # 自动推断：从 skill 路径向上查找 Agent 目录
        agent_dir = find_agent_dir(args.skill_path.parent)
        if agent_dir:
            args.workspace = infer_evolution_workspace(agent_dir, agent_name=sub_activity)
        else:
            fallback_dir = args.skill_path.parent
            args.workspace = infer_evolution_workspace(fallback_dir, agent_name=sub_activity)
    elif getattr(args, 'skill_paths', None):
        # Agent 模式：从第一个 skill 路径推断 workspace
        from orchestrators.skill_manager import parse_skill_paths
        skill_path_list = parse_skill_paths(args.skill_paths)
        if skill_path_list:
            first_skill_path = Path(skill_path_list[0])
            agent_dir = find_agent_dir(first_skill_path.parent)
            if agent_dir:
                args.workspace = infer_evolution_workspace(agent_dir, agent_name=sub_activity)
            else:
                fallback_dir = first_skill_path.parent
                args.workspace = infer_evolution_workspace(fallback_dir, agent_name=sub_activity)

    # 架构约束：产物禁止污染工程自身
    if args.workspace:
        ws_from_env = os.environ.get("SKILLX_WORKSPACE", "")
        if not ws_from_env or Path(ws_from_env).resolve() != Path(args.workspace).resolve():
            enforce_evolution_workspace(args)

    # 解析 taskid 子目录
    if args.workspace:
        old_ws = args.workspace
        # mode 决定 taskid 前缀
        # argparse 取值是 "eval" / "static" / "refactor"，映射到 resolve_workspace_with_taskid 的 mode 参数
        # - eval    → skill_evolve_taskid_xxx（兼容旧 taskid_xxx 命名）
        # - static  → skill_optimize_taskid_xxx
        # - refactor → skill_refactor_taskid_xxx
        raw_mode = getattr(args, "mode", "eval") or "eval"
        if raw_mode == "static":
            mode = "optimize"
        elif raw_mode in ("refactor", "refactor-diff-report", "refactor-self-check"):
            # refactor-diff-report / refactor-self-check 与 refactor 共用 refactor 前缀(同一 workspace)
            mode = "refactor"
        else:
            mode = "evolve"
        args.workspace = resolve_workspace_with_taskid(args.workspace, mode=mode)
        if args.workspace != old_ws:
            print(f"  📋 任务 ID: {args.workspace.name}")
        print(f"  📂 工作区: {args.workspace}")

        # 暴露当前任务工作区给子模块（tools.Agent 用它定位 _debug 落盘目录）
        os.environ["SKILLX_CURRENT_TASK_DIR"] = str(args.workspace)

        # 落盘 session_start 标记：一眼确认 _debug 子 Agent 日志机制已开启
        try:
            import time as _t
            _debug_dir = Path(args.workspace) / "_debug"
            _debug_dir.mkdir(parents=True, exist_ok=True)
            _session_log = _debug_dir / "session_start.log"
            with _session_log.open("a", encoding="utf-8") as _fp:
                _fp.write(f"\n{'='*60}\n")
                _fp.write(f"# session_start : {_t.strftime('%Y-%m-%d %H:%M:%S')}\n")
                _fp.write(f"# task_dir      : {args.workspace}\n")
                _fp.write(f"# pid           : {os.getpid()}\n")
                _fp.write(f"# skill_target  : {getattr(args, 'target_skill', '')}\n")
                _fp.write(f"# max_rounds    : {getattr(args, 'max_rounds', '')}\n")
                _fp.write(f"# candidates    : {getattr(args, 'candidates_per_round', '')}\n")
                _fp.write(f"# eval_runs     : {getattr(args, 'eval_runs_per_candidate', '')}\n")
                _fp.write(f"# mode          : {getattr(args, 'optimization_mode', 'single')}\n")
                _fp.write(f"# _debug 目录   : {_debug_dir}\n")
                _fp.write("# 子 Agent 日志 : 所有 Agent() 调用会写入本目录 agent_*.txt\n")
                _fp.write(f"{'='*60}\n")
            print(f"  📝 session_start 标记已落盘: {_session_log}")
        except Exception as _e:
            print(f"  ⚠️ session_start 落盘失败(非致命): {_e}")




def _find_invalid_evidence_paths(score_json: Path) -> list:
    """读 score.json,返回指向不存在文件的 gold/llm 路径清单(ExtractionAgent 可修正)。

    trace 缺失是评测产物问题(重跑也拿不到),不在本校验范围。
    校验失败/无 score.json → 空清单(不阻塞)。
    """
    invalid: list = []
    if not score_json.exists():
        return invalid
    import json as _json
    try:
        data = _json.loads(score_json.read_text(encoding="utf-8"))
    except Exception:
        return invalid
    info = data.get("info", {}) or {}
    for label in ("gold_per_case", "llm_output_per_case"):
        for cid, p in (info.get(label) or {}).items():
            if p and not Path(str(p)).exists():
                invalid.append(f"{label}:{cid}")
    return invalid


def _analyze_run_with_evidence_retry(
    analyzer, run_dir, round_num, candidate_id, run_index, case_ids=None
):
    """analyze_run + score.json 证据路径校验,失效则 force 重跑一次 ExtractionAgent。

    gold/llm 路径指向不存在的文件 = ExtractionAgent 未 ls 探查实际文件就填了约定路径
    (实测 R_用户需求分析.md 失效,实际产物是全量_用户需求分析.md)。
    → force=True 重跑一次(重新做两步 LLM 探查),让 score.json 自身正确;
      重跑后仍失效 → 放弃,渲染层 glob 兜底(_fix_evidence_paths)处理展示。
    """
    import logging
    log = logging.getLogger(__name__)
    rs = analyzer.analyze_run(
        run_dir, round_num, candidate_id, run_index, case_ids=case_ids
    )
    invalid = _find_invalid_evidence_paths(run_dir / "score.json")
    if not invalid:
        return rs
    log.warning("score.json 证据路径失效(%s),force 重跑 ExtractionAgent", ", ".join(invalid))
    print(f"  ⚠️ [路径自查] score.json 证据路径失效({', '.join(invalid)}),force 重跑 ExtractionAgent 修正")
    # 把上次失效路径注入重试 prompt(analyze_run 的 _analyze_with_agent 读取该 env),
    # 让 LLM 明确知道上次填错,本次必须先 ls 探查实际文件。用完必须清除,防污染后续调用。
    import os as _os
    rs2 = None
    try:
        _os.environ["SKILLX_EVIDENCE_RETRY_HINT"] = ", ".join(invalid)
        rs2 = analyzer.analyze_run(
            run_dir, round_num, candidate_id, run_index, case_ids=case_ids, force=True
        )
    finally:
        _os.environ.pop("SKILLX_EVIDENCE_RETRY_HINT", None)
    still = _find_invalid_evidence_paths(run_dir / "score.json")
    if still:
        log.warning("重跑后证据路径仍失效(%s),放弃(渲染层 glob 兜底)", ", ".join(still))
        print(f"  ⚠️ [路径自查] 重跑后仍失效({', '.join(still)}),放弃修正(渲染层 glob 兜底)")
    return rs2


def _sync_skill_to_eval_agents(agent_dir: Path) -> None:
    """评测前把 workspace skill(优化后)同步到评测 agent 目录 `skills/`。

    核心 bug 修复:评测命令(sdd_eval_parallel → run_batch)用固定的评测 agent 目录
    (如 需求分析Agent),从其 `skills/` 读 skill —— 若不把 workspace 优化后的
    skill 同步过去,评测永远测初始 skill,优化不体现在分数。

    实现:
    - 评测 agent 目录从 user-config `need_cleaned_dir` 里含 `{X}Agent/changes` 的路径派生
      (父目录 = agent 根,`skills/` = skill 位置)
    - 覆盖前把初始 skill 备份到 `{name}.bak`(若未备份)——用户确认直接改,因有 .bak
    - 再把 workspace `skill/{name}/` 拷贝覆盖到 agent 的 `skills/{name}/`
    """
    import shutil as _sh

    from orchestrators.workspace import get_need_cleaned_dirs

    skills_root = Path(agent_dir) / "skill"
    if not skills_root.is_dir():
        return
    skill_dirs = {sd.name: sd for sd in skills_root.iterdir() if sd.is_dir()}
    if not skill_dirs:
        return

    synced = 0
    for nd in get_need_cleaned_dirs():
        if nd.name != "changes" or not nd.parent.name.endswith("Agent"):
            continue
        agent_root = nd.parent
        skills_dir = agent_root / "." / "skills"
        if not skills_dir.is_dir():
            continue
        for name, src in skill_dirs.items():
            dest = skills_dir / name
            bak = skills_dir / f"{name}.bak"
            # 只在 agent 原本有该 skill(或 .bak)时才同步 —— 避免把本活动 skill 污染到其他 Agent
            if not dest.exists() and not bak.exists():
                continue
            try:
                if dest.exists() and not bak.exists():
                    _sh.copytree(str(dest), str(bak))  # 备份初始 skill(仅首次)
                if dest.exists():
                    _sh.rmtree(str(dest))
                _sh.copytree(str(src), str(dest))
                synced += 1
                print(f"  🔄 同步 skill [{name}] → 评测 agent {agent_root.name}/skills/(优化后)")
            except Exception as e:
                print(f"  ⚠️ 同步 skill [{name}] → {agent_root.name} 失败: {e}")
    if synced:
        print(f"  🔄 评测前已同步 {synced} 个优化后 skill 到评测 agent 目录")
