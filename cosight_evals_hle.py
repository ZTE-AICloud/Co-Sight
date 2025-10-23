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

import datetime
import json
import os
import traceback
from pathlib import Path
import shutil
from app.manus.manus_hle import Manus
from evals.gaia import hle, pre_judge_hle, post_judge_hle, post_judge_hle_four_route
from llm import llm_for_plan, llm_for_act, llm_for_tool, llm_for_vision
from llm import llm_for_plan_route2, llm_for_act_route2, llm_for_tool_route2, llm_for_vision_route2
import csv

gaia_timestamp = datetime.datetime.today().strftime('%Y%m%d_%H%M%S')
WORKSPACE_PATH = (
        Path(__file__).parent / "workspace" / gaia_timestamp
)

LOG_PATH = (
        Path(__file__).parent / "logs"
)


def manus_route1():
    def execute(question):
        manus = Manus(llm_for_plan, llm_for_act, llm_for_tool, llm_for_vision)
        result, raw_result = manus.execute(question)
        print(f"final result is >>{result}<<")
        return result, raw_result

    return execute


def manus_route2():
    def execute(question):
        manus = Manus(llm_for_plan_route2, llm_for_act_route2, llm_for_tool_route2, llm_for_vision_route2)
        result, raw_result = manus.execute(question)
        print(f"final result is >>{result}<<")
        return result, raw_result

    return execute


def save_results(results: str, results_path: str):
    try:
        data = {
            "eval": {
                "model": os.environ.get("MODEL_NAME"),
                "date": datetime.datetime.today().strftime('%Y-%m-%d %H:%M:%S'),
            },
            "detail": results
        }
        with open(results_path, 'w', encoding='utf-8') as file:
            json.dump(data, file, ensure_ascii=False, indent=2)
        print(f"保存 {results_path} 成功")
    except Exception as e:
        print(f"保存 {results_path} 发生错误: {e}")
        print(traceback.format_exc())


def save_submissions(results: str, submissions_path: str):
    try:
        lines = []
        data = {
            "task_id": result["task_id"],
            "model_answer": result["model_answer"]
        }
        lines.append(json.dumps(data, ensure_ascii=False))

        with open(submissions_path, 'w', encoding='utf-8') as file:
            file.writelines(lines)

        print(f"保存 {submissions_path} 成功")
    except Exception as e:
        print(f"保存 {submissions_path} 发生错误: {e}")

def save_str_list_to_csv(str_list, filename):
    """保存字符串元素的一维列表为CSV文件"""
    try:
        with open(filename, 'w', newline='', encoding='utf-8') as csvfile:
            writer = csv.writer(csvfile)
            for s in str_list:
                writer.writerow([s])  # 字符串直接写入，无需额外处理
        print(f"字符串列表已保存到 {filename}")
    except Exception as e:
        print(f"保存失败：{e}")

def extract_ids_in_range(jsonl_file, start=20, end=40):
    """
    从JSONL文件中提取指定范围内的id列表

    参数:
        jsonl_file: JSONL文件路径
        start: 起始位置（包含），默认为20
        end: 结束位置（包含），默认为40

    返回:
        包含指定范围内id的列表，如果出错则返回空列表
    """
    ids = []

    try:
        with open(jsonl_file, 'r', encoding='utf-8') as f:
            # 从1开始计数行号，符合日常"第n个"的表述习惯
            for line_num, line in enumerate(f, start=1):
                line = line.strip()
                if not line:  # 跳过空行
                    continue

                try:
                    data = json.loads(line)
                except json.JSONDecodeError as e:
                    print(f"解析JSON时出错: {e}，行号: {line_num}")
                    continue

                # 检查是否包含id字段
                if 'id' not in data:
                    print(f"警告: 行号 {line_num} 不包含'id'字段")
                    continue

                # 如果当前行在目标范围内，添加id到列表
                if start <= line_num <= end:
                    ids.append(data['id'])

                # 如果已经超过结束位置，提前退出循环
                if line_num > end:
                    break

        return ids

    except FileNotFoundError:
        print(f"错误: 文件'{jsonl_file}'不存在")
        return []
    except Exception as e:
        print(f"处理文件时发生错误: {e}")
        return []

if __name__ == '__main__':

    os.makedirs(WORKSPACE_PATH, exist_ok=True)
    os.makedirs(LOG_PATH, exist_ok=True)
    os.environ['WORKSPACE_PATH'] = WORKSPACE_PATH.as_posix()
    os.environ['RESULTS_PATH'] = WORKSPACE_PATH.as_posix()

    manus_route1 = manus_route1()  # set radical expert agent
    manus_route2 = manus_route2()  # set conservative expert agent

    save_data = []

    out_file = "results_hle7.jsonl"
    id_start = 120
    id_end = id_start + 19

    print(f"开始处理从第{id_start}个到第{id_end}个任务...")
    # jsonl_file = "HLE_results/HLE_results_gemini2.5pro/diff-id-all.jsonl"
    jsonl_file = "data_hle/data/hle_dataset_part6.jsonl"
    task_ids = extract_ids_in_range(jsonl_file, start=id_start, end=id_end)
    # for task_id in task_ids[id_start:id_end]:
    for task_id in task_ids:

        for i in range(2):
            if i == 0:
                # Conservative expert agent
                result, analysis = hle(process_message=manus_route2,
                                       task_id=task_id,
                                       postcall=save_results
                                       )

            elif i == 1:
                # Radical expert agent
                result, analysis = hle(process_message=manus_route1,
                                       task_id=task_id,
                                       postcall=save_results
                                       )
                answer1 = result["model_answer"]
                analysis1 = analysis

                answer2 = result["model_answer"]
                analysis2 = analysis
            elif i == 2:
                # Radical expert agent
                result, analysis = hle(process_message=manus_route1,
                                       task_id=task_id,
                                       postcall=save_results
                                       )
                answer3 = result["model_answer"]
                analysis3 = analysis
            elif i == 3:
                # Radical expert agent
                result, analysis = hle(process_message=manus_route1,
                                       task_id=task_id,
                                       postcall=save_results
                                       )
                answer4 = result["model_answer"]
                analysis4 = analysis

        judge_response = post_judge_hle(manus_route2, result["question"], answer1, answer2, analysis1, analysis2)
        # judge_response = post_judge_hle_four_route(manus_route2, result["question"], answer1, answer2, answer3, answer4, analysis1, analysis2, analysis3, analysis4)

        data_item = {
            "task_id": result["task_id"],
            "answer": result["answer"],
            "model_answer": judge_response,
            "category": result["category"],
            "question": result["question"]
        }
        save_data.append(data_item)

        with open(out_file, "w", encoding="utf-8") as f:
            for item in save_data:
                # 每个条目作为一行JSON写入文件
                f.write(json.dumps(item, ensure_ascii=False) + "\n")

        datestr = datetime.datetime.today().strftime('%Y%m%d%H%M%S')
        save_results(result, (WORKSPACE_PATH / f'result_{datestr}.json').as_posix())

        # 移动文件
        try:
            shutil.move("logs/console.log", WORKSPACE_PATH)
            print(f"文件已移动到 {WORKSPACE_PATH}")
        except FileNotFoundError:
            print("❌ 文件不存在，请检查路径！")
        except Exception as e:
            print(f"发生错误：{e}")


