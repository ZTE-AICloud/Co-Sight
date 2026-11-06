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

import time
from functools import wraps
from app.common.logger_util import logger

def time_record(func):
    """
    记录函数执行时间的装饰器（精简版日志）

    使用说明（给开发者/使用者看的简单说明）：
    - 自动打印一行统一格式的耗时日志，方便在日志中快速对比各阶段耗时
    - 会自动根据函数名粗分为三类：
        - LLM：大模型思考 / 对话
        - TOOL：工具调用
        - STEP：其他步骤
    - 若调用时传入了 keyword 参数：
        - function_name：会出现在日志里，方便区分具体工具
        - step_index：会出现在日志里，方便对应到计划中的某一步
    """

    @wraps(func)
    def wrapper(*args, **kwargs):
        start_time = time.time()
        try:
            return func(*args, **kwargs)
        finally:
            elapsed_time = time.time() - start_time

            # 根据函数名简单归类
            fname = func.__name__
            if fname in ("create_with_tools", "chat_to_llm"):
                category = "LLM"
            elif "tool" in fname:
                category = "TOOL"
            else:
                category = "STEP"

            # 提取常用的上下文字段（如果有的话）
            function_name = kwargs.get("function_name") or ""
            step_index = kwargs.get("step_index")

            extra_parts = []
            if function_name:
                extra_parts.append(f"func={function_name}")
            if step_index is not None:
                extra_parts.append(f"step={step_index}")

            extra = f" ({', '.join(extra_parts)})" if extra_parts else ""

            # 统一、简洁的耗时日志格式
            logger.info(
                f"[TIME][{category}] {func.__qualname__}{extra} executed in {elapsed_time:.4f}s"
            )

    return wrapper
