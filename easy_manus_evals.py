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

from app.manus.manus import Manus as EasyManus
from evals.gaia import gaia_level1
from llm import llm_for_plan, llm_for_act, llm_for_tool, llm_for_vision

gaia_timestamp = datetime.datetime.today().strftime('%Y%m%d_%H%M%S')
WORKSPACE_PATH = (
        Path(__file__).parent / "workspace" / gaia_timestamp
)

LOG_PATH = (
        Path(__file__).parent / "logs"
)


def easy_manus():
    def execute(question):
        manus = EasyManus(llm_for_plan, llm_for_act, llm_for_tool, llm_for_vision)

        result = manus.execute(question)
        print(f"final result is >>{result}<<")
        return result

    return execute


def save_results(results: str, results_path: str):
    try:
        scores = {"all": 0, 1: 0, 2: 0, 3: 0}
        num_questions = {"all": 0, 1: 0, 2: 0, 3: 0}

        for result in results:
            score = result["score"]
            level = result["Level"]
            scores["all"] += score
            scores[level] += score
            num_questions["all"] += 1
            num_questions[level] += 1

        data = {
            "eval": {
                "model": os.environ.get("MODEL_NAME"),
                "score": 100 * scores["all"] / len(results) if results else 0,
                "score_level1": 100 * scores[1] / num_questions[1] if num_questions[1] else 0,
                "score_level2": 100 * scores[2] / num_questions[2] if num_questions[2] else 0,
                "score_level3": 100 * scores[3] / num_questions[3] if num_questions[3] else 0,
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
        for result in results:
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


if __name__ == '__main__':
    os.makedirs(WORKSPACE_PATH, exist_ok=True)
    os.makedirs(LOG_PATH, exist_ok=True)
    os.environ['WORKSPACE_PATH'] = WORKSPACE_PATH.as_posix()
    os.environ['RESULTS_PATH'] = WORKSPACE_PATH.as_posix()

    manus = easy_manus()
    results = gaia_level1(process_message=manus,
                          postcall=save_results
                          )

    datestr = datetime.datetime.today().strftime('%Y%m%d%H%M%S')
    save_results(results, (WORKSPACE_PATH / f'result_level1_{datestr}.json').as_posix())

