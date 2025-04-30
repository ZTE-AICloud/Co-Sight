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
from typing import Any, Literal
import json
import shutil
import os


def gaia_dataset(
        input_prompt: str | None = None,
        subset: Literal[
            "2023_all", "2023_level1", "2023_level2", "2023_level3"
        ] = "2023_all",
        split: Literal["test", "validation"] = "validation",
        task_id: str | list = None
) -> list[dict]:
    GAIA_DATASET_LOCATION = (
            Path(__file__).parent / "dataset" / "GAIA"
    )

    WORK_SPACE_LOCATION = (
            Path(os.environ['WORKSPACE_PATH'])
    )

    def record_to_sample(record: dict[str, Any]) -> dict[str, Any]:

        prompt = input_prompt or DEFAULT_INPUT_PROMPT
        ori_question = question = record["Question"]
        files_location = GAIA_DATASET_LOCATION / "2023" / split
        file_path = (files_location / record["file_name"]).as_posix() if record["file_name"] else ''
        work_space_file = (WORK_SPACE_LOCATION / record["file_name"]).as_posix() if record["file_name"] else ''

        metadata = record["Annotator Metadata"]
        steps = metadata['Steps']
        tools = metadata['Tools']

        input_question = prompt.format(file=work_space_file, question=ori_question)

        sample = {
            "input": input_question,
            "task_id": record["task_id"],
            "Question": ori_question,
            "Level": record["Level"],
            "Final answer": record["Final answer"],
            "file_name": record["file_name"],
            "dataset_file": file_path,
            "prompt": DEFAULT_INPUT_PROMPT
        }

        return sample

    samples = []
    metadata_path = GAIA_DATASET_LOCATION / "2023" / split / "metadata.jsonl"
    with metadata_path.open('r', encoding='utf-8') as file:
        for line in file:
            samples.append(record_to_sample(json.loads(line)))

    level = subset.split('_')[1]

    task_id_list = None
    if isinstance(task_id, str):
        task_id_list = [task_id]
    if isinstance(task_id, list):
        task_id_list = task_id

    if task_id_list:
        dataset = [sample for sample in samples if sample["task_id"] in task_id_list]
    elif level != 'all':
        dataset = [sample for sample in samples if f'level{sample["Level"]}' == level]
    else:
        dataset = samples

    return dataset


DEFAULT_INPUT_PROMPT = """Please answer the question below. 

{file}

Here is the question:

{question}"""

