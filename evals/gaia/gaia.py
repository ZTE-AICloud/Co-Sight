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

from pathlib import Path
from typing import Any, Literal, Callable

from .dataset import gaia_dataset
from .scorer import question_scorer
import datetime
import shutil
import traceback
import os






def gaia(
    process_message,
    input_prompt: str | None = None,
    subset: Literal[
        "2023_all", "2023_level1", "2023_level2", "2023_level3"
    ] = "2023_all",
    split: Literal["test", "validation"] = "validation",
    task_id: str = None,
    first_task_id: str = None,
    postcall: Callable = None
) -> dict:
    # read dataset
    dataset = gaia_dataset(
        input_prompt=input_prompt,
        subset=subset,
        split=split,
        task_id=task_id
    )
    results = []
    skip_task = not first_task_id is None
    total_time = []

    work_space_location = (
        Path(os.environ['WORKSPACE_PATH'])
    )

    for data in dataset:
        task_id = data['task_id']

        if skip_task:
            if first_task_id == task_id:
                skip_task = False
            else:
                print(f'skip {task_id}')
                continue

        task_work_space = (work_space_location / task_id)
        os.makedirs(task_work_space, exist_ok=True)
        os.environ['WORKSPACE_PATH'] = task_work_space.as_posix()
        work_space_file = (task_work_space / data["file_name"]).as_posix() if data["file_name"] else ''

        copy_to_workspace(data["dataset_file"], work_space_file)
        message = data['prompt'].format(file=work_space_file, question=data['Question'])

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
            model_answer=real_answer, ground_truth=data["Final answer"]
        )

        timestr = datetime.datetime.today().strftime('%Y-%m-%d %H:%M:%S')
        end_time = datetime.datetime.today()
        time_diff = end_time - start_time
        total_time.append(time_diff)
        print(f'{timestr} end task {task_id} time_diff: {time_diff}')
        result = {
            "input": message,
            "task_id": data["task_id"],
            "Question": data["Question"],
            "Level": data["Level"],
            "Final answer": data["Final answer"],
            "model_answer": real_answer,
            "error": error_result,
            "file_name": data["file_name"],
            "score": 1 if score else 0,
            "elapsed time": str(time_diff)
        }
        results.append(result)

        if postcall:
            result_path = (task_work_space / f'results_{task_id}.json').as_posix()
            postcall([result], result_path)

    return results

def copy_to_workspace(source_file, destination_file):
    if not source_file and not destination_file:
        return

    try:
        # 复制文件
        shutil.copy(source_file, destination_file)
        print(f"文件 {source_file} 已成功复制到 {destination_file}")
    except FileNotFoundError:
        print(f"源文件 {source_file} 未找到")
    except PermissionError:
        print(f"没有权限复制文件 {source_file}")
    except shutil.SameFileError:
        print(f"源文件和目标文件相同")
    except Exception as e:
        print(f"复制文件时发生错误: {e}")

def gaia_level1(**kwargs: Any) -> dict:
    return gaia(subset="2023_level1", **kwargs)



def gaia_level2(**kwargs: Any) -> dict:
    return gaia(subset="2023_level2", **kwargs)



def gaia_level3(**kwargs: Any) -> dict:
    return gaia(subset="2023_level3", **kwargs)

