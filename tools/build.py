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
import time
from pathlib import Path
from datetime import timedelta
import re

def run_command(command):
    """运行命令并打印输出"""
    print(f"运行命令: {command}")
    process = subprocess.Popen(
        command, 
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        shell=True,
        universal_newlines=True,
        encoding='utf-8',
        errors='replace'
    )
    
    for line in process.stdout:
        print(line, end='')
    
    process.wait()
    if process.returncode != 0:
        print(f"命令执行失败，退出码: {process.returncode}")
        sys.exit(process.returncode)

def collect_modules(start_path, prefix=""):
    """递归收集指定路径下的所有Python模块"""
    modules = []
    
    if not os.path.exists(start_path):
        return modules
        
    for item in os.listdir(start_path):
        item_path = os.path.join(start_path, item)
        
        if item.startswith('__pycache__') or item.startswith('.'):
            continue
            
        if os.path.isfile(item_path) and item.endswith('.py'):
            module_name = item[:-3]
            if prefix:
                modules.append(f"{prefix}.{module_name}")
            else:
                modules.append(module_name)
                
        elif os.path.isdir(item_path):
            if os.path.exists(os.path.join(item_path, '__init__.py')):
                new_prefix = f"{prefix}.{item}" if prefix else item
                modules.append(new_prefix)
                modules.extend(collect_modules(item_path, new_prefix))
    
    return modules

def main():
    """主打包函数"""
    start_time = time.time()
    
    print("开始打包NAE-Manus...")

    # 确保dist目录是空的
    dist_dir = Path("dist")
    if dist_dir.exists():
        shutil.rmtree(dist_dir)
    os.makedirs(dist_dir)
    
    # 调整当前目录的获取方式
    current_dir = os.path.dirname(os.path.abspath(__file__))  # tools目录
    project_root = os.path.dirname(current_dir)  # 项目根目录
    manus_server_dir = os.path.join(project_root, 'cosight_server')  # manus_server目录
    
    separator = ";" if sys.platform.startswith("win") else ":"
    
    # 更新数据文件路径
    data_files = [
        f"{os.path.join(manus_server_dir, 'web')}{separator}web",
        f"{os.path.join(manus_server_dir, 'deep_research/services/i18n.json')}{separator}cosight_server/deep_research/services",
        f"{os.path.join(project_root, 'app/cosight/tool/deep_search/common/i18n.json')}{separator}app/cosight/tool/deep_search/common",
        f"{os.path.join(project_root, 'config')}{separator}config"
    ]
    
    # 创建spec文件
    spec_file = os.path.join(current_dir, 'NAE-Manus.spec')
    with open(spec_file, 'w', encoding='utf-8') as f:
        # 更新图标和主程序路径
        icon_path = os.path.join(manus_server_dir, "web/favicon.ico").replace("\\", "\\\\")
        main_py_path = os.path.join(manus_server_dir, 'deep_research/main.py').replace('\\', '\\\\')
        
        # 构建数据文件列表
        datas_list = []
        for data_file in data_files:
            src, dest = data_file.split(separator)
            if os.path.exists(src):
                src_escaped = src.replace('\\', '\\\\')
                datas_list.append(f"(r'{src_escaped}', r'{dest}')")
        
        datas_str = ",\n        ".join(datas_list)
        
        # 在spec文件生成部分添加平台检测
        binaries_list = []
        if sys.platform.startswith('linux'):
            # 查找expat库，优先使用conda环境中的库
            expat_paths = [
                # 首先检查conda环境中的库
                os.path.join(sys.prefix, 'lib', 'libexpat.so.1'),
                # 然后检查常见的系统路径
                '/usr/lib/x86_64-linux-gnu/libexpat.so.1',
                '/usr/lib/libexpat.so.1',
                '/lib/x86_64-linux-gnu/libexpat.so.1'
            ]
            
            for path in expat_paths:
                if os.path.exists(path):
                    binaries_list.append(f"(r'{path}', '.')")
                    print(f"找到并添加expat库: {path}")
                    break
            else:
                print("警告: 未找到libexpat.so.1库，这可能导致打包的应用程序在某些系统上无法运行")
        
        # 写入完整的spec文件内容
        f.write(f"""# -*- mode: python ; coding: utf-8 -*-

block_cipher = None

a = Analysis(
    [r'{main_py_path}'],
    pathex=[],
    binaries=[{', '.join(binaries_list)}],
    datas=[
        {datas_str}
    ],
    hiddenimports=[
        # 基本导入
        'uvicorn.logging', 'uvicorn.loops', 'uvicorn.loops.auto',
        'uvicorn.protocols', 'uvicorn.protocols.http', 'uvicorn.protocols.http.auto',
        'uvicorn.lifespan', 'uvicorn.lifespan.on',
        'boto3', 'botocore', 'scipy.io.matlab', 'tensorflow',
        
        # mem0相关模块
        'mem0', 'mem0.configs', 'mem0.configs.vector_stores',
        'mem0.configs.vector_stores.qdrant', 'mem0.memory', 'mem0.memory.main',
        'mem0.vector_stores.configs', 'mem0.vector_stores',
        'mem0.vector_stores.qdrant',
        
        # browser_use相关模块
        'browser_use', 'browser_use.agent', 'browser_use.agent.memory',
        'browser_use.agent.memory.service', 'browser_use.agent.service',
        
        # 向量存储相关依赖
        'qdrant_client',
""")

        # 添加zagents_framework模块
        zagents_framework_path = os.path.join(project_root, 'app')
        if os.path.exists(zagents_framework_path):
            modules = collect_modules(zagents_framework_path, 'app')
            for module in modules:
                f.write(f"\n        '{module}',")
        
        f.write("""
    ],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    cipher=block_cipher,
    noarchive=False,
)

pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name='NAE-Manus',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=True,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=r'""" + icon_path + """',
)

coll = COLLECT(
    exe,
    a.binaries,
    a.zipfiles,
    a.datas,
    strip=False,
    upx=False,
    upx_exclude=[],
    name='NAE-Manus',
)
""")

    # 使用--clean参数强制重新构建
    run_command(f"pyinstaller --clean {spec_file}")
    
    # 更新输出目录路径
    output_dir = os.path.join('dist', 'NAE-Manus')
    
    # 检查并手动复制必要的数据文件
    print("检查并手动复制必要的数据文件...")
    for data_file in data_files:
        src, dest = data_file.split(separator)
        if os.path.exists(src):
            dest_path = os.path.join(output_dir, dest)
            os.makedirs(os.path.dirname(dest_path), exist_ok=True)
            
            if os.path.isdir(src):
                if not os.path.exists(dest_path):
                    print(f"手动复制目录: {src} -> {dest_path}")
                    shutil.copytree(src, dest_path)
            else:
                print(f"手动复制文件: {src} -> {dest_path}")
                shutil.copy2(src, dest_path)
    
    # 处理 .env 文件
    print("处理环境配置文件...")
    env_file = os.path.join(project_root, '.env')
    if os.path.exists(env_file):
        # 读取原始 .env 文件
        with open(env_file, 'r', encoding='utf-8') as f:
            env_content = f.read()
        
        # 创建示例 .env 文件，移除敏感信息
        example_env_content = env_content
        # 替换所有 API 密钥为占位符
        example_env_content = re.sub(r'(API_KEY=)([^\s]+)', r'\1your-key-here', example_env_content)
        example_env_content = re.sub(r'(TAVILY_API_KEY=)([^\s]+)', r'\1tvly-dev-your-key-here', example_env_content)
        example_env_content = re.sub(r'(GOOGLE_API_KEY=)([^\s]+)', r'\1your-key-here', example_env_content)
        
        # 将示例 .env 文件复制到输出目录
        dist_env_file = os.path.join(output_dir, '.env.example')
        with open(dist_env_file, 'w', encoding='utf-8') as f:
            f.write("# 示例配置文件 - 请根据需要修改并重命名为 .env\n")
            f.write("# 应用程序将在启动时读取此文件\n\n")
            f.write(example_env_content)
        
        print(f"✓ 已创建示例环境配置文件: {dist_env_file}")
        
        # 创建一个配置说明文档
        config_readme = os.path.join(output_dir, 'CONFIG.md')
        with open(config_readme, 'w', encoding='utf-8') as f:
            f.write("""# 配置说明

## 环境配置文件

本应用使用 `.env` 文件来配置环境变量，包括第三方服务的 API 密钥等。

### 使用方法

1. 找到 `.env.example` 示例配置文件
2. 将其复制并重命名为 `.env`（注意包含前面的点）
3. 使用文本编辑器（如记事本）打开 `.env` 文件
4. 根据需要修改配置项，特别是各个 API 密钥
5. 保存文件
6. **重要：修改配置后必须重启应用程序才能生效**

### 配置项说明

#### 基本配置
- `ENVIRONMENT`: 运行环境，可设为 development 或 production

#### 主模型配置
- `API_KEY`: 主要语言模型的 API 密钥（必填）
- `API_BASE_URL`: API 服务的基础 URL
- `MODEL_NAME`: 使用的模型名称
- `MAX_TOKENS`: 生成文本的最大token数
- `TEMPERATURE`: 生成文本的创造性程度（0.0-1.0）
- `PROXY`: 代理服务器地址（可选）

#### 可选模型配置（所有可选）
您可以为不同的任务设置不同的模型：
- `PLAN_API_KEY`, `PLAN_API_BASE_URL`, `PLAN_MODEL_NAME`: 用于规划任务的模型
- `ACT_API_KEY`, `ACT_API_BASE_URL`, `ACT_MODEL_NAME`: 用于执行任务的模型
- `TOOL_API_KEY`, `TOOL_API_BASE_URL`, `TOOL_MODEL_NAME`: 用于工具使用的模型
- `VISION_API_KEY`, `VISION_API_BASE_URL`, `VISION_MODEL_NAME`: 用于视觉任务的模型

#### 搜索工具配置（可选）
- `TAVILY_API_KEY`: Tavily搜索API密钥
- `GOOGLE_API_KEY`: Google搜索API密钥
- `SEARCH_ENGINE_ID`: Google自定义搜索引擎ID

**重要提示：**
- 配置文件中的 API 密钥是敏感信息，请勿分享给他人
- 应用程序需要至少设置主模型的 API_KEY 才能正常工作
- 如不设置可选模型，系统将使用主模型配置
- 配置更改后，需要重启应用程序才能生效
""")
        print(f"✓ 已创建配置说明文档: {config_readme}")

    # 计算执行时间
    end_time = time.time()
    elapsed_time = time.time() - start_time
    elapsed_time_formatted = str(timedelta(seconds=int(elapsed_time)))
    
    print(f"打包完成。可执行文件位于dist/NAE-Manus目录中。")
    print(f"总执行时间: {elapsed_time_formatted} (小时:分钟:秒)")

    # 验证打包结果
    print("验证打包结果...")
    expected_dirs = ['web']
    for dir_name in expected_dirs:
        check_path = os.path.join(output_dir, dir_name)
        if os.path.exists(check_path):
            print(f"✓ 目录 {dir_name} 已成功打包")
        else:
            print(f"✗ 警告: 目录 {dir_name} 不存在于打包结果中!")

if __name__ == "__main__":
    main()