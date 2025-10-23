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


from typing import Callable

from .scorer import question_scorer
import datetime
import traceback
import os
from pathlib import Path
import json



def extract_fields_from_jsonl(target_id, jsonl_file="simpleQA/simpleqa/sampled_data_10pct.jsonl"):
    """
    从JSONL文件中根据id提取对应的字段

    参数:
        jsonl_file: JSONL文件路径
        target_id: 要查找的目标id

    返回:
        如果找到匹配的id，返回包含所需字段的字典；否则返回None
    """
    try:
        with open(jsonl_file, 'r', encoding='utf-8') as f:
            for line in f:
                # 去除行首尾的空白字符
                line = line.strip()
                if not line:
                    continue

                # 解析JSON对象
                try:
                    data = json.loads(line)
                except json.JSONDecodeError as e:
                    print(f"解析JSON时出错: {e}，行内容: {line}")
                    continue

                # 检查是否包含id字段并且匹配目标id
                if 'id' in data and data['id'] == target_id:
                    # 提取所需字段
                    result = {
                        'id': data['id'],
                        'question': data.get('input_query'),
                        'answer': data.get('expected_answer')
                    }
                    return result

        # 如果循环结束仍未找到匹配的id
        print(f"未找到id为'{target_id}'的条目")
        return None

    except FileNotFoundError:
        print(f"错误: 文件'{jsonl_file}'不存在")
        return None
    except Exception as e:
        print(f"处理文件时发生错误: {e}")
        return None


def simpleqa(
    process_message,
    task_id: str  = "1",
    file_path: str  = "simpleQA/simpleqa/sampled_data_10pct.jsonl",
    first_task_id: str = None,
    postcall: Callable = None
) -> dict:
    # 这个需要换一下
    # read dataset
    data = extract_fields_from_jsonl(task_id, file_path)
    total_time = []
    results = []

    work_space_location = (
        Path(os.environ['WORKSPACE_PATH'])
    )

    # 防止附属文件出现反复嵌套的情况
    # task_work_space = (work_space_location / task_id)
    task_work_space = work_space_location
    os.makedirs(task_work_space, exist_ok=True)
    os.environ['WORKSPACE_PATH'] = task_work_space.as_posix()
    work_space_file = ''

    # copy_to_workspace(data["image"].tolist()[0], work_space_file)
    # message = data['prompt'].format(file=work_space_file, question=data['question'].tolist()[0])

    prompt = "Please answer the question:\n\n{question}"
    message = prompt.format(file=work_space_file, question=data['question'])

    real_answer = None
    error_result = None
    timestr = datetime.datetime.today().strftime('%Y-%m-%d %H:%M:%S')
    start_time = datetime.datetime.today()
    print(f'{timestr} start task {task_id}')
    try:
        real_answer = process_message(message)
        print(f'\n')
    except Exception as e:
        error_result = f'process question failed: {e}'
        print(traceback.format_exc())

    real_answer = 'None' if real_answer is None else real_answer

    score, explanation = question_scorer(
        model_answer=real_answer, ground_truth=data["answer"]
    )

    timestr = datetime.datetime.today().strftime('%Y-%m-%d %H:%M:%S')
    end_time = datetime.datetime.today()
    time_diff = end_time - start_time
    total_time.append(time_diff)
    print(f'{timestr} end task {task_id} time_diff: {time_diff}')
    result = {
        "task_id": task_id,
        "question": data['question'],
        "answer": data['answer'],
        "model_answer": real_answer,
        "score": 1 if score else 0,
        "elapsed time": str(time_diff)
    }

    results.append(result)

    if postcall:
        result_path = (task_work_space / f'results_{task_id}.json').as_posix()
        postcall([result], result_path)

    return results





