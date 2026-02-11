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

"""Netopt actor reuses task_actor prompts; can be overridden later for netopt-specific wording."""

from app.cosight.agent.actor.task_actor.prompt import (
    actor_system_prompt,
    actor_system_prompt_zh,
    actor_execute_task_prompt,
    actor_execute_task_prompt_zh,
)

__all__ = [
    "actor_system_prompt",
    "actor_system_prompt_zh",
    "actor_execute_task_prompt",
    "actor_execute_task_prompt_zh",
]
