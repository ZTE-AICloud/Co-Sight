"""全局异常钩子 — 异常退出时恢复原路径 .bak。

config.json 新增字段:
{
  "user_source_bak": {
    "backup_roots": {"SkillName": "/path/to/skills/SkillName.bak"},
    "created_at": "ISO 8601 timestamp"
  }
}

atexit / SIGINT / SIGTERM 触发时,从 config 读 .bak 路径并恢复到原路径。

设计原则：
- 容错优先：所有失败仅 print warning，不影响主流程退出
- 幂等注册：同一进程多次调用只注册一次
- 已清理或无字段 → noop（向后兼容）

注意：
- atexit 在 SIGKILL(-9) 不触发 → 需手动 rm .bak + 从 git 恢复
- signal handler 必须在主线程注册才生效
"""

from __future__ import annotations

import atexit
import json
import logging
import shutil
import signal
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)

_HOOK_INSTALLED = False  # 单例保护


def _read_user_source_bak(config_path: Path) -> Optional[dict]:
    """从 config.json 读 user_source_bak 字段。缺失/文件不存在/解析失败 → return None。"""
    if not config_path.exists():
        return None
    try:
        with open(config_path, "r", encoding="utf-8") as f:
            config = json.load(f)
        return config.get("user_source_bak")
    except (json.JSONDecodeError, OSError) as e:
        logger.warning("读 config.json 失败 (%s): %s", config_path, e)
        return None


def _safe_restore_all(config_path: Path) -> None:
    """atexit / signal handler：从 config.json 读 .bak 路径，恢复到原路径。

    容错设计：
    - config 缺失 / 无 user_source_bak 字段 → noop
    - .bak 已不存在 → noop（可能已被手动清理或 cleanup_skill_bak 清过）
    - 单个 skill 恢复失败 → log warning，继续其他
    """
    bak_info = _read_user_source_bak(config_path)
    if not bak_info:
        return
    backup_roots = bak_info.get("backup_roots", {})
    if not backup_roots:
        return

    print(f"  🚨 异常退出检测:恢复 {len(backup_roots)} 个 skill 原路径...")
    for name, bak_path_str in backup_roots.items():
        bak_path = Path(bak_path_str)
        if not bak_path.exists():
            print(f"  ⏭️  {name}: .bak 已不存在({bak_path}),跳过")
            continue
        # 原路径 = .bak 父目录 / {name}(与 backup_skill_to_bak 的派生逻辑一致)
        orig_dir = bak_path.parent / name
        try:
            if orig_dir.exists():
                shutil.rmtree(str(orig_dir))
            shutil.copytree(str(bak_path), str(orig_dir))
            print(f"  ✅ 恢复 {name}: {bak_path} → {orig_dir}")
        except Exception as e:
            print(f"  ⚠️  恢复失败 {name}: {e}")
            continue

    # 清理 config.json 的 user_source_bak 字段(避免下次启动误以为还有未恢复的备份)
    try:
        with open(config_path, "r", encoding="utf-8") as f:
            config = json.load(f)
        if "user_source_bak" in config:
            del config["user_source_bak"]
            with open(config_path, "w", encoding="utf-8") as f:
                json.dump(config, f, ensure_ascii=False, indent=2)
            print("  🧹 清理 config.json user_source_bak 字段")
    except Exception as e:
        print(f"  ⚠️  清理 config 失败: {e}")


def _signal_handler(signum, frame, config_path: Path) -> None:
    """SIGINT / SIGTERM handler：调 _safe_restore_all + 重新抛 KeyboardInterrupt。"""
    print(f"\n  ⚠️ 收到信号 {signum},尝试恢复原路径...")
    _safe_restore_all(config_path)
    # 重新抛出,让默认行为继续(中断主进程)
    raise KeyboardInterrupt()


def register_cleanup_hook(config_path: Path) -> None:
    """从 config.json 读 user_source_bak 注册 atexit + signal 钩子。

    幂等:同一进程多次调用只注册一次(避免 hook 链堆积)。

    Args:
        config_path: orchestrator 的 config.json 绝对路径
    """
    global _HOOK_INSTALLED
    if _HOOK_INSTALLED:
        return
    _HOOK_INSTALLED = True

    # atexit:正常退出触发(包括 sys.exit()、主程序 return、异常未捕获)
    atexit.register(_safe_restore_all, config_path)

    # SIGINT / SIGTERM:用户 Ctrl+C 或 kill 触发
    try:
        signal.signal(signal.SIGINT, lambda s, f: _signal_handler(s, f, config_path))
        signal.signal(signal.SIGTERM, lambda s, f: _signal_handler(s, f, config_path))
    except ValueError:
        # 非主线程调用 signal.signal 会抛 ValueError,降级到只 atexit 兜底
        logger.warning("signal handler 注册失败(非主线程),仅 atexit 兜底")


def unregister_cleanup_hook() -> None:
    """测试 / 正常 finish 时反注册(目前仅清单例标志)。

    注:atexit 钩子本身是 LIFO 栈,无法选择性撤销;信号 handler 同上。
    本函数主要为测试场景重置单例状态。
    """
    global _HOOK_INSTALLED
    _HOOK_INSTALLED = False


def write_user_source_bak_to_config(
    config_path: Path,
    backup_roots: dict,
) -> None:
    """把 backup_roots 写入 config.json 的 user_source_bak 字段。

    在 backup_skill_to_bak 后调,记录 .bak 路径供异常恢复寻址。

    Args:
        config_path: config.json 路径
        backup_roots: {SkillName: .bak path} 字典
    """
    if not config_path.exists():
        # config 还没初始化(理论上不应发生,但容错:建空 config)
        config_path.parent.mkdir(parents=True, exist_ok=True)
        config = {}
    else:
        with open(config_path, "r", encoding="utf-8") as f:
            config = json.load(f)

    config["user_source_bak"] = {
        "backup_roots": backup_roots,
        "created_at": datetime.now(timezone.utc).isoformat(),
    }

    with open(config_path, "w", encoding="utf-8") as f:
        json.dump(config, f, ensure_ascii=False, indent=2)


def clear_user_source_bak_from_config(config_path: Path) -> bool:
    """从 config.json 删除 user_source_bak 字段(任务成功 finish 时调)。

    Returns:
        是否成功删除(本来不存在也返回 True)
    """
    if not config_path.exists():
        return True
    try:
        with open(config_path, "r", encoding="utf-8") as f:
            config = json.load(f)
        if "user_source_bak" in config:
            del config["user_source_bak"]
            with open(config_path, "w", encoding="utf-8") as f:
                json.dump(config, f, ensure_ascii=False, indent=2)
        return True
    except Exception as e:
        logger.warning("清 user_source_bak 字段失败 (%s): %s", config_path, e)
        return False