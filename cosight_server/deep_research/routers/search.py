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

import json
import asyncio
import os
from datetime import datetime
from pathlib import Path
from typing import Any
from fastapi import APIRouter, Body
from starlette.requests import Request
from fastapi.responses import StreamingResponse

from llm import llm_for_plan, llm_for_act, llm_for_tool, llm_for_vision
from cosight_server.deep_research.services.i18n_service import i18n
from cosight_server.sdk.common.logger_util import get_logger

# 引入CoSight所需的依赖
from app.cosight.task.plan_report_manager import plan_report_event_manager
from app.cosight.task.todolist import Plan
from CoSight import CoSight

logger = get_logger("ai-search")
searchRouter = APIRouter()

# 使用从环境变量获取的WORKSPACE_PATH
WORKSPACE_PATH = os.environ.get('WORKSPACE_PATH')
logger.info(f"Using WORKSPACE_PATH: {WORKSPACE_PATH}")

# 确保logs目录存在
LOGS_PATH = os.path.join(WORKSPACE_PATH, 'logs')
if not os.path.exists(LOGS_PATH):
    os.makedirs(LOGS_PATH)

# 用于存储plan数据的队列和事件循环引用
plan_queue = None
main_loop = None


def append_create_plan(data: Any):
    """
    将数据追加写入LOGS_PATH下的plan.log文件，并将数据放入队列以发送给客户端

    Args:
        data: 要写入的数据（支持字典、列表等可JSON序列化的类型）
    """
    try:
        # 使用LOGS_PATH构建文件路径
        file_path = Path(LOGS_PATH) / "plan.log"

        # 处理Plan对象转换为可序列化的dict
        if isinstance(data, Plan):
            plan_dict = {
                "title": data.title if hasattr(data, 'title') else "",
                "steps": data.steps if hasattr(data, 'steps') else [],
                "step_files": data.step_files if hasattr(data, 'step_files') else {},
                "step_statuses": data.step_statuses if hasattr(data, 'step_statuses') else {},
                "step_notes": data.step_notes if hasattr(data, 'step_notes') else {},
                "step_details": data.step_details if hasattr(data, 'step_details') else {},
                "dependencies": {str(k): v for k, v in data.dependencies.items()} if hasattr(data, 'dependencies') else {},
                "progress": data.get_progress() if hasattr(data, 'get_progress') and callable(data.get_progress) else {},
                "result": data.get_plan_result() if hasattr(data, 'get_plan_result') and callable(data.get_plan_result) else ""
            }
            logger.info(f"step_files:{data.step_files}")

            # logger.info(f"Plan对象已转换为字典: {plan_dict}")
            data = plan_dict

        # 准备写入内容（自动处理不同类型）
        if isinstance(data, (dict, list)):
            try:
                content = json.dumps(data, ensure_ascii=False, indent=2) + "\n"
            except TypeError as e:
                logger.error(f"JSON序列化失败，尝试转换对象: {e}", exc_info=True)
                # 尝试将复杂对象转换为字符串
                if isinstance(data, dict):
                    serializable_data = {k: str(v) for k, v in data.items()}
                elif isinstance(data, list):
                    serializable_data = [str(item) if not isinstance(item, (dict, list, str, int, float, bool, type(None))) else item for item in data]
                content = json.dumps(serializable_data, ensure_ascii=False, indent=2) + "\n"
        else:
            content = str(data) + "\n"

        # 记录序列化后的内容到日志
        # logger.info(f"序列化后的Plan数据: {content.strip()}")

        # 追加写入文件（自动创建文件）
        with open(file_path, mode='a', encoding='utf-8') as f:
            f.write(content)

        # 将数据放入队列以便流式发送 - 使用run_coroutine_threadsafe
        global plan_queue, main_loop
        if plan_queue is not None and main_loop is not None:
            # 确保队列中的数据是可JSON序列化的
            if isinstance(data, Plan):
                # 已经在上面转换过了
                asyncio.run_coroutine_threadsafe(plan_queue.put(plan_dict), main_loop)
            else:
                asyncio.run_coroutine_threadsafe(plan_queue.put(data), main_loop)

    except json.JSONDecodeError as e:
        logger.error(f"JSON序列化失败: {e}", exc_info=True)
    except IOError as e:
        logger.error(f"文件写入失败: {e}", exc_info=True)
    except Exception as e:
        logger.error(f"未知错误: {e}", exc_info=True)


def validate_search_input(params: dict) -> dict | None:
    """
    验证搜索输入参数
    Args:
        params: 输入参数字典
    Returns:
        如果验证失败返回错误响应，验证通过返回None
    """
    if not (content := params.get('content')) or len(content) == 0:
        return {
            "contentType": "multi-modal",
            "content": [{"type": "text", "value": i18n.t('invalid_command')}],
            "promptSentences": []
        }
    return None


@searchRouter.post("/deep-research/search")
async def search(request: Request, params: Any = Body(None)):
    logger.info(f"=====params:{params}")

    # if not await session_manager.authority(request):
    #     raise HTTPException(status_code=403, detail="Forbidden")

    if result := validate_search_input(params):
        return result

    # 获取查询内容
    content_array = params.get('content', [])
    query_content = content_array[0]['value'] if content_array and isinstance(
        content_array, list) and len(content_array) > 0 and 'value' in content_array[0] else ""

    async def generator_func():
        # 清空之前可能存在的队列数据并保存当前事件循环
        global plan_queue, main_loop
        plan_queue = asyncio.Queue()
        main_loop = asyncio.get_running_loop()

        # 保存最新的plan数据
        latest_plan = None

        # 在子线程中执行CoSight任务
        def run_manus():
            try:
                # 订阅事件
                plan_report_event_manager.subscribe(event_type="plan_created", callback=append_create_plan)
                plan_report_event_manager.subscribe(event_type="plan_updated", callback=append_create_plan)
                plan_report_event_manager.subscribe(event_type="plan_process", callback=append_create_plan)
                plan_report_event_manager.subscribe(event_type="plan_result", callback=append_create_plan)

                # 构造路径：/xxx/xxx/work_space/work_space_时间戳
                timestamp = datetime.now().strftime('%Y%m%d_%H%M%S_%f')
                WORKSPACE_PATH_TIME = os.path.join(WORKSPACE_PATH, f'work_space_{timestamp}')
                print(f":WORKSPACE_PATH_TIME:{WORKSPACE_PATH_TIME}")
                os.makedirs(WORKSPACE_PATH_TIME, exist_ok=True)
                os.environ['WORKSPACE_PATH'] = WORKSPACE_PATH_TIME

                # 初始化CoSight并执行
                cosight = CoSight(llm_for_plan, llm_for_act, llm_for_tool, llm_for_vision)
                result = cosight.execute(query_content)
                logger.info(f"final result is {result}")

            except Exception as e:
                logger.error(f"CoSight执行错误: {e}", exc_info=True)

        # 启动子线程执行CoSight
        import threading
        thread = threading.Thread(target=run_manus)
        thread.daemon = True
        thread.start()

        # 持续从队列获取数据并产生响应
        while True:
            try:
                # 等待队列中的数据，设置超时防止无限等待
                data = await asyncio.wait_for(plan_queue.get(), timeout=60.0)
                # print(f"queue_data:{data}")
                if isinstance(data, dict) and "result" in data and data['result']:
                    latest_plan = data
                    latest_plan["status_text"] = "执行完成"
                    yield {"plan": latest_plan}
                    break

                # 更新最新plan数据
                latest_plan = data
                # 添加状态文本
                latest_plan["status_text"] = "正在执行中"
                # 发送完整的plan
                yield {"plan": latest_plan}

            except asyncio.TimeoutError:
                # 超时，可能任务仍在进行，发送最新plan加上等待状态
                if latest_plan:
                    latest_plan["status_text"] = "等待计划更新..."
                    yield {"plan": latest_plan}
                else:
                    yield {"plan": {"title": "等待任务执行", "status_text": "等待计划更新...", "steps": []}}
            except Exception as e:
                logger.error(f"生成响应错误: {e}", exc_info=True)
                # 发送错误状态，但保留最新plan
                if latest_plan:
                    latest_plan["status_text"] = f"生成响应出错: {str(e)}"
                    yield {"plan": latest_plan}
                else:
                    yield {"plan": {"title": "任务出错", "status_text": f"生成响应出错: {str(e)}", "steps": []}}
                break

    async def generate_stream_response(generator_func, params):
        try:
            async for response_data in generator_func():
                response_json = {
                    "contentType": "lui-message-manus-step",
                    "sessionInfo": params.get("sessionInfo", {}),
                    "code": 0,
                    "message": "ok",
                    "task": "chat",
                    "changeType": "replace",
                    "content": response_data["plan"]  # 直接使用plan数据作为content
                }

                yield json.dumps(response_json, ensure_ascii=False).encode('utf-8') + b'\n'
                await asyncio.sleep(0)

        except Exception as exc:
            error_msg = "生成回复时发生错误。"
            logger.exception(error_msg)
            error_response = json.dumps({
                "contentType": "lui-message-manus-step",
                "content": {"intro": error_msg, "steps": []},
                "sessionInfo": params.get("sessionInfo", {}),
                "code": 1,
                "message": "error",
                "task": "chat",
                "changeType": "replace"
            }, ensure_ascii=False).encode('utf-8') + b'\n'
            yield error_response

    return StreamingResponse(
        generate_stream_response(generator_func, params),
        media_type="application/json"
    )
