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
import sys
import shutil
import subprocess
from pathlib import Path

def run_command(command, cwd=None):
    """运行命令并打印输出"""
    print(f"运行命令: {command}")
    process = subprocess.Popen(
        command, 
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        shell=True,
        universal_newlines=True,
        encoding='utf-8',
        errors='replace',
        cwd=cwd  # 指定工作目录
    )
    
    for line in process.stdout:
        print(line, end='')
    
    process.wait()
    if process.returncode != 0:
        print(f"命令执行失败，退出码: {process.returncode}")
        sys.exit(process.returncode)

def main():
    """主函数：构建web并复制到目标目录"""
    # 获取项目相关目录
    current_dir = os.path.dirname(os.path.abspath(__file__))  # tools目录
    project_root = os.path.dirname(current_dir)  # 项目根目录
    manus_ui_dir = os.path.join(project_root, 'cosight_ui')  # manus_ui目录
    manus_server_web_dir = os.path.join(project_root, 'cosight_server', 'web')  # 目标web目录

    # 检查cosight_ui目录是否存在
    if not os.path.exists(manus_ui_dir):
        print(f"错误: manus_ui目录不存在: {manus_ui_dir}")
        sys.exit(1)

    print("=== 开始构建web文件 ===")
    
    # 1. 在cosight_ui目录下执行npm run build
    print("\n1. 执行npm build...")
    try:
        run_command("npm run build", cwd=manus_ui_dir)
    except Exception as e:
        print(f"npm build失败: {str(e)}")
        sys.exit(1)

    # 2. 检查构建输出目录是否存在
    ui_dist_dir = os.path.join(manus_ui_dir, 'dist', 'html')
    if not os.path.exists(ui_dist_dir):
        print(f"错误: 构建输出目录不存在: {ui_dist_dir}")
        sys.exit(1)

    # 3. 清空cosight_server的web目录
    print("\n2. 清空目标web目录...")
    if os.path.exists(manus_server_web_dir):
        try:
            shutil.rmtree(manus_server_web_dir)
        except Exception as e:
            print(f"清空web目录失败: {str(e)}")
            sys.exit(1)
    
    # 4. 复制文件
    print("\n3. 复制构建文件到web目录...")
    try:
        # 确保目标目录存在
        os.makedirs(manus_server_web_dir, exist_ok=True)
        
        # 复制所有文件
        for item in os.listdir(ui_dist_dir):
            src = os.path.join(ui_dist_dir, item)
            dst = os.path.join(manus_server_web_dir, item)
            if os.path.isdir(src):
                shutil.copytree(src, dst)
            else:
                shutil.copy2(src, dst)
        print("文件复制完成！")
    except Exception as e:
        print(f"复制文件失败: {str(e)}")
        sys.exit(1)

    print("\n=== web文件构建完成 ===")
    print(f"文件已复制到: {manus_server_web_dir}")

    # 验证结果
    if os.path.exists(manus_server_web_dir):
        file_count = sum([len(files) for _, _, files in os.walk(manus_server_web_dir)])
        print(f"web目录中共有 {file_count} 个文件")
        if file_count == 0:
            print("警告: web目录是空的，可能复制过程出现问题")
    else:
        print("错误: web目录不存在，复制过程可能失败")

if __name__ == "__main__":
    main() 