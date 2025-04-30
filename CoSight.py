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
from app.cosight.agent.actor.instance.actor_agent_instance import create_actor_instance
from llm import llm_for_plan, llm_for_act, llm_for_tool, llm_for_vision
from work_space import WORKSPACE_PATH
from app.cosight.task.plan_report_manager import plan_report_event_manager


import os
import time

from app.cosight.agent.actor.task_actor_agent import TaskActorAgent
from app.cosight.agent.planner.instance.planner_agent_instance import create_planner_instance
from app.cosight.agent.planner.task_plannr_agent import TaskPlannerAgent
from app.cosight.task.task_manager import TaskManager
from app.cosight.task.todolist import Plan
from app.cosight.task.time_record_util import time_record


class CoSight:
    def __init__(self, plan_llm, act_llm, tool_llm, vision_llm):
        self.plan_id = f"plan_{int(time.time())}"
        self.plan = Plan()
        TaskManager.set_plan(self.plan_id, self.plan)
        self.task_planner_agent = TaskPlannerAgent(create_planner_instance("task_planner_agent"), plan_llm,
                                                   self.plan_id)
        self.act_llm = act_llm  # Store llm for later use
        self.tool_llm = tool_llm
        self.vision_llm = vision_llm

    @time_record
    def execute(self, question, output_format=""):
        create_task = question
        retry_count = 0
        while not self.plan.get_ready_steps() and retry_count < 3:
            create_result = self.task_planner_agent.create_plan(create_task, output_format)
            create_task += f"\nThe plan creation result is: {create_result}\nCreation failed, please carefully review the plan creation rules and select the create_plan tool to create the plan"
            retry_count += 1
        while True:
            ready_steps = self.plan.get_ready_steps()
            if not ready_steps:
                print("No more ready steps to execute")
                break
            print(f"Found {ready_steps} ready steps to execute")

            results = self.execute_steps(question, ready_steps)
            print(f"All steps completed with results: {results}")
            # 可配置是否只在堵塞的时候再重规划，提高效率
            # todo 这里没有实时上报
            plan_report_event_manager.publish("plan_process", self.plan)
            # re_plan_result = self.task_planner_agent.re_plan(question, output_format)
            # print(f"re-plan_result is {re_plan_result}")
        return self.task_planner_agent.finalize_plan(question, output_format)

    def execute_steps(self, question, ready_steps):
        from threading import Thread, Semaphore
        from queue import Queue

        results = {}
        result_queue = Queue()
        semaphore = Semaphore(min(5, len(ready_steps)))

        def execute_step(step_index):
            semaphore.acquire()
            try:
                print(f"Starting execution of step {step_index}")
                # 每个线程创建独立的TaskActorAgent实例
                task_actor_agent = TaskActorAgent(create_actor_instance(f"actor_for_step_{step_index}"), self.act_llm,
                                                  self.vision_llm, self.tool_llm, self.plan_id)
                result = task_actor_agent.act(question=question, step_index=step_index)
                print(f"Completed execution of step {step_index} with result: {result}")
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
    os.makedirs(WORKSPACE_PATH, exist_ok=True)
    os.environ['WORKSPACE_PATH'] = WORKSPACE_PATH

    # 配置CoSight
    cosight = CoSight(llm_for_plan, llm_for_act, llm_for_tool, llm_for_vision)

    # 运行CoSight
    result = cosight.execute("帮我写一篇中兴通讯的分析报告")
    print(f"final result is {result}")
