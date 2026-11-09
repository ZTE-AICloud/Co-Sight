"""
Hook 注册表
============
管理 Hook 的注册和触发
"""

import importlib
import importlib.util
import logging
import time
from pathlib import Path
from typing import Any, Dict, List, Optional

from .spec import HookResult, HookSpec, HookTrigger

logger = logging.getLogger(__name__)


class HookRegistry:
    """
    Hook 注册表

    管理所有 Hook 的注册、配置和触发

    用法：
        registry = HookRegistry()

        # 注册 Hook
        registry.register(HookSpec(
            name="validate_skill",
            trigger=HookTrigger.PRE_ROUND,
            fn=lambda ctx: validate_skill_path(ctx)
        ))

        # 触发 Hook
        results = registry.trigger(HookTrigger.PRE_ROUND, {"round": 1})

        # 加载内置 Hooks
        registry.load_builtin_hooks()
    """

    def __init__(self):
        self._hooks: Dict[HookTrigger, List[HookSpec]] = {
            trigger: [] for trigger in HookTrigger
        }
        self._enabled = True

    def register(self, spec: HookSpec) -> None:
        """
        注册一个 Hook

        Args:
            spec: Hook 规范
        """
        if not spec.enabled:
            return

        trigger_hooks = self._hooks.get(spec.trigger, [])
        # 检查是否已存在同名 Hook
        existing = [h for h in trigger_hooks if h.name == spec.name]
        if existing:
            logger.warning(f"Hook '{spec.name}' already registered for {spec.trigger.value}, replacing")
            trigger_hooks.remove(existing[0])

        trigger_hooks.append(spec)
        self._hooks[spec.trigger] = trigger_hooks
        logger.debug(f"Registered hook '{spec.name}' for {spec.trigger.value}")

    def unregister(self, name: str, trigger: Optional[HookTrigger] = None) -> bool:
        """
        注销一个 Hook

        Args:
            name: Hook 名称
            trigger: 可选，限定在特定触发时机

        Returns:
            是否成功注销
        """
        removed = False
        for t, hooks in self._hooks.items():
            if trigger is not None and t != trigger:
                continue
            original_len = len(hooks)
            self._hooks[t] = [h for h in hooks if h.name != name]
            if len(self._hooks[t]) < original_len:
                removed = True
        return removed

    def trigger(self, trigger: HookTrigger, context: Dict[str, Any]) -> List[HookResult]:
        """
        触发指定类型的所有 Hook

        Args:
            trigger: 触发时机
            context: 上下文数据

        Returns:
            所有 Hook 的执行结果

        超时策略：纯计时检查（subprocess 安全，不依赖 signal.SIGALRM）。
        若 hook 函数执行时长 > spec.timeout，记录超时但**不强制中断**（避免破坏主链路）。
        hook 自身应保持短小，复杂工作放到异步任务里。
        """
        if not self._enabled:
            return []

        results = []
        hooks = self._hooks.get(trigger, [])

        for spec in hooks:
            if not spec.enabled:
                continue

            start_time = time.time()
            try:
                success = spec.fn(context)
                message = "OK" if success else "Hook returned False"
                error = None
            except Exception as e:
                success = False
                message = ""
                error = f"{type(e).__name__}: {e}"
                logger.exception(f"Hook '{spec.name}' failed: {e}")

            duration_ms = (time.time() - start_time) * 1000

            if duration_ms > spec.timeout * 1000:
                logger.warning(
                    f"Hook '{spec.name}' 耗时 {duration_ms:.0f}ms 超过设定超时 {spec.timeout*1000:.0f}ms（仅警告，未强制中断）"
                )

            result = HookResult(
                success=success,
                hook_name=spec.name,
                message=message,
                duration_ms=duration_ms,
                error=error
            )
            results.append(result)

            try:
                from hooks._debug import log_hook_event
                log_hook_event(
                    trigger=trigger.value if hasattr(trigger, "value") else str(trigger),
                    hook_name=spec.name,
                    success=success,
                    duration_ms=duration_ms,
                    context=context,
                    error=error,
                )
            except Exception:
                pass

            if not success and trigger == HookTrigger.ON_ERROR:
                # on_error Hook 失败不应该递归
                pass

        return results

    def load_builtin_hooks(self) -> int:
        """
        加载内置 Hooks

        Returns:
            加载的 Hook 数量
        """
        builtin_dir = Path(__file__).parent / "builtin"
        if not builtin_dir.exists():
            return 0

        loaded = 0
        for file_path in builtin_dir.glob("*.py"):
            if file_path.name.startswith("_"):
                continue

            try:
                # 动态导入模块
                spec = importlib.util.spec_from_file_location(
                    f"hooks.builtin.{file_path.stem}",
                    file_path
                )
                if spec and spec.loader:
                    module = importlib.util.module_from_spec(spec)
                    spec.loader.exec_module(module)

                    # 查找模块中的 HookSpec 对象
                    for attr_name in dir(module):
                        attr = getattr(module, attr_name)
                        if isinstance(attr, HookSpec):
                            self.register(attr)
                            loaded += 1
                        elif isinstance(attr, list) and all(isinstance(x, HookSpec) for x in attr):
                            for hook in attr:
                                self.register(hook)
                                loaded += 1

            except Exception as e:
                logger.warning(f"Failed to load builtin hooks from {file_path}: {e}")

        return loaded

    def load_hooks_from_config(self, config: Dict[str, Any]) -> int:
        """
        从配置加载 Hooks

        配置格式：
        {
            "hooks": {
                "pre_round": ["validate_skill", "ensure_dirs"],
                "post_evaluation": ["archive_report"]
            }
        }

        Args:
            config: 配置字典

        Returns:
            加载的 Hook 数量
        """
        # 预定义的 Hook 映射
        hook_map = self._get_builtin_hook_map()

        loaded = 0
        hooks_config = config.get("hooks", {})

        for trigger_str, hook_names in hooks_config.items():
            try:
                HookTrigger(trigger_str)  # 校验合法性
            except ValueError:
                logger.warning(f"Unknown hook trigger: {trigger_str}")
                continue

            for name in hook_names:
                if name in hook_map:
                    self.register(hook_map[name])
                    loaded += 1
                else:
                    logger.warning(f"Unknown hook name: {name}")

        return loaded

    def _get_builtin_hook_map(self) -> Dict[str, HookSpec]:
        """获取内置 Hook 映射（兼容历史调用，主要 hook 通过 load_builtin_hooks 动态注册）"""
        hooks: Dict[str, HookSpec] = {}
        builtin_pkg_name = "hooks.builtin"
        try:
            builtin_pkg = importlib.import_module(builtin_pkg_name)
        except ImportError:
            return hooks

        for attr_name in dir(builtin_pkg):
            attr = getattr(builtin_pkg, attr_name)
            if isinstance(attr, HookSpec):
                hooks[attr.name] = attr
        return hooks

    def enable(self):
        """启用 Hooks"""
        self._enabled = True

    def disable(self):
        """禁用 Hooks"""
        self._enabled = False

    @property
    def enabled(self) -> bool:
        return self._enabled

    def get_hooks(self, trigger: HookTrigger) -> List[HookSpec]:
        """获取指定触发时机的所有 Hook"""
        return self._hooks.get(trigger, [])

    def list_all_hooks(self) -> List[HookSpec]:
        """列出所有已注册的 Hook"""
        all_hooks = []
        for hooks in self._hooks.values():
            all_hooks.extend(hooks)
        return all_hooks