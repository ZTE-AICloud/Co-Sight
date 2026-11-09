"""
Hook 规范定义
=============
定义 Hook 的数据结构和类型
"""

from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Callable, Dict, List, Optional


class HookTrigger(Enum):
    """Hook 触发时机"""
    PRE_ROUND = "pre_round"           # 轮次开始前
    POST_EVALUATION = "post_evaluation"  # 评测完成后
    POST_OPTIMIZATION = "post_optimization"  # 优化完成后
    POST_ROUND = "post_round"         # 轮次结束后
    ON_ERROR = "on_error"             # 发生错误时
    ON_APPLY_PROPOSAL = "on_apply_proposal"  # 应用提案时


@dataclass
class HookSpec:
    """
    Hook 规范

    Attributes:
        name: Hook 名称
        trigger: 触发时机
        fn: Hook 函数
        timeout: 超时时间（秒）
        enabled: 是否启用
        config: 额外配置
    """
    name: str
    trigger: HookTrigger
    fn: Callable[[Dict[str, Any]], bool]
    timeout: int = 30
    enabled: bool = True
    config: Dict[str, Any] = field(default_factory=dict)

    def __post_init__(self):
        # 兼容字符串 trigger
        if isinstance(self.trigger, str):
            self.trigger = HookTrigger(self.trigger)


@dataclass
class HookResult:
    """
    Hook 执行结果

    Attributes:
        success: 是否成功
        hook_name: Hook 名称
        message: 结果消息
        duration_ms: 执行耗时（毫秒）
        error: 错误信息（如果有）
    """
    success: bool
    hook_name: str
    message: str = ""
    duration_ms: float = 0
    error: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        return {
            "success": self.success,
            "hook_name": self.hook_name,
            "message": self.message,
            "duration_ms": self.duration_ms,
            "error": self.error,
        }


# 预定义的 Hook 名称常量
class HookNames:
    """预定义的内置 Hook 名称"""
    # pre_round
    VALIDATE_SKILL_PATH = "validate_skill_path"
    ENSURE_DIRS = "ensure_dirs"
    CHECK_GOLD_DATA = "check_gold_data"

    # post_evaluation
    ARCHIVE_REPORT = "archive_report"
    NOTIFY_COMPLETION = "notify_completion"

    # post_optimization
    COMMIT_VERSION = "commit_version"

    # post_round
    SAVE_SNAPSHOT = "save_snapshot"

    # on_error
    ROLLBACK_STATE = "rollback_state"
    ALERT_ADMIN = "alert_admin"
    LOG_ERROR = "log_error"

    # on_apply_proposal
    BACKUP_BEFORE_APPLY = "backup_before_apply"