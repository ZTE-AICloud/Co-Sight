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
from app.cosight.agent.actor.instance.actor_agent_instance import create_actor_instance
from llm import llm_for_plan, llm_for_act, llm_for_tool, llm_for_vision
from app.cosight.task.plan_report_manager import plan_report_event_manager


import os
import time
from threading import Thread

from app.cosight.agent.actor.task_actor_agent import TaskActorAgent
from app.cosight.agent.planner.instance.planner_agent_instance import create_planner_instance
from app.cosight.agent.planner.task_plannr_agent import TaskPlannerAgent
from app.cosight.task.task_manager import TaskManager
from app.cosight.task.todolist import Plan
from app.cosight.task.time_record_util import time_record
from app.common.logger_util import logger


class CoSight:
    def __init__(self, plan_llm, act_llm, tool_llm, vision_llm, work_space_path: str = None, message_uuid: str|None = None):
        self.work_space_path = work_space_path or os.getenv("WORKSPACE_PATH") or os.getcwd()
        self.plan_id = message_uuid if message_uuid else f"plan_{int(time.time())}"
        self.plan = Plan()
        TaskManager.set_plan(self.plan_id, self.plan)
        
        # 设置Langfuse追踪上下文
        # 使用plan_id作为session_id，让整个任务的所有traces都关联在一起
        # trace_id会自动生成，每个Agent调用都是独立的trace
        # 这样在Langfuse中可以看到完整的session replay
        plan_llm.set_trace_context(
            trace_id=None,  # 不指定trace_id，让每次调用自动生成
            session_id=self.plan_id,  # 使用plan_id作为session_id
            tags=["planning"],
            metadata={"agent_type": "planner", "plan_id": self.plan_id}
        )
        act_llm.set_trace_context(
            trace_id=None,
            session_id=self.plan_id,
            tags=["execution"],
            metadata={"agent_type": "actor", "plan_id": self.plan_id}
        )
        tool_llm.set_trace_context(
            trace_id=None,
            session_id=self.plan_id,
            tags=["tool"],
            metadata={"agent_type": "tool", "plan_id": self.plan_id}
        )
        vision_llm.set_trace_context(
            trace_id=None,
            session_id=self.plan_id,
            tags=["vision"],
            metadata={"agent_type": "vision", "plan_id": self.plan_id}
        )
        
        self.task_planner_agent = TaskPlannerAgent(create_planner_instance("task_planner_agent"), plan_llm,
                                                   self.plan_id)
        self.act_llm = act_llm  # Store llm for later use
        self.tool_llm = tool_llm
        self.vision_llm = vision_llm

    @time_record
    def execute(self, question, output_format=""):
        # 更新所有LLM的metadata，添加任务信息
        task_metadata = {
            "task_question": question[:200] if len(question) > 200 else question,
            "plan_id": self.plan_id
        }
        
        for llm in [self.task_planner_agent.llm, self.act_llm, self.tool_llm, self.vision_llm]:
            if hasattr(llm, 'current_metadata'):
                llm.current_metadata.update(task_metadata)
        
        create_task = question
        retry_count = 0
        while not self.plan.get_ready_steps() and retry_count < 3:
            create_result = self.task_planner_agent.create_plan(create_task, output_format)
            create_task += f"\nThe plan creation result is: {create_result}\nCreation failed, please carefully review the plan creation rules and select the create_plan tool to create the plan"
            retry_count += 1
        
        # 使用持续监控的方式，而不是等待所有步骤完成
        active_threads = {}  # 存储活跃的线程 {step_index: thread}
        
        while True:
            # 检查是否有新的可执行步骤
            ready_steps = self.plan.get_ready_steps()
            
            # 启动新的可执行步骤
            for step_index in ready_steps:
                if step_index not in active_threads:
                    logger.info(f"Starting new step {step_index}")
                    thread = Thread(target=self._execute_single_step, args=(question, step_index))
                    thread.daemon = True
                    thread.start()
                    active_threads[step_index] = thread
            
            # 检查已完成的线程
            completed_steps = []
            for step_index, thread in active_threads.items():
                if not thread.is_alive():
                    completed_steps.append(step_index)
            
            # 移除已完成的线程
            for step_index in completed_steps:
                del active_threads[step_index]
                logger.info(f"Step {step_index} completed and thread removed")
            
            # 如果没有活跃线程且没有可执行步骤，则退出
            if not active_threads and not ready_steps:
                logger.info("No more ready steps to execute and no active threads")
                break
            
            # 短暂休眠，避免CPU占用过高
            import time
            time.sleep(0.1)
        
        return self.task_planner_agent.finalize_plan(question, output_format)

    def _execute_single_step(self, question, step_index):
        """执行单个步骤"""
        try:
            logger.info(f"Starting execution of step {step_index}")
            # 每个线程创建独立的TaskActorAgent实例
            task_actor_agent = TaskActorAgent(
                create_actor_instance(f"actor_for_step_{step_index}", self.work_space_path),
                self.act_llm,
                self.vision_llm,
                self.tool_llm,
                self.plan_id,
                work_space_path=self.work_space_path
            )
            result = task_actor_agent.act(question=question, step_index=step_index)
            logger.info(f"Completed execution of step {step_index} with result: {result}")
        except Exception as e:
            logger.error(f"Error executing step {step_index}: {e}", exc_info=True)

    def execute_steps(self, question, ready_steps):
        from threading import Thread, Semaphore
        from queue import Queue

        results = {}
        result_queue = Queue()
        semaphore = Semaphore(min(5, len(ready_steps)))

        def execute_step(step_index):
            semaphore.acquire()
            try:
                logger.info(f"Starting execution of step {step_index}")
                # 每个线程创建独立的TaskActorAgent实例
                task_actor_agent = TaskActorAgent(
                    create_actor_instance(f"actor_for_step_{step_index}", self.work_space_path),
                    self.act_llm,
                    self.vision_llm,
                    self.tool_llm,
                    self.plan_id,
                    work_space_path=self.work_space_path
                )
                result = task_actor_agent.act(question=question, step_index=step_index)
                logger.info(f"Completed execution of step {step_index} with result: {result}")
                result_queue.put((step_index, result))
            finally:
                semaphore.release()

        # 为每个ready_step创建并执行线程
        threads = []
        for step_index in ready_steps:
            thread = Thread(target=execute_step, args=(step_index,))
            thread.start()
            threads.append(thread)

        # 等待所有线程完成
        for thread in threads:
            thread.join()

        # 收集结果
        while not result_queue.empty():
            step_index, result = result_queue.get()
            results[step_index] = result

        return results


if __name__ == '__main__':
    # 配置工作区
    BASE_DIR = os.path.dirname(os.path.abspath(__file__))
    # 获取当前时间并格式化
    timestamp = datetime.now().strftime('%Y%m%d_%H%M%S_%f')
    # 构造路径：/xxx/xxx/work_space/work_space_时间戳
    work_space_path = os.path.join(BASE_DIR, 'work_space', f'work_space_{timestamp}')
    os.makedirs(work_space_path, exist_ok=True)

    # 配置CoSight
    cosight = CoSight(llm_for_plan, llm_for_act, llm_for_tool, llm_for_vision, work_space_path)

    # 运行CoSight
    result = cosight.execute("帮我写一篇中兴通讯的分析报告")
    logger.info(f"final result is {result}")
