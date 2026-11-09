"""
API 配置模块
===========
统一管理 API 端点、密钥和模型配置。

模型架构：
- 模型统一由 ANTHROPIC_MODEL / COSIGHT_MODEL 控制（子代理直接读取）
- [已废弃] SKILLX_MODEL / SKILLX_EVAL_MODEL — 冗余变量，仅保留为向后兼容的 fallback

优先级：CLI 参数 > ANTHROPIC_* 环境变量 > SKILLX_* 兼容 fallback > 硬编码默认值

环境变量：
  SKILLX_API_BASE      - 全局 API 端点地址
  SKILLX_API_KEY       - 全局 API 密钥
  ANTHROPIC_MODEL      - 全局默认模型名（优先使用）
  COSIGHT_MODEL         - cosight 默认模型名（兼容）
  SKILLX_MODEL         - 兼容旧配置（作为最后 fallback）
  [已废弃] SKILLX_EVAL_MODEL    - 评测专用模型名（冗余）
  [已废弃] SKILLX_EVAL_API_BASE - 评测专用 API 端点（冗余）
  [已废弃] SKILLX_EVAL_API_KEY  - 评测专用 API 密钥（冗余）
"""

import os

# 硬编码默认值（最后兜底，仅当所有环境变量均未设置时使用）
_DEFAULT_API_BASE = ""
_DEFAULT_API_KEY = ""
_DEFAULT_MODEL = ""


def _resolve_global_model() -> dict:
    """
    检测用户全局模型配置（ANTHROPIC_* 环境变量）。
    返回 {"api_base": ..., "api_key": ..., "model": ...}，未配置时返回空 dict。
    """
    base = os.environ.get("ANTHROPIC_BASE_URL", "").strip()
    model = os.environ.get("ANTHROPIC_MODEL", "").strip()
    key = (os.environ.get("ANTHROPIC_API_KEY", "").strip()
           or os.environ.get("ANTHROPIC_AUTH_TOKEN", "").strip())
    if base and model:
        return {"api_base": base, "api_key": key, "model": model}
    return {}


def get_api_config(args=None, model_override=None):
    """
    获取全局 API 配置（用于优化/分析阶段）

    优先级（从高到低）：
    1. CLI 参数（--api-base, --api-key, --model-reasoning）
    2. SKILLX_* 环境变量
    3. ANTHROPIC_* 环境变量（用户全局 cosight 配置）

    不再设置硬编码默认值。

    Args:
        args: 命令行参数对象（可选），可包含 api_base, api_key 属性
        model_override: 模型名覆盖（可选），优先级高于 args.model_reasoning

    Returns:
        dict: {"api_base": ..., "api_key": ..., "model": ...}
    """
    # 检测全局模型配置（ANTHROPIC_*），作为 SKILLX_* 之后的首选兜底
    _global = _resolve_global_model()

    # 逐级读取环境变量，不设硬编码默认值
    api_base = os.environ.get("SKILLX_API_BASE") or _global.get("api_base") or ""
    api_key = os.environ.get("SKILLX_API_KEY") or _global.get("api_key") or os.environ.get("DEEPSEEK_API_KEY") or ""
    model = os.environ.get("ANTHROPIC_MODEL") or _global.get("model") or os.environ.get("COSIGHT_MODEL") or os.environ.get("SKILLX_MODEL", "")

    # CLI 参数覆盖（最高优先级）
    if args is not None:
        if getattr(args, 'api_base', None):
            api_base = args.api_base
        if getattr(args, 'api_key', None):
            api_key = args.api_key

    if model_override:
        model = model_override
    elif args is not None:
        reasoning_model = getattr(args, 'model_reasoning', None)
        if reasoning_model:
            model = reasoning_model

    # URL 规范化：DeepSeek Anthropic 端点映射为 OpenAI 兼容端点
    # https://api.deepseek.com/anthropic → https://api.deepseek.com/v1
    if "api.deepseek.com/anthropic" in api_base:
        api_base = "https://api.deepseek.com/v1"

    config = {"api_base": api_base, "api_key": api_key, "model": model}

    # 配置完整性检查：优化阶段 API 未配置时给出明确提示
    missing = []
    if not api_base:
        missing.append("api_base (SKILLX_API_BASE / ANTHROPIC_BASE_URL / --api-base)")
    if not api_key:
        missing.append("api_key (SKILLX_API_KEY / ANTHROPIC_API_KEY / --api-key)")
    if not model:
        missing.append("model (ANTHROPIC_MODEL / COSIGHT_MODEL / --model-reasoning)")
    if missing:
        print(f"  ⚠️ 优化阶段 API 配置不完整，缺少:")
        for m in missing:
            print(f"  └─ {m}")
        print(f"  └─ 请通过 CLI 参数、环境变量、或 .env 文件配置优化阶段的 API 信息")

    return config


def get_eval_api_config(args=None):
    """
    获取评测专用 API 配置（用于评测阶段：LLM 分数解析、Gap 分析、沙箱评测脚本）

    如果未配置评测专用参数，自动回退到全局配置 get_api_config()。

    优先级（从高到低）：
    1. CLI 参数（--eval-model, --eval-api-base, --eval-api-key）
    2. SKILLX_EVAL_* 环境变量
    3. 回退到 get_api_config()（全局配置）

    Args:
        args: 命令行参数对象（可选），可包含 eval_model, eval_api_base, eval_api_key 属性

    Returns:
        dict: {"api_base": ..., "api_key": ..., "model": ...}
    """
    # CLI 参数（最高优先级）
    eval_model = None
    eval_api_base = None
    eval_api_key = None

    if args is not None:
        eval_model = getattr(args, 'eval_model', None) or None
        eval_api_base = getattr(args, 'eval_api_base', None) or None
        eval_api_key = getattr(args, 'eval_api_key', None) or None

    # 环境变量
    if not eval_model:
        eval_model = os.environ.get("ANTHROPIC_MODEL", "").strip() or None
    if not eval_api_base:
        eval_api_base = os.environ.get("SKILLX_EVAL_API_BASE", "").strip() or None
    if not eval_api_key:
        eval_api_key = os.environ.get("SKILLX_EVAL_API_KEY", "").strip() or None

    # 评测模型未配置时，直接回退到全局配置（ANTHROPIC_MODEL）
    if not eval_model:
        return get_api_config(args)

    # 使用评测专用配置
    api_base = eval_api_base or os.environ.get("SKILLX_API_BASE", "").strip()
    if not api_base:
        _global = _resolve_global_model()
        api_base = _global.get("api_base") or _DEFAULT_API_BASE

    api_key = eval_api_key or os.environ.get("SKILLX_API_KEY", "").strip()
    if not api_key:
        _global = _resolve_global_model()
        api_key = _global.get("api_key") or os.environ.get("DEEPSEEK_API_KEY") or _DEFAULT_API_KEY

    # URL 规范化
    if "api.deepseek.com/anthropic" in api_base:
        api_base = "https://api.deepseek.com/v1"

    return {"api_base": api_base, "api_key": api_key, "model": eval_model}


def apply_env_from_args(args):
    """
    将 CLI 参数写入环境变量，使子模块可直接通过 os.environ 获取

    Args:
        args: 命令行参数对象
    """
    if getattr(args, 'api_base', None):
        os.environ["SKILLX_API_BASE"] = args.api_base
    if getattr(args, 'api_key', None):
        os.environ["SKILLX_API_KEY"] = args.api_key
    # [已废弃] SKILLX_MODEL/SKILLX_EVAL_MODEL → 子代理直接读取 ANTHROPIC_MODEL
    # CLI 参数仍映射到 ANTHROPIC_MODEL，保持向后兼容
    if getattr(args, 'model_reasoning', None):
        os.environ["ANTHROPIC_MODEL"] = args.model_reasoning
    if getattr(args, 'eval_model', None):
        os.environ["ANTHROPIC_MODEL"] = args.eval_model
    if getattr(args, 'eval_api_base', None):
        os.environ["SKILLX_EVAL_API_BASE"] = args.eval_api_base
    if getattr(args, 'eval_api_key', None):
        os.environ["SKILLX_EVAL_API_KEY"] = args.eval_api_key
