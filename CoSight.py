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

from datetime import datetime
import os
import time
from threading import Thread

from app.common.logger_util import logger
from app.cosight.agent.actor.instance.actor_agent_instance import create_actor_instance
from app.cosight.agent.actor.task_actor_agent import TaskActorAgent
from app.cosight.agent.planner.instance.planner_agent_instance import create_planner_instance
from app.cosight.agent.planner.task_plannr_agent import TaskPlannerAgent
from app.cosight.agent.runtime import agent_registry
from app.cosight.agent.runtime import agent_runtime_factory
from app.cosight.task.task_manager import TaskManager
from app.cosight.task.time_record_util import time_record
from app.cosight.task.todolist import Plan
from llm import llm_for_plan, llm_for_act, llm_for_tool, llm_for_vision


class CoSight:
    def __init__(
        self,
        plan_llm,
        act_llm,
        tool_llm,
        vision_llm,
        work_space_path: str = None,
        message_uuid: str | None = None,
        agent_run_config: dict | None = None,
    ):
        self.work_space_path = work_space_path or os.getenv("WORKSPACE_PATH") or os.getcwd()
        self.plan_id = message_uuid if message_uuid else f"plan_{int(time.time())}"
        self.plan = Plan()
        TaskManager.set_plan(self.plan_id, self.plan)

        self.act_llm = act_llm
        self.tool_llm = tool_llm
        self.vision_llm = vision_llm

        self.agent_run_config = self._normalize_agent_run_config(agent_run_config or {})
        self.selected_planner_id = self.agent_run_config["planner_id"]
        self.dispatch_mode = self.agent_run_config["dispatch_mode"]
        self.allowed_actor_ids = self.agent_run_config["allowed_actor_ids"]
        self.default_actor_id = self.agent_run_config["default_actor_id"]
        self.planner_custom_prompt = None

        self.plan.configure_runtime_agents(
            planner_id=self.selected_planner_id,
            allowed_actor_ids=self.allowed_actor_ids,
            default_actor_id=self.default_actor_id,
            dispatch_mode=self.dispatch_mode,
        )

        plan_llm.set_trace_context(
            trace_id=None,
            session_id=self.plan_id,
            tags=["planning"],
            metadata={"agent_type": "planner", "plan_id": self.plan_id},
        )
        act_llm.set_trace_context(
            trace_id=None,
            session_id=self.plan_id,
            tags=["execution"],
            metadata={"agent_type": "actor", "plan_id": self.plan_id},
        )
        tool_llm.set_trace_context(
            trace_id=None,
            session_id=self.plan_id,
            tags=["tool"],
            metadata={"agent_type": "tool", "plan_id": self.plan_id},
        )
        vision_llm.set_trace_context(
            trace_id=None,
            session_id=self.plan_id,
            tags=["vision"],
            metadata={"agent_type": "vision", "plan_id": self.plan_id},
        )

        self.task_planner_agent = self._create_planner(plan_llm)

        self._actor_configs_cache = {}
        for actor_id in self.allowed_actor_ids:
            actor_config = agent_registry.get_agent_by_id(actor_id)
            if self._is_valid_actor_config(actor_config):
                self._actor_configs_cache[actor_id] = actor_config

        logger.info(
            "CoSight initialized: planner_id=%s, dispatch_mode=%s, allowed_actors=%s, default_actor=%s",
            self.selected_planner_id,
            self.dispatch_mode,
            self.allowed_actor_ids,
            self.default_actor_id,
        )

    @staticmethod
    def _is_valid_planner_config(agent_config: dict | None) -> bool:
        return bool(
            agent_config
            and agent_config.get("enabled", True)
            and agent_config.get("agent_type") == "planner"
        )

    @staticmethod
    def _is_valid_actor_config(agent_config: dict | None) -> bool:
        return bool(
            agent_config
            and agent_config.get("enabled", True)
            and agent_config.get("agent_type") == "actor"
        )

    @staticmethod
    def _set_runtime_agent_metadata(agent, agent_id: str, agent_name: str, agent_type: str):
        agent.runtime_agent_id = agent_id
        agent.runtime_agent_name = agent_name
        agent.runtime_agent_type = agent_type

    def _normalize_agent_run_config(self, raw_config: dict) -> dict:
        default_planner = agent_registry.get_default_planner() or {}
        default_actor = agent_registry.get_default_actor() or {}

        planner_id = raw_config.get("planner_id") or default_planner.get("id") or "builtin-planner"
        planner_config = agent_registry.get_agent_by_id(planner_id)
        if not self._is_valid_planner_config(planner_config):
            fallback_planner_id = default_planner.get("id") or "builtin-planner"
            logger.warning(
                "Invalid planner_id '%s', falling back to '%s'",
                planner_id,
                fallback_planner_id,
            )
            planner_id = fallback_planner_id

        requested_actor_ids = raw_config.get("allowed_actor_ids")
        if not isinstance(requested_actor_ids, list):
            requested_actor_ids = []

        valid_actor_ids = []
        for actor_id in requested_actor_ids:
            if actor_id in valid_actor_ids:
                continue
            actor_config = agent_registry.get_agent_by_id(actor_id)
            if self._is_valid_actor_config(actor_config):
                valid_actor_ids.append(actor_id)
            else:
                logger.warning("Ignoring invalid actor_id '%s' in agent_run_config", actor_id)

        fallback_actor_id = default_actor.get("id") or "builtin-actor"
        fallback_actor_config = agent_registry.get_agent_by_id(fallback_actor_id)
        if not valid_actor_ids and self._is_valid_actor_config(fallback_actor_config):
            valid_actor_ids = [fallback_actor_id]

        default_actor_id = raw_config.get("default_actor_id") or fallback_actor_id
        if default_actor_id not in valid_actor_ids:
            default_actor_id = valid_actor_ids[0] if valid_actor_ids else fallback_actor_id

        dispatch_mode = raw_config.get("dispatch_mode", "single_actor")
        if dispatch_mode not in ("single_actor", "planner_assign"):
            logger.warning(
                "Invalid dispatch_mode '%s', falling back to 'single_actor'",
                dispatch_mode,
            )
            dispatch_mode = "single_actor"

        return {
            "planner_id": planner_id,
            "allowed_actor_ids": valid_actor_ids,
            "default_actor_id": default_actor_id,
            "dispatch_mode": dispatch_mode,
        }

    def _create_planner(self, plan_llm):
        planner_config = agent_registry.get_agent_by_id(self.selected_planner_id)
        planner_name = planner_config.get("name", "Task Planning Expert") if planner_config else "Task Planning Expert"

        if self._is_valid_planner_config(planner_config):
            try:
                planner, self.planner_custom_prompt = agent_runtime_factory.create_planner_runtime(
                    planner_config,
                    plan_llm,
                    self.plan_id,
                )
                self._set_runtime_agent_metadata(planner, self.selected_planner_id, planner_name, "planner")
                return planner
            except Exception as exc:
                logger.warning(
                    "Failed to create planner '%s': %s, using built-in planner",
                    self.selected_planner_id,
                    exc,
                )

        planner = TaskPlannerAgent(create_planner_instance("task_planner_agent"), plan_llm, self.plan_id)
        self._set_runtime_agent_metadata(planner, "builtin-planner", planner_name, "planner")
        self.selected_planner_id = "builtin-planner"
        self.plan.selected_planner_id = self.selected_planner_id
        return planner

    @time_record
    def execute(self, question, output_format=""):
        task_metadata = {
            "task_question": question[:200] if len(question) > 200 else question,
            "plan_id": self.plan_id,
        }

        for llm in [self.task_planner_agent.llm, self.act_llm, self.tool_llm, self.vision_llm]:
            if hasattr(llm, "current_metadata"):
                llm.current_metadata.update(task_metadata)

        create_task = question
        retry_count = 0
        available_actors = list(self._actor_configs_cache.values()) if self._actor_configs_cache else None
        while not self.plan.get_ready_steps() and retry_count < 3:
            create_result = self.task_planner_agent.create_plan(
                create_task,
                output_format,
                available_actors=available_actors,
                dispatch_mode=self.dispatch_mode,
                custom_system_prompt=self.planner_custom_prompt,
            )
            create_task += (
                f"\nThe plan creation result is: {create_result}\n"
                "Creation failed, please carefully review the plan creation rules "
                "and select the create_plan tool to create the plan"
            )
            retry_count += 1

        active_threads = {}

        while True:
            ready_steps = self.plan.get_ready_steps()

            for step_index in ready_steps:
                if step_index not in active_threads:
                    logger.info("Starting new step %s", step_index)
                    thread = Thread(target=self._execute_single_step, args=(question, step_index))
                    thread.daemon = True
                    thread.start()
                    active_threads[step_index] = thread

            completed_steps = []
            for step_index, thread in active_threads.items():
                if not thread.is_alive():
                    completed_steps.append(step_index)

            for step_index in completed_steps:
                del active_threads[step_index]
                logger.info("Step %s completed and thread removed", step_index)

            if not active_threads and not ready_steps:
                logger.info("No more ready steps to execute and no active threads")
                break

            time.sleep(0.1)

        return self.task_planner_agent.finalize_plan(question, output_format)

    def _resolve_actor_id_for_step(self, step_index: int) -> str:
        if self.dispatch_mode == "single_actor" or not self.allowed_actor_ids:
            return self.default_actor_id

        step_agent_id = self.plan.get_step_agent(step_index)
        if step_agent_id and step_agent_id in self.allowed_actor_ids:
            return step_agent_id
        return self.default_actor_id

    def _create_actor_for_step(self, step_index: int):
        actor_id = self._resolve_actor_id_for_step(step_index)
        actor_config = self._actor_configs_cache.get(actor_id)

        if actor_config:
            try:
                actor = agent_runtime_factory.create_actor_runtime(
                    agent_config=actor_config,
                    fallback_act_llm=self.act_llm,
                    fallback_vision_llm=self.vision_llm,
                    fallback_tool_llm=self.tool_llm,
                    plan_id=self.plan_id,
                    work_space_path=self.work_space_path,
                    step_index=step_index,
                )
                self._set_runtime_agent_metadata(actor, actor_id, actor_config.get("name", actor_id), "actor")
                self.plan.set_step_execution_agent(step_index, actor_id)
                logger.info(
                    "Step %s: using actor '%s' (id=%s)",
                    step_index,
                    actor_config.get("name"),
                    actor_id,
                )
                return actor
            except Exception as exc:
                logger.warning(
                    "Step %s: failed to create actor (id=%s): %s, using built-in actor",
                    step_index,
                    actor_id,
                    exc,
                )

        actor = TaskActorAgent(
            create_actor_instance(f"actor_for_step_{step_index}", self.work_space_path),
            self.act_llm,
            self.vision_llm,
            self.tool_llm,
            self.plan_id,
            work_space_path=self.work_space_path,
        )
        self._set_runtime_agent_metadata(actor, "builtin-actor", "Task Actor", "actor")
        self.plan.set_step_execution_agent(step_index, "builtin-actor")
        return actor

    def _execute_single_step(self, question, step_index):
        try:
            logger.info("Starting execution of step %s", step_index)
            task_actor_agent = self._create_actor_for_step(step_index)
            result = task_actor_agent.act(question=question, step_index=step_index)
            logger.info("Completed execution of step %s with result: %s", step_index, result)
        except Exception as exc:
            logger.error("Error executing step %s: %s", step_index, exc, exc_info=True)

    def execute_steps(self, question, ready_steps):
        from queue import Queue
        from threading import Semaphore, Thread

        results = {}
        result_queue = Queue()
        semaphore = Semaphore(min(5, len(ready_steps)))

        def execute_step(step_index):
            semaphore.acquire()
            try:
                logger.info("Starting execution of step %s", step_index)
                task_actor_agent = self._create_actor_for_step(step_index)
                result = task_actor_agent.act(question=question, step_index=step_index)
                logger.info("Completed execution of step %s with result: %s", step_index, result)
                result_queue.put((step_index, result))
            finally:
                semaphore.release()

        threads = []
        for step_index in ready_steps:
            thread = Thread(target=execute_step, args=(step_index,))
            thread.start()
            threads.append(thread)

        for thread in threads:
            thread.join()

        while not result_queue.empty():
            step_index, result = result_queue.get()
            results[step_index] = result

        return results


if __name__ == "__main__":
    base_dir = os.path.dirname(os.path.abspath(__file__))
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S_%f")
    work_space_path = os.path.join(base_dir, "work_space", f"work_space_{timestamp}")
    os.makedirs(work_space_path, exist_ok=True)

    cosight = CoSight(llm_for_plan, llm_for_act, llm_for_tool, llm_for_vision, work_space_path)
    result = cosight.execute("帮我写一篇中兴通讯的分析报告")
    logger.info("final result is %s", result)
