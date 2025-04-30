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

import os

# 代理服务器地址
proxy = "http://proxyhk.zte.com.cn:80"

# 设置 HTTP 和 HTTPS 代理
os.environ['ALL_PROXY'] = ''
os.environ['all_proxy'] = ''
os.environ['SOCKS_PROXY'] = ''
os.environ['socks_proxy'] = ''
os.environ['HTTPS_PROXY'] = proxy
os.environ['https_proxy'] = proxy
os.environ['HTTP_PROXY'] = proxy
os.environ['http_proxy'] = proxy
os.environ['URL_CONTEXT_PATH'] = 'proxy'

import sys
if not sys.platform.startswith('win'):
    __import__('pysqlite3')
    sys.modules['sqlite3'] = sys.modules.pop('pysqlite3')
import json
import os
from pathlib import Path
from typing import Any

from app.manus.task.plan_report_manager import plan_report_event_manager
from llm import llm_for_plan, llm_for_act, llm_for_tool, llm_for_vision

sys.path.insert(1, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..")))
sys.path.insert(1, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", "..")))

import os
import time

from app.manus import WORKSPACE_PATH
from app.manus.agent.actor.instance.actor_agent_instance import create_actor_instance
from app.manus.agent.actor.task_actor_agent import TaskActorAgent
from app.manus.agent.planner.instance.planner_agent_instance import create_planner_instance
from app.manus.agent.planner.task_plannr_agent import TaskPlannerAgent
from app.manus.task.task_manager import TaskManager
from app.manus.task.todolist import Plan
from app.manus.task.time_record_util import time_record


class Manus:
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
            plan_report_event_manager.publish("plan_process", self.plan)
            # 可配置是否只在堵塞的时候再重规划，提高效率
            # todo 这里没有实时上报
            plan_report_event_manager.publish("plan_process", self.plan)
            re_plan_result = self.task_planner_agent.re_plan(question, output_format)
            print(f"re-plan_result is {re_plan_result}")
        return self.task_planner_agent.finalize_plan(question, output_format)


    @time_record
    def execute_actor(self,question):
        task_actor_agent = TaskActorAgent(create_actor_instance(f"actor_for_step_{0}"), self.act_llm,
                                          self.vision_llm, self.tool_llm, self.plan_id)
        result = task_actor_agent.single_act(question)
        print(f"Completed execution of step {0} with result: {result}")
        return result


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


def append_create_plan(data: Any):
    """
    将数据追加写入当前目录下的 plan.log 文件
    支持结构化数据自动转为JSON字符串

    Args:
        data: 要写入的数据（支持字典、列表等可JSON序列化的类型）
    """
    try:
        # 获取当前路径并构建文件路径
        current_dir = Path.cwd()
        file_path = current_dir / "plan.log"

        # 准备写入内容（自动处理不同类型）
        if isinstance(data, (dict, list)):
            content = json.dumps(data, ensure_ascii=False, indent=2) + "\n"
        else:
            content = str(data) + "\n"

        # 追加写入文件（自动创建文件）
        with open(file_path, mode='a', encoding='utf-8') as f:
            f.write(content)

    except json.JSONDecodeError as e:
        print(f"JSON序列化失败: {e}")
    except IOError as e:
        print(f"文件写入失败: {e}")
    except Exception as e:
        print(f"未知错误: {e}")


if __name__ == '__main__':
    # 配置工作区
    os.makedirs(WORKSPACE_PATH, exist_ok=True)
    os.environ['WORKSPACE_PATH'] = WORKSPACE_PATH

    # 配置Manus
    manus = Manus(llm_for_plan, llm_for_act, llm_for_tool, llm_for_vision)

    # 运行Manus
    result = manus.execute("帮我写一篇中兴通讯的分析报告")
    print(f"final result is {result}")
