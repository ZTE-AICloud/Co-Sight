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

import re
from typing import List, Optional, Dict, Tuple
import os
import platform
from pathlib import PureWindowsPath, PurePosixPath

# 在文件开头添加全局字典
folder_files_map: Dict[str, List[str]] = {}
subfolder_files_map: Dict[str, List[str]] = {}

class Plan:
    """Represents a single plan with steps, statuses, and execution details as a DAG."""

    def __init__(self, title: str = "", steps: List[str] = None, dependencies: Dict[int, List[int]] = None):
        self.title = title
        self.steps = steps if steps else []
        # 使用步骤内容（中文）作为key存储状态、备注和详细信息
        self.step_statuses = {step: "not_started" for step in self.steps}
        self.step_notes = {step: "" for step in self.steps}
        self.step_details = {step: "" for step in self.steps}
        self.step_files = {step: "" for step in self.steps}
        # 使用邻接表表示依赖关系
        if dependencies:
            self.dependencies = dependencies
        else:
            self.dependencies = {i: [i-1] for i in range(1, len(self.steps))} if len(self.steps) > 1 else {}
        self.result = ""

    def set_plan_result(self, plan_result):
        self.result = plan_result

    def get_plan_result(self):
        return self.result

    def get_ready_steps(self) -> List[int]:
        """获取所有前置依赖都已完成的步骤索引

        返回:
            List[int]: 可立即执行的步骤索引列表（返回所有符合条件的步骤）
        """
        print(f"get_ready_steps dependencies: {self.dependencies}")
        ready_steps = []
        for step_index in range(len(self.steps)):
            # 获取该步骤的所有依赖
            dependencies = self.dependencies.get(step_index, [])

            # 检查所有依赖是否都已完成
            if all(self.step_statuses.get(self.steps[dep]) != "not_started" for dep in dependencies):
                # 检查步骤本身是否未开始
                if self.step_statuses.get(self.steps[step_index]) == "not_started":
                    ready_steps.append(step_index)

        return ready_steps

    def update(self, title: Optional[str] = None, steps: Optional[List[str]] = None,
               dependencies: Optional[Dict[int, List[int]]] = None) -> None:
        """Update the plan with new title, steps, or dependencies while preserving completed steps."""
        if title:
            self.title = title
        if type(steps) == str:
            tmep_str = str(steps)
            steps = tmep_str.split("\n")
        if steps:
            # Preserve all existing steps and their statuses
            new_steps = []
            new_statuses = {}
            new_notes = {}
            new_details = {}

            # First, process all steps in the input order
            for step in steps:
                # If step exists in current steps and is started, preserve it
                if step in self.steps and self.step_statuses.get(step) != "not_started":
                    new_steps.append(step)
                    new_statuses[step] = self.step_statuses.get(step)
                    new_notes[step] = self.step_notes.get(step)
                    new_details[step] = self.step_details.get(step)
                # If step exists in current steps and is not started, preserve as not_started
                elif step in self.steps:
                    new_steps.append(step)
                    new_statuses[step] = "not_started"
                    new_notes[step] = self.step_notes.get(step)
                    new_details[step] = self.step_details.get(step)
                # If step is new, add as not_started
                else:
                    new_steps.append(step)
                    new_statuses[step] = "not_started"
                    new_notes[step] = ""
                    new_details[step] = ""

            self.steps = new_steps
            self.step_statuses = new_statuses
            self.step_notes = new_notes
            self.step_details = new_details
        print(f"before update dependencies: {self.dependencies}")
        if dependencies:
            self.dependencies.clear()
            dependencies = {int(k): v for k, v in dependencies.items()}
            self.dependencies.update(dependencies)
        else:
            self.dependencies = {i: [i-1] for i in range(1, len(steps))} if len(steps) > 1 else {}
        print(f"after update dependencies: {self.dependencies}")


    def mark_step(self, step_index: int, step_status: Optional[str] = None, step_notes: Optional[str] = None) -> None:
        """Mark a single step with specific statuses, notes, and details.

        Args:
            step_index (int): Index of the step to update
            step_status (Optional[str]): New status for the step
            step_notes (Optional[str]): Notes for the step
        """
        # Validate step index
        if step_index < 0 or step_index >= len(self.steps):
            raise ValueError(f"Invalid step_index: {step_index}. Valid indices range from 0 to {len(self.steps) - 1}.")
        print(f"step_index: {step_index}, step_status is {step_status},step_notes is {step_notes}")
        step = self.steps[step_index]

        # Update step status
        if step_status is not None:
            self.step_statuses[step] = step_status

        # Update step notes
        if step_notes is not None:
            step_notes, file_path_info = process_text_with_workspace(step_notes)
            self.step_notes[step] = step_notes
            self.step_files[step] = file_path_info

        # Validate status if marking as completed
        if step_status == "completed":
            # Check if all dependencies are completed
            if not all(self.step_statuses[self.steps[dep]] == "completed" for dep in
                       self.dependencies.get(step_index, [])):
                raise ValueError(f"Cannot complete step {step_index} before its dependencies are completed")

    def get_progress(self) -> Dict[str, int]:
        """Get progress statistics of the plan."""
        return {
            "total": len(self.steps),
            "completed": sum(1 for status in self.step_statuses.values() if status == "completed"),
            "in_progress": sum(1 for status in self.step_statuses.values() if status == "in_progress"),
            "blocked": sum(1 for status in self.step_statuses.values() if status == "blocked"),
            "not_started": sum(1 for status in self.step_statuses.values() if status == "not_started")
        }

    def format(self, with_detail: bool = False) -> str:
        """Format the plan for display."""
        output = f"Plan: {self.title}\n"
        output += "=" * len(output) + "\n\n"

        progress = self.get_progress()
        output += f"Progress: {progress['completed']}/{progress['total']} steps completed "
        if progress['total'] > 0:
            percentage = (progress['completed'] / progress['total']) * 100
            output += f"({percentage:.1f}%)\n"
        else:
            output += "(0%)\n"

        output += f"Status: {progress['completed']} completed, {progress['in_progress']} in progress, "
        output += f"{progress['blocked']} blocked, {progress['not_started']} not started\n\n"
        output += "Steps:\n"

        for i, step in enumerate(self.steps):
            status_symbol = {
                "not_started": "[ ]",
                "in_progress": "[→]",
                "completed": "[✓]",
                "blocked": "[!]",
            }.get(self.step_statuses.get(step), "[ ]")

            # 显示依赖关系
            deps = self.dependencies.get(i, [])
            dep_str = f" (depends on: {', '.join(map(str, deps))})" if deps else ""
            output += f"Step{i} :{status_symbol} {step}{dep_str}\n"
            if self.step_notes.get(step):
                output += f"   Notes: {self.step_notes.get(step)}\nDetails: {self.step_details.get(step)}\n" if with_detail else f"   Notes: {self.step_notes.get(step)}\n"

        return output

    def has_blocked_steps(self) -> bool:
        """Check if there are any blocked steps in the plan.
        
        Returns:
            bool: True if any step is blocked, False otherwise
        """
        return any(status == "blocked" for status in self.step_statuses.values())


def get_last_folder_name() -> str:
    workspace_path = os.environ.get('WORKSPACE_PATH')
    if not workspace_path:
        raise ValueError("环境变量 'WORKSPACE_PATH' 未设置。")

    current_os = platform.system()
    if current_os == 'Windows':
        path_obj = PureWindowsPath(workspace_path)
    else:
        path_obj = PurePosixPath(workspace_path)

    return path_obj.name


def extract_and_replace_paths(text: str, folder_name: str) -> Tuple[str, List[Dict[str, str]]]:
    # 支持的文件扩展名
    valid_extensions = r"(txt|md|pdf|docx|xlsx|csv|json|xml|html|png|jpg|jpeg|svg|py)"

    # ✅ Linux/macOS 风格: /xxx/yyy/zzz/file.ext
    # ✅ Windows 风格: C:\xxx\yyy\file.ext （或 UNC 网络路径 \\Server\Share\file.ext）
    path_file_pattern = rf'([a-zA-Z]:\\[^\s《》]+?\.{valid_extensions}|/[^\s《》]+?\.{valid_extensions})'

    # ✅ 中文书名号引用的文件名（不区分平台）
    quoted_file_pattern = rf'《([^《》\s]+?\.{valid_extensions})》'

    result_list: List[Dict[str, str]] = []
    
    # 初始化该文件夹的文件列表（如果不存在）
    if folder_name not in folder_files_map:
        folder_files_map[folder_name] = []

    def replace_path_file(match):
        full_path = match.group(1)
        filename = os.path.basename(full_path.replace("\\", "/"))  # 把反斜杠变成斜杠后再提取
        new_path = f"{folder_name}/{filename}"
        
        # 如果文件名不在该文件夹的列表中，则添加
        # if filename not in folder_files_map[folder_name]:
        #     folder_files_map[folder_name].append(filename)
        #     result_list.append({
        #         "name": filename,
        #         "path": new_path
        #     })
        return new_path

    def replace_quoted_file(match):
        filename = match.group(1)
        new_path = f"{folder_name}/{filename}"
        
        # 如果文件名不在该文件夹的列表中，则添加
        # if filename not in folder_files_map[folder_name]:
        #     folder_files_map[folder_name].append(filename)
        #     result_list.append({
        #         "name": filename,
        #         "path": new_path
        #     })
        return new_path

    new_text = re.sub(path_file_pattern, replace_path_file, text)
    new_text = re.sub(quoted_file_pattern, replace_quoted_file, new_text)

    # 再次读取工作空间目录下的所有文件
    workspace_path = os.environ.get('WORKSPACE_PATH')
    if workspace_path:
        try:
            # 遍历工作空间目录下的所有文件
            for filename in os.listdir(workspace_path):
                # 如果文件名不在该文件夹的列表中，则添加
                if filename not in folder_files_map[folder_name]:
                    folder_files_map[folder_name].append(filename)
                    result_list.append({
                        "name": filename,
                        "path": f"{folder_name}/{filename}"
                    })

            # 遍历工作空间目录下的所有子目录
            for root, dirs, files in os.walk(workspace_path):
                print(f"root:{root}")
                if root != workspace_path:  # 跳过根目录，因为已经在上面处理过了
                    # 获取相对路径
                    rel_path = os.path.relpath(root, workspace_path)
                    # 构建文件夹的唯一标识
                    folder_key = f"{folder_name}/{rel_path}"
                    
                    # 初始化该文件夹的文件列表（如果不存在）
                    if folder_key not in subfolder_files_map:
                        subfolder_files_map[folder_key] = []
                        print(f"subfolder_files_map: {subfolder_files_map}")
                    
                    for filename in files:
                        # 如果文件名不在该文件夹的列表中，则添加
                        if filename not in subfolder_files_map[folder_key]:
                            subfolder_files_map[folder_key].append(filename)
                            # 构建完整的相对路径
                            full_rel_path = f"{folder_name}/{rel_path}/{filename}"
                            result_list.append({
                                "name": filename,
                                "path": full_rel_path
                            })
                            print(f"dirs_result_list:{result_list}")
        except Exception as e:
            print(f"Error reading workspace directory: {e}")

    return new_text, result_list


def process_text_with_workspace(text: str) -> Tuple[str, List[Dict[str, str]]]:
    folder_name = get_last_folder_name()
    return extract_and_replace_paths(text, folder_name)


if __name__ == "__main__":
    # 创建Plan
    plan = Plan("测试计划", [
        "步骤1",
        "步骤2",
        "步骤3",
        "步骤4",
        "步骤5"
    ])
    # 设置依赖关系
    plan.add_dependency(1, 0)  # 步骤2依赖于步骤1
    plan.add_dependency(2, 0)  # 步骤3依赖于步骤1
    plan.add_dependency(3, 1)  # 步骤4依赖于步骤2
    plan.add_dependency(4, 2)  # 步骤5依赖于步骤3
    plan.mark_step(0, "completed")
    plan.mark_step(1, "completed")
    plan.mark_step(2, "completed")
    result = plan.get_ready_steps()
    print(result)
