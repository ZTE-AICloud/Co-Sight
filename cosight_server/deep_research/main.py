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
sys.path.insert(1, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..")))

from fastapi import FastAPI, Request
from fastapi.staticfiles import StaticFiles
from fastapi.responses import JSONResponse

# 添加这段代码来加载.env文件
try:
    from dotenv import load_dotenv
    # 尝试从当前目录加载.env文件
    env_loaded = load_dotenv()
    if env_loaded:
        print("已成功加载.env配置文件")
    else:
        print("警告: .env文件未找到或为空")
except ImportError:
    print("警告: python-dotenv模块未安装，无法自动加载.env文件")
except Exception as e:
    print(f"加载.env文件时出错: {e}")

# 添加这段代码来验证环境变量
print("\n=== 环境变量检查 ===")
env_vars_to_check = [
    "ENVIRONMENT", 
    "API_KEY",
    "API_BASE_URL",
    "MODEL_NAME",
    "MAX_TOKENS",
    "TEMPERATURE",
    "PROXY",
    # 可选配置检查
    "TAVILY_API_KEY",
    "GOOGLE_API_KEY",
    "SEARCH_ENGINE_ID"
]

# 可选的模型配置组
optional_model_configs = [
    ["PLAN_API_KEY", "PLAN_API_BASE_URL", "PLAN_MODEL_NAME"],
    ["ACT_API_KEY", "ACT_API_BASE_URL", "ACT_MODEL_NAME"],
    ["TOOL_API_KEY", "TOOL_API_BASE_URL", "TOOL_MODEL_NAME"],
    ["VISION_API_KEY", "VISION_API_BASE_URL", "VISION_MODEL_NAME"]
]

for var in env_vars_to_check:
    value = os.getenv(var)
    if value:
        # 对API密钥只显示前几个字符，保护敏感信息
        if "API_KEY" in var and len(value) > 8:
            masked_value = value[:4] + "****" + value[-4:]
            print(f"✓ {var} = {masked_value}")
        else:
            print(f"✓ {var} = {value}")
    else:
        if var in ["PROXY", "TAVILY_API_KEY", "GOOGLE_API_KEY", "SEARCH_ENGINE_ID"]:
            print(f"ℹ {var} 未设置 (可选)")
        else:
            print(f"✗ {var} 未设置")

# 检查可选的模型配置组
print("\n=== 可选模型配置检查 ===")
for config_group in optional_model_configs:
    group_name = config_group[0].split("_")[0]  # 提取PLAN/ACT/TOOL/VISION
    api_key = os.getenv(config_group[0])
    if api_key:
        print(f"✓ {group_name} 模型配置已设置")
        # 可以进一步检查该组中的其他配置
        for var in config_group[1:]:
            value = os.getenv(var)
            if value:
                if "API_KEY" in var and len(value) > 8:
                    masked_value = value[:4] + "****" + value[-4:]
                    print(f"  ✓ {var} = {masked_value}")
                else:
                    print(f"  ✓ {var} = {value}")
            else:
                print(f"  ✗ {var} 未设置")
    else:
        print(f"ℹ {group_name} 模型配置未设置 (可选)")
        
print("=== 环境变量检查结束 ===\n")

from cosight_server.deep_research.services.i18n_service import i18n
# custom_config的初始化必须放在最开始
from cosight_server.sdk.common.config import custom_config
from cosight_server.deep_research.common.config import custom_config_data
custom_config.initialize(custom_config_data)

from cosight_server.sdk.common.logger_util import get_logger

logger = get_logger("ai-search")
# 添加项目根目录到 Python 路径
root_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
logger.info(f"root_dir is >>>>>> {root_dir}")
sys.path.insert(0, root_dir)

current_file_path = os.path.abspath(__file__)
work_dir = os.path.abspath(os.path.join(current_file_path, "../../"))
os.chdir(work_dir)
logger.info(f"current work dir is >>>>>> {os.getcwd()}")

# 确保work_space目录存在，放在与upload_files相同的目录层级
if not os.path.exists("work_space"):
    os.makedirs("work_space")
# 设置WORKSPACE_PATH环境变量，使用相对路径或环境变量指定的路径
workspace_env = os.getenv("WORKSPACE_PATH_ENV")
WORKSPACE_PATH = workspace_env + "/work_space" if workspace_env else "work_space"
logger.info(f"workspace path is >>>>>> {WORKSPACE_PATH}")
# 确保logs目录存在
LOGS_PATH = os.path.join(WORKSPACE_PATH, 'logs')
if not os.path.exists(LOGS_PATH):
    os.makedirs(LOGS_PATH)
# 设置环境变量供子模块使用
os.environ['WORKSPACE_PATH'] = os.path.abspath(WORKSPACE_PATH)

# 重要：先设置好环境变量，再导入search模块
from cosight_server.deep_research.routers.search import searchRouter
from cosight_server.deep_research.routers.user_manager import userRouter
from cosight_server.deep_research.routers.websocket_manager import wsRouter
from cosight_server.deep_research.routers.common import commonRouter
from cosight_server.deep_research.routers.chat_manager import chatRouter
from cosight_server.deep_research.routers.feedback import feedbackRouter

app = FastAPI()

# 确保upload_files目录存在
if not os.path.exists("upload_files"):
    os.makedirs("upload_files")
upload_dir = os.getenv(custom_config.get("upload_dir_env"))
logger.info(f"upload dir in upload_dir_env >>>>>> {upload_dir}")
upload_dir = upload_dir + "/upload_files" if upload_dir else "upload_files"
logger.info(f"upload dir is >>>>>> {upload_dir}")

base_url = str(custom_config.get("base_api_url"))
# 挂载upload_files目录
app.mount(f"{base_url}/upload_files", StaticFiles(directory=upload_dir), name="upload_files")

# 挂载work_space目录，使前端可以访问静态资源
app.mount(f"{base_url}/work_space", StaticFiles(directory=WORKSPACE_PATH), name="work_space")
logger.info(f"work_space已挂载到: {base_url}/work_space")

# 挂载前端静态文件目录
# 原来的代码尝试不正确的路径
# web_dir = os.path.join(os.path.dirname(root_dir), "web")
# if not os.path.exists(web_dir):
#     web_dir = "cosight_server/web"

# 修改为：使用与WORKSPACE_PATH相同的逻辑来定位web目录
web_dir_env = os.getenv("WEB_DIR_ENV")
if web_dir_env:
    web_dir = web_dir_env + "/web"
else:
    # 如果没有环境变量，则使用与work_space相同的父目录
    web_dir = os.path.join(os.path.dirname(WORKSPACE_PATH), "web")
    # 如果web_dir不存在，尝试其他常见路径
    if not os.path.exists(web_dir):
        web_dir = "web"  # 当前工作目录下的web
        if not os.path.exists(web_dir):
            # 如果运行进程时从cosight_server目录启动
            web_dir = "../web"
            if not os.path.exists(web_dir):
                # 如果是从根目录启动
                web_dir = "cosight_server/web"

# 如果web目录不存在，创建一个空的web目录
if not os.path.exists(web_dir):
    logger.warning(f"Web目录不存在: {web_dir}，创建空目录")
    try:
        # 创建web目录
        os.makedirs(web_dir)
        # 创建一个简单的index.html文件，避免空目录挂载问题
        index_path = os.path.join(web_dir, "index.html")
        with open(index_path, "w") as f:
            f.write("<html><body><h1>开发模式</h1><p>这是一个自动创建的临时页面。</p></body></html>")
        logger.info(f"已创建临时web目录和index.html文件: {web_dir}")
    except Exception as e:
        logger.error(f"创建web目录失败: {str(e)}", exc_info=True)
        logger.info(f"当前工作目录: {os.getcwd()}")
        logger.info(f"尝试查找web目录...")
        # 打印当前目录下有哪些文件夹
        for item in os.listdir('.'):
            if os.path.isdir(item):
                logger.info(f"发现目录: {item}")
        # 即使创建失败也不退出，只记录警告
        logger.warning("无法创建web目录，将跳过静态文件挂载")
        web_dir = None

# 只有当web_dir存在时才挂载
if web_dir:
    logger.info(f"web dir is >>>>>> {web_dir}")
    # 在根路径挂载web目录
    app.mount(f"/cosight", StaticFiles(directory=web_dir, html=True), name="web")
    logger.info(f"前端静态文件已挂载到: /web")

app.include_router(userRouter, prefix=str(custom_config.get("base_api_url")))
app.include_router(searchRouter, prefix=str(custom_config.get("base_api_url")))
app.include_router(wsRouter, prefix=str(custom_config.get("base_chatbot_api_url")))
app.include_router(commonRouter, prefix=str(custom_config.get("base_api_url")))
app.include_router(chatRouter, prefix=str(custom_config.get("base_chatbot_api_url")))
app.include_router(feedbackRouter, prefix=str(custom_config.get("base_chatbot_api_url")))

@app.middleware("http")
async def global_exception_handler(request: Request, call_next):
    try:
        return await call_next(request)
    except Exception as e:
        logger.error(f"Unhandled exception: {e}", exc_info=True)
        return JSONResponse(status_code=500, content={"message": "An unexpected error occurred.", "details": str(e)})

if __name__ == '__main__':
    print("\n【提示】请在浏览器访问: http://localhost:7788/cosight/\n")
    import argparse
    import uvicorn
    
    # 创建命令行参数解析器
    parser = argparse.ArgumentParser(description=i18n.t('ai_search_plugin_description'))
    parser.add_argument('-p', '--port', type=int, help=i18n.t('ai_search_port_help'), default=None)
    args = parser.parse_args()
    
    logger.info('*****************')
    logger.info('plugin server staring...')
    args.port = custom_config.get("search_port")

    uvicorn.run(app=app, host="0.0.0.0", port=int(args.port))
