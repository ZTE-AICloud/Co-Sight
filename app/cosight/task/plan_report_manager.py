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


from app.cosight.task.todolist import Plan


class EventManager:
    def __init__(self):
        self._subscribers: Dict[str, List[Callable]] = {}  # 简化为直接存储回调函数列表
        self._lock = Lock()
        self._executor = ThreadPoolExecutor()

    def subscribe(self, event_type: str, callback: Callable[[Any], None]):
        """订阅事件"""
        with self._lock:
            self._subscribers.setdefault(event_type, []).append(callback)

    def publish(self, event_type: str, plan: Optional[Plan] = None):
        """发布事件"""
        callbacks = []
        with self._lock:
            if event_type in self._subscribers:
                callbacks = self._subscribers[event_type].copy()

        for callback in callbacks:
            self._executor.submit(self._safe_callback, callback, plan)

    def _safe_callback(self, callback: Callable, plan: Optional[Plan]):
        try:
            callback(plan)
        except Exception as e:
            print(f"Callback failed: {e}")


plan_report_event_manager = EventManager()
