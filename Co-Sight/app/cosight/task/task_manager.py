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


class TaskManager:
    _lock = Lock()
    plans = {}
    plan_to_id = {}
    # 运行中计划集合，用于幂等与判重
    running_plans = set()

    @classmethod
    def set_plan(cls, plan_id: str, plan):
        with cls._lock:
            cls.plans[plan_id] = plan
            cls.plan_to_id[id(plan)] = plan_id

    @classmethod
    def get_plan(cls, plan_id: str):
        with cls._lock:
            return cls.plans.get(plan_id)

    @classmethod
    def get_plan_id(cls, plan):
        with cls._lock:
            return cls.plan_to_id.get(id(plan))

    @classmethod
    def remove_plan(cls, plan_id: str):
        with cls._lock:
            plan = cls.plans.get(plan_id)
            if plan is not None:
                memory_address = id(plan)
                if memory_address in cls.plan_to_id:
                    del cls.plan_to_id[memory_address]
                if plan_id in cls.plans:
                    del cls.plans[plan_id]
            # 从运行集中移除（容错处理）
            if plan_id in cls.running_plans:
                cls.running_plans.discard(plan_id)

    @classmethod
    def is_running(cls, plan_id: str) -> bool:
        with cls._lock:
            return plan_id in cls.running_plans

    @classmethod
    def mark_running(cls, plan_id: str):
        with cls._lock:
            cls.running_plans.add(plan_id)

    @classmethod
    def mark_completed(cls, plan_id: str):
        with cls._lock:
            cls.running_plans.discard(plan_id)

