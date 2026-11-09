"""配置三层加载：user-config → framework YAMLs（jinja2 渲染）。

设计目标
========
- 业务方只维护 `config/user-config.yaml` 一个文件（业务专属配置）。
- framework YAML（`framework_configs/eval-config.yaml` /
  `framework_configs/proposal-agent-config.yaml`）由 framework 维护者管，
  业务方**0 接触**。framework YAML 内的 `{{ user.xxx }}` 占位符在加载时
  被 user_config 渲染成具体值。
- 不引入 deep_merge 等隐式合并；纯 jinja2 渲染，行为可预测。
- 旧字段（proposal-agent-config.yaml 的 `execution_traces` /
  `failure_statistics` / `focus_blocks` / `gap_extractors`）在 deprecation
  期间仍生效，但启动时打 WARN 提示迁移路径；下个 major 版本再删除。

加载顺序
========
1. user-config.yaml：CLI `--user-config` > env `SKILLX_USER_CONFIG` > 默认
   `config/user-config.yaml`（不存在时返回 {}，不抛错）。
2. framework YAML：用 user_config 作为 jinja2 上下文渲染 `{{ user.xxx }}`。
3. 调用方拿到**已渲染**的 dict，正常使用即可。

失败策略
========
- jinja2 渲染单字符串失败 → 返回原字符串 + 控制台 WARN（不抛错，让 framework
  走 fallback 路径继续工作）。
- 列表/dict 渲染异常 → 跳过该条目 + WARN。
- 整个 YAML 不存在 → 返回 {}（让 framework 用代码兜底）。
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any, Dict, Optional

import yaml

# ── 默认路径 ──────────────────────────────────────────────────────────
# 业务方唯一配置入口:config/evolve-user-config.yaml
DEFAULT_USER_CONFIG_PATH = (
    Path(__file__).resolve().parent.parent / "config" / "evolve-user-config.yaml"
)

# framework YAML 只读模板（由 framework 维护者管，业务方勿动）
DEFAULT_FRAMEWORK_CONFIG_DIR = (
    Path(__file__).resolve().parent.parent / "framework_configs"
)

# framework YAML 默认文件名
FRAMEWORK_EVAL_CONFIG_NAME = "eval-config.yaml"
FRAMEWORK_PROPOSAL_CONFIG_NAME = "proposal-agent-config.yaml"


# ── YAML / jinja2 渲染底层 ────────────────────────────────────────────

def _load_yaml(path: Path) -> Dict[str, Any]:
    """加载 YAML 文件为 dict，失败/不存在返回 {}。"""
    if not path.exists():
        return {}
    try:
        with open(path, encoding="utf-8") as f:
            data = yaml.safe_load(f)
        return data if isinstance(data, dict) else {}
    except Exception as e:
        print(f"  [ConfigLayered] 加载 YAML 失败 ({path}): {type(e).__name__}: {e}")
        return {}


def _resolve_user_ref(ref: str, user_cfg: Dict[str, Any]) -> Any:
    """解析 `a.b.c` 形式的 user_cfg 引用路径。

    例：ref='extraction_hints.task_description' → user_cfg['extraction_hints']['task_description']
    找不到时返回 ''（保留 framework YAML 的可读性，调用方拿到空串走 fallback）。
    """
    cur: Any = user_cfg
    for part in ref.split("."):
        if isinstance(cur, dict) and part in cur:
            cur = cur[part]
        else:
            return ""
    return cur


def _render_jinja2_string(template: str, user_cfg: Dict[str, Any]) -> Any:
    """单字符串渲染：识别 `{{ user.xxx.yyy }}` 形式的引用并替换为 user_cfg 的值。

    **为什么不用 jinja2**：
    framework YAML 里有运行时占位符（如 `{data_dir}` / `{case_ids}` / `{lang}`），
    jinja2 会把 `{` 视为模板语法；且 YAML 中的反引号、注释等在 jinja2 中可能报错。
    自实现一个轻量替换器只处理 `{{ user.xxx }}` 引用，规避这些冲突。

    **返回值类型**：返回**原值类型**（dict / list / str / 数字），
    不是强制 str()。这样 `{{ user.execution_traces }}` 返回完整 dict 而非字符串 repr。

    失败时：返回原字符串 + WARN（让 framework 走 fallback 路径继续工作）。
    """
    if not isinstance(template, str):
        return template
    if "{{" not in template:
        return template

    import re
    pattern = re.compile(r"\{\{\s*user\.([a-zA-Z0-9_.]+)\s*\}\}")

    # 处理逻辑：找到所有 {{ user.xxx }} 引用，逐段拼接
    # - 如果整个字符串就是单个 {{ user.xxx }} 引用 → 直接返回 value（保留原类型）
    # - 否则作为字符串插入位置 → 强制 str() 转换
    parts = []
    last_end = 0
    single_match: Any = None
    single_match_obj: Optional[re.Match] = None
    for m in pattern.finditer(template):
        if single_match_obj is None:
            single_match_obj = m
        else:
            single_match_obj = False  # 多个匹配,只能走字符串拼接
        if last_end < m.start():
            parts.append(template[last_end:m.start()])
        ref = m.group(1)
        value = _resolve_user_ref(ref, user_cfg)
        if value == "":
            print(f"  [ConfigLayered] user.{ref} 未在 user-config 中定义，渲染为空串")
        parts.append(value)
        last_end = m.end()

    # 整个字符串就一个 {{ user.xxx }} 引用 → 直接返回原值（保留类型）
    if single_match_obj is not False and single_match_obj is not None \
            and last_end == len(template) and last_end != 0:
        # 确认整个 template 就是这一个引用（前面没有静态前缀）
        if single_match_obj.start() == 0:
            return parts[0]  # 返回原值类型（dict / list / str 等）

    # 多引用或带静态前缀 → 走字符串拼接
    if last_end < len(template):
        parts.append(template[last_end:])
    return "".join(str(p) for p in parts)


def _deep_render(obj: Any, user_cfg: Dict[str, Any]) -> Any:
    """递归渲染 dict / list / str 中的 jinja2 占位符。

    数值/布尔/None 原样返回。
    list 渲染失败时返回空 list（不抛错，让 framework 兜底）。
    """
    if isinstance(obj, dict):
        rendered: Dict[str, Any] = {}
        for k, v in obj.items():
            try:
                rendered[k] = _deep_render(v, user_cfg)
            except Exception as e:
                print(f"  [ConfigLayered] 跳过 dict['{k}'] 渲染: {type(e).__name__}: {e}")
        return rendered
    if isinstance(obj, list):
        result = []
        for idx, item in enumerate(obj):
            try:
                result.append(_deep_render(item, user_cfg))
            except Exception as e:
                print(f"  [ConfigLayered] 跳过 list[{idx}] 渲染: {type(e).__name__}: {e}")
        return result
    if isinstance(obj, str):
        return _render_jinja2_string(obj, user_cfg)
    return obj


# ── 公开 API ──────────────────────────────────────────────────────────

def load_user_config(path: Optional[Path] = None) -> Dict[str, Any]:
    """加载业务方配置（`config/evolve-user-config.yaml`）。

    优先级:参数 > 环境变量 `SKILLX_USER_CONFIG` > 默认 `evolve-user-config.yaml`。

    返回 dict，文件不存在时返回 {}（不抛错，让 framework 用代码兜底）。
    """
    if path is not None:
        p = Path(path)
    else:
        env_path = os.environ.get("SKILLX_USER_CONFIG", "").strip()
        p = Path(env_path) if env_path else DEFAULT_USER_CONFIG_PATH
    cfg = _load_yaml(p)
    if not cfg and p != DEFAULT_USER_CONFIG_PATH:
        # CLI 显式指定了 user-config 但加载失败/为空 — 提示
        print(f"  [ConfigLayered] 指定的 user-config 为空或加载失败: {p}")
    elif cfg and p != DEFAULT_USER_CONFIG_PATH:
        print(f"  [ConfigLayered] 使用 user-config: {p}")
    return cfg


def _resolve_framework_path(name: str, explicit: Optional[Path] = None) -> Path:
    """解析 framework YAML 路径。

    优先级：参数 > 环境变量 `SKILLX_FRAMEWORK_CONFIG_DIR` 下的 `{name}`
    > 默认 `framework_configs/{name}`。
    """
    if explicit is not None:
        return Path(explicit)
    env_dir = os.environ.get("SKILLX_FRAMEWORK_CONFIG_DIR", "").strip()
    if env_dir:
        return Path(env_dir) / name
    return DEFAULT_FRAMEWORK_CONFIG_DIR / name


def _warn_deprecated_fields(
    framework: Dict[str, Any], user_cfg: Dict[str, Any], framework_name: str
) -> None:
    """如果 framework YAML 含旧业务字段且 user_cfg 未覆盖，打 WARN 提示迁移。

    只在 framework YAML 里的值是**实际业务数据**（非 jinja2 引用）时触发。
    因为新版 framework YAML 业务字段已改为 `{{ user.xxx }}` 引用，值不是
    字符串 `"{{ user.xxx }}"` 模板时才认为是旧版硬编码。

    **当前 design**：framework YAML 已自给自足（focus_blocks / gap_extractors /
    failure_classify_threshold / min_runs_for_determinism 都是 framework 自带默认），
    业务方只通过 user-config 的 2 段自然语言描述业务布局，没有需要 deprecation 警告的
    旧字段。deprecation_map 留空，函数变为 no-op，下个 major 版本如需重新启用可还原。
    """
    return  # 业务方只读 user-config.yaml，framework YAML 不再有业务字段需要迁移


def load_framework_config_with_user(
    framework_name: str,
    user_cfg: Optional[Dict[str, Any]] = None,
    framework_path: Optional[Path] = None,
) -> Dict[str, Any]:
    """加载 framework YAML 并用 user_cfg 渲染 `{{ user.xxx }}` 占位符。

    Args:
        framework_name: 'eval' 或 'proposal-agent'
        user_cfg: load_user_config() 返回的 dict；传 None 时自动 load
        framework_path: 显式指定 framework YAML 路径（调试用）

    Returns:
        已渲染的 dict；文件不存在/为空时返回 {}
    """
    if user_cfg is None:
        user_cfg = load_user_config()

    if framework_name == "eval":
        name = FRAMEWORK_EVAL_CONFIG_NAME
    elif framework_name == "proposal-agent":
        name = FRAMEWORK_PROPOSAL_CONFIG_NAME
    else:
        raise ValueError(f"未知的 framework_name: {framework_name!r}，仅支持 'eval' / 'proposal-agent'")

    path = _resolve_framework_path(name, framework_path)
    framework = _load_yaml(path)
    if not framework:
        return {}

    # deprecation 检查（仅在 framework_name=='proposal-agent' 时有效）
    _warn_deprecated_fields(framework, user_cfg, framework_name)

    # 递归 jinja2 渲染
    rendered = _deep_render(framework, user_cfg)
    return rendered  # type: ignore[return-value]


# ── 兼容层：旧 API 包装 ────────────────────────────────────────────────

def load_framework_config_legacy(
    framework_name: str,
    user_cfg: Optional[Dict[str, Any]] = None,
    framework_path: Optional[Path] = None,
) -> Dict[str, Any]:
    """兼容旧调用方的"无 user 注入"加载模式（纯 YAML 加载，无 jinja2 渲染）。

    主要给 metrics.config.from_yaml 之类的"还没接 user_cfg"的代码兜底。
    仍然走同一路径解析，但不做 jinja2 渲染（旧行为）。
    """
    if user_cfg is None:
        user_cfg = load_user_config()
    if framework_name == "eval":
        name = FRAMEWORK_EVAL_CONFIG_NAME
    elif framework_name == "proposal-agent":
        name = FRAMEWORK_PROPOSAL_CONFIG_NAME
    else:
        raise ValueError(f"未知的 framework_name: {framework_name!r}")
    path = _resolve_framework_path(name, framework_path)
    return _load_yaml(path)


__all__ = [
    "DEFAULT_USER_CONFIG_PATH",
    "DEFAULT_FRAMEWORK_CONFIG_DIR",
    "FRAMEWORK_EVAL_CONFIG_NAME",
    "FRAMEWORK_PROPOSAL_CONFIG_NAME",
    "load_user_config",
    "load_framework_config_with_user",
    "load_framework_config_legacy",
]


if __name__ == "__main__":
    # 简单自检：python3 scripts/config_layered.py
    user = load_user_config()
    print(f"user-config 字段: {sorted(user.keys())}")
    for name in ("eval", "proposal-agent"):
        rendered = load_framework_config_with_user(name, user)
        print(f"  framework {name}: {len(rendered)} 顶层字段")
