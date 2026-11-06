# Copyright 2025 ZTE Corporation.
# All Rights Reserved.
#
#    Licensed under the Apache License, Version 2.0 (the "License"); you may
#    not use this file except in compliance with the License. You may obtain
#    a copy of the License at
#
#         http://www.apache.org/licenses/LICENSE-2.0
#
#    Unless required by applicable law or agreed to in writing, software
#    distributed under the License is distributed on an "AS IS" BASIS, WITHOUT
#    WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied. See the
#    License for the specific language governing permissions and limitations
#    under the License.

from threading import Lock
from typing import Callable, Dict, List, Any, Optional
from concurrent.futures import ThreadPoolExecutor

from app.cosight.task.task_manager import TaskManager
from app.cosight.task.todolist import Plan
from app.common.logger_util import logger


class EventManager:
    def __init__(self):
        # 结构: {event_type: {plan_id: [callbacks]}}
        self._subscribers: Dict[str, Dict[str, List[Callable]]] = {}
        self._lock = Lock()
        self._executor = ThreadPoolExecutor()

    def subscribe(self, event_type: str, plan_id: str, callback: Callable):
        """订阅事件，关联计划ID"""
        with self._lock:
            if event_type not in self._subscribers:
                self._subscribers[event_type] = {}
            self._subscribers[event_type].setdefault(plan_id, []).append(callback)
        logger.info(f"Subscribed to {event_type} for plan_id: {plan_id}, total callbacks: {len(self._subscribers[event_type][plan_id])}")

    def publish(self, event_type: str, plan_or_plan_id=None, event_data=None):
        """发布事件 - 支持Plan对象和工具事件数据"""
        # 处理工具事件的特殊情况
        if event_type == "tool_event" and isinstance(plan_or_plan_id, str) and event_data is not None:
            plan_id = plan_or_plan_id
            callbacks = []
            with self._lock:
                if event_type in self._subscribers and plan_id in self._subscribers[event_type]:
                    callbacks = self._subscribers[event_type][plan_id].copy()

            logger.info(f"Publishing tool_event for plan_id: {plan_id}, callbacks: {len(callbacks)}")
            # 对于工具事件，使用同步调用确保顺序
            for callback in callbacks:
                try:
                    callback(event_data)
                except Exception as e:
                    logger.error(f"工具事件回调执行失败: {e}", exc_info=True)
            return
        
        # 原有的Plan对象处理逻辑
        plan = plan_or_plan_id
        if plan is None:
            return

        # 通过TaskManager获取plan_id
        plan_id = TaskManager.get_plan_id(plan)
        if not plan_id:
            logger.warning(f"无法找到plan对象的ID: {plan}")
            return

        callbacks = []
        with self._lock:
            if event_type in self._subscribers and plan_id in self._subscribers[event_type]:
                callbacks = self._subscribers[event_type][plan_id].copy()

        logger.info(f"Publishing {event_type} for plan_id: {plan_id}, callbacks: {len(callbacks)}")
        for callback in callbacks:
            self._executor.submit(self._safe_callback, callback, plan)

    def unsubscribe(self, event_type: str, plan_id: str, callback: Callable):
        """取消订阅特定计划ID的事件"""
        with self._lock:
            if (event_type in self._subscribers and
                    plan_id in self._subscribers[event_type]):
                try:
                    self._subscribers[event_type][plan_id].remove(callback)
                except ValueError:
                    pass

    def _safe_callback(self, callback: Callable, data):
        try:
            callback(data)
        except Exception as e:
            logger.error(f"Callback failed: {str(e)}", exc_info=True)


plan_report_event_manager = EventManager()
